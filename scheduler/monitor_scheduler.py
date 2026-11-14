"""Asynchronous Monitoring Scheduler using APScheduler.

Coordinates non-blocking periodic probes for active websites according to their
individual check intervals. Enforces concurrency limits via asyncio.Semaphore,
prevents overlapping probes for the same website, and manages clean shutdown.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import logging
from pathlib import Path
import sys

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

import config
from database.db import get_db, get_recent_checks, save_check_result
from database.repository import MonitoringRepository
from monitoring.engine import check_website_async
from monitoring.probe_engine import ProbeResult

logger = logging.getLogger("aiops.scheduler")


class MonitoringScheduler:
    """APScheduler-powered asynchronous website probe runner."""

    def __init__(
        self,
        db_path: Path | str | None = None,
        poll_interval: float = 5.0,
        max_concurrency: int = 10,
    ) -> None:
        """Initialize scheduler configuration and concurrency controls.

        Args:
            db_path: Custom SQLite database path (optional).
            poll_interval: Scheduler tick frequency in seconds (default 5.0s).
            max_concurrency: Maximum number of concurrent probes allowed.
        """
        self.db_path = db_path
        self.poll_interval = poll_interval
        self.max_concurrency = max_concurrency
        self.repository = MonitoringRepository(db_path)
        self.scheduler = AsyncIOScheduler()
        self.semaphore = asyncio.Semaphore(max_concurrency)
        self._active_probes: set[int] = set()
        self._is_running = False

    def start(self) -> None:
        """Initialize and start the APScheduler background event loop job."""
        if self._is_running:
            return

        self._is_running = True
        if not self.scheduler.running:
            self.scheduler.add_job(
                self.run_due_checks,
                trigger=IntervalTrigger(seconds=self.poll_interval),
                id="website_monitoring_job",
                replace_existing=True,
                max_instances=1,
            )
            self.scheduler.start()
        logger.info(
            "MonitoringScheduler started with APScheduler (poll=%.1fs, max_concurrency=%d).",
            self.poll_interval,
            self.max_concurrency,
        )

    async def stop(self) -> None:
        """Shut down the background APScheduler cleanly without blocking."""
        if not self._is_running:
            return

        self._is_running = False
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
            await asyncio.sleep(0.01)
        logger.info("MonitoringScheduler stopped cleanly.")

    async def run_due_checks(self) -> list[int]:
        """Evaluate active websites and execute probes for due checks under concurrency limit.

        Returns:
            List of website IDs for which probes were dispatched.
        """
        # Support both direct SQLite db_path and repository
        if self.db_path:
            query = "SELECT id, url, check_interval FROM websites WHERE is_active = 1;"
            with get_db(self.db_path) as conn:
                active_websites = [dict(r) for r in conn.execute(query).fetchall()]
        else:
            try:
                db_sites = self.repository.list_websites(active_only=True)
                active_websites = [
                    {"id": s.id, "url": s.url, "check_interval": s.check_interval}
                    for s in db_sites
                ]
            except Exception as exc:
                logger.error("Failed to load active websites from database: %s", exc)
                return []

        now_utc = datetime.now(timezone.utc)
        dispatched_ids: list[int] = []
        tasks = []

        for site in active_websites:
            site_id = site["id"]
            url = site["url"]
            if site_id in self._active_probes:
                logger.debug(
                    "Skipping website %s (%d): probe already in flight (overlap guard).",
                    url,
                    site_id,
                )
                continue

            interval_sec = site.get("check_interval") or config.DEFAULT_CHECK_INTERVAL

            # Check timestamp of latest recorded probe
            recent = get_recent_checks(site_id, limit=1, db_path=self.db_path)
            is_due = True
            if recent and recent[0].get("timestamp"):
                try:
                    last_time = datetime.fromisoformat(recent[0]["timestamp"])
                    if (now_utc - last_time).total_seconds() < interval_sec:
                        is_due = False
                except (ValueError, TypeError):
                    is_due = True

            if is_due:
                self._active_probes.add(site_id)
                dispatched_ids.append(site_id)
                tasks.append(self._probe_worker(site_id, url))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        return dispatched_ids

    async def _probe_worker(self, website_id: int, url: str) -> ProbeResult:
        """Worker task executing probe under semaphore concurrency control."""
        async with self.semaphore:
            try:
                fn = getattr(
                    sys.modules[__name__],
                    "check_website_async",
                    check_website_async,
                )
                result = await fn(url)
                save_check_result(website_id, result, db_path=self.db_path)
                try:
                    self.repository.save_probe_result(website_id, result)
                except Exception:
                    pass
                return result
            except Exception as exc:
                logger.exception(
                    "Unexpected error probing website %d (%s): %s", website_id, url, exc
                )
                failed_res = ProbeResult(
                    url=url,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    is_success=False,
                    status="DOWN",
                    http_status=None,
                    dns_lookup_ms=None,
                    tcp_connect_ms=None,
                    tls_handshake_ms=None,
                    ttfb_ms=None,
                    download_ms=None,
                    total_time_ms=None,
                    response_size_bytes=0,
                    redirect_count=0,
                    ssl_valid=None,
                    ssl_expiry_date=None,
                    ssl_expiry_days=None,
                    dns_success=False,
                    resolved_ip=None,
                    error_type="ProbeWorkerError",
                    error_message=str(exc),
                )
                save_check_result(website_id, failed_res, db_path=self.db_path)
                try:
                    self.repository.save_probe_result(website_id, failed_res)
                except Exception:
                    pass
                return failed_res
            finally:
                self._active_probes.discard(website_id)
