"""Unit tests for the periodic background monitoring scheduler."""

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch
import pytest

from database.db import get_db, init_db, save_check_result
from monitoring.engine import WebsiteCheckResult
from scheduler.monitor_scheduler import MonitoringScheduler


@pytest.fixture
def sched_db(tmp_path: Path) -> Path:
    """Initialize a clean database for scheduler tests."""
    db_file = tmp_path / "scheduler_test.db"
    init_db(db_file)
    return db_file


@pytest.mark.asyncio
class TestMonitoringScheduler:
    """Validate scheduler interval evaluation, concurrency limits, and overlap guard."""

    async def test_scheduler_dispatches_due_checks(self, sched_db: Path) -> None:
        """Verify scheduler identifies and dispatches checks only for due sites."""
        now = datetime.now(timezone.utc)
        past_time = (now - timedelta(seconds=120)).isoformat()
        recent_time = (now - timedelta(seconds=10)).isoformat()

        # Insert 3 websites:
        # Site 1: Due (interval 60s, last checked 120s ago)
        # Site 2: Not due (interval 60s, last checked 10s ago)
        # Site 3: Inactive (interval 60s, due time, but is_active=0)
        with get_db(sched_db) as conn:
            cur1 = conn.execute(
                "INSERT INTO websites (url, check_interval, is_active, created_at, updated_at) "
                "VALUES ('https://due-site.com', 60, 1, '2026-01-01', '2026-01-01');"
            )
            id1 = cur1.lastrowid

            cur2 = conn.execute(
                "INSERT INTO websites (url, check_interval, is_active, created_at, updated_at) "
                "VALUES ('https://notdue-site.com', 60, 1, '2026-01-01', '2026-01-01');"
            )
            id2 = cur2.lastrowid

            cur3 = conn.execute(
                "INSERT INTO websites (url, check_interval, is_active, created_at, updated_at) "
                "VALUES ('https://inactive-site.com', 60, 0, '2026-01-01', '2026-01-01');"
            )
            assert cur3.lastrowid is not None

        # Insert historical checks
        dummy_res1 = WebsiteCheckResult(
            url="https://due-site.com",
            timestamp=past_time,
            is_up=True,
            status="UP",
            http_status_code=200,
            response_time_ms=50.0,
            ttfb_ms=30.0,
            dns_time_ms=5.0,
            ssl_valid=True,
            ssl_expiry_date="2027-01-01",
            ssl_days_remaining=300,
            response_size_bytes=1000,
            redirect_count=0,
            resolved_ip="93.184.216.34",
            error_message=None,
        )
        save_check_result(id1, dummy_res1, db_path=sched_db)

        dummy_res2 = WebsiteCheckResult(
            url="https://notdue-site.com",
            timestamp=recent_time,
            is_up=True,
            status="UP",
            http_status_code=200,
            response_time_ms=50.0,
            ttfb_ms=30.0,
            dns_time_ms=5.0,
            ssl_valid=True,
            ssl_expiry_date="2027-01-01",
            ssl_days_remaining=300,
            response_size_bytes=1000,
            redirect_count=0,
            resolved_ip="93.184.216.34",
            error_message=None,
        )
        save_check_result(id2, dummy_res2, db_path=sched_db)

        scheduler = MonitoringScheduler(db_path=sched_db, poll_interval=1.0)

        # Mock probe function so it doesn't make real web requests
        with patch(
            "scheduler.monitor_scheduler.check_website_async", new_callable=AsyncMock
        ) as mock_probe:
            mock_probe.return_value = dummy_res1

            dispatched_ids = await scheduler.run_due_checks()

        # Only site 1 should be dispatched
        assert dispatched_ids == [id1]
        assert mock_probe.call_count == 1

    async def test_overlap_guard_prevents_duplicate_simultaneous_probes(
        self, sched_db: Path
    ) -> None:
        """Verify in-flight probe prevents dispatching duplicate check for same site."""
        with get_db(sched_db) as conn:
            cur = conn.execute(
                "INSERT INTO websites (url, check_interval, is_active, created_at, updated_at) "
                "VALUES ('https://overlap.com', 60, 1, '2026-01-01', '2026-01-01');"
            )
            site_id = cur.lastrowid

        scheduler = MonitoringScheduler(db_path=sched_db)
        # Mark site as currently probing (in-flight)
        scheduler._active_probes.add(site_id)

        dispatched = await scheduler.run_due_checks()
        assert site_id not in dispatched

    async def test_concurrent_probe_limits_enforced_by_semaphore(
        self, sched_db: Path
    ) -> None:
        """Verify concurrency semaphore limits simultaneous executing workers."""
        max_limit = 2
        scheduler = MonitoringScheduler(
            db_path=sched_db, max_concurrency=max_limit
        )

        current_running = 0
        peak_running = 0

        async def slow_probe(url):
            nonlocal current_running, peak_running
            current_running += 1
            if current_running > peak_running:
                peak_running = current_running
            await asyncio.sleep(0.05)
            current_running -= 1
            return WebsiteCheckResult(
                url=url,
                timestamp=datetime.now(timezone.utc).isoformat(),
                is_up=True,
                status="UP",
                http_status_code=200,
                response_time_ms=50.0,
                ttfb_ms=25.0,
                dns_time_ms=5.0,
                ssl_valid=True,
                ssl_expiry_date="2027-01-01",
                ssl_days_remaining=300,
                response_size_bytes=500,
                redirect_count=0,
                resolved_ip="93.184.216.34",
                error_message=None,
            )

        with patch(
            "scheduler.monitor_scheduler.check_website_async", side_effect=slow_probe
        ):
            tasks = [
                scheduler._probe_worker(i, f"https://site{i}.com")
                for i in range(1, 6)
            ]
            await asyncio.gather(*tasks)

        assert peak_running <= max_limit

    async def test_scheduler_lifecycle(self, sched_db: Path) -> None:
        """Verify scheduler start and stop clean lifecycle."""
        scheduler = MonitoringScheduler(db_path=sched_db, poll_interval=1.0)
        scheduler.start()
        assert scheduler._is_running is True
        assert scheduler.scheduler.running is True

        await scheduler.stop()
        assert scheduler._is_running is False
        assert scheduler.scheduler.running is False
