"""Asynchronous Monitoring Scheduler.

Coordinates recurring background probes for all registered active websites
according to their configured check intervals.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import logging
from pathlib import Path

from database.db import get_db, get_recent_checks, save_check_result
from monitoring.engine import check_website_async

logger = logging.getLogger("aiops.scheduler")


class MonitoringScheduler:
    """Manages continuous background polling and scheduled website checks."""

    def __init__(
        self,
        db_path: Path | str | None = None,
        poll_interval: float = 5.0,
    ) -> None:
        self.db_path = db_path
        self.poll_interval = poll_interval
        self._is_running = False
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        """Start the background scheduler task in the current event loop."""
        if self._is_running:
            return
        self._is_running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(
            "MonitoringScheduler started (polling every %.1fs).", self.poll_interval
        )

    async def stop(self) -> None:
        """Stop the background scheduler cleanly."""
        if not self._is_running:
            return
        self._is_running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("MonitoringScheduler stopped.")

    async def _run_loop(self) -> None:
        """Main periodic scheduling loop."""
        while self._is_running:
            try:
                await self.run_due_checks()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(
                    "Error during scheduled monitoring cycle: %s", exc, exc_info=True
                )

            await asyncio.sleep(self.poll_interval)

    async def run_due_checks(self) -> list[int]:
        """Inspect all active websites and trigger checks for those due.

        Returns:
            List of website IDs for which checks were dispatched.
        """
        query = "SELECT id, url, check_interval FROM websites WHERE is_active = 1;"
        with get_db(self.db_path) as conn:
            active_sites = [dict(r) for r in conn.execute(query).fetchall()]

        dispatched: list[int] = []
        now = datetime.now(timezone.utc)

        tasks = []
        for site in active_sites:
            site_id = site["id"]
            interval = site["check_interval"]

            # Fetch the most recent check timestamp
            recent = get_recent_checks(site_id, limit=1, db_path=self.db_path)
            is_due = True
            if recent:
                last_time_str = recent[0]["timestamp"]
                try:
                    last_time = datetime.fromisoformat(last_time_str)
                    elapsed = (now - last_time).total_seconds()
                    if elapsed < interval:
                        is_due = False
                except Exception:
                    is_due = True

            if is_due:
                dispatched.append(site_id)
                tasks.append(self._check_and_persist(site_id, site["url"]))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        return dispatched

    async def _check_and_persist(self, website_id: int, url: str) -> None:
        """Execute check for a single site and record results."""
        try:
            result = await check_website_async(url)
            save_check_result(website_id, result, db_path=self.db_path)
            logger.debug(
                "Scheduled check completed for site %s (%s): %s",
                website_id,
                url,
                result.status,
            )
        except Exception as exc:
            logger.error("Scheduled check failed for site %s: %s", website_id, exc)
