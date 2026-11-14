"""Unit tests for the SQLite persistence and aggregation layer."""

from pathlib import Path
import pytest

from database.db import (
    get_aggregate_stats,
    get_db,
    get_recent_checks,
    init_db,
    save_check_result,
)
from monitoring.engine import WebsiteCheckResult


@pytest.fixture
def temp_db(tmp_path: Path) -> Path:
    """Initialize a clean temporary SQLite database."""
    db_file = tmp_path / "test_monitoring.db"
    init_db(db_file)
    return db_file


class TestDatabaseLayer:
    """Validate schema initialization, check persistence, and statistical aggregation."""

    def test_init_db_creates_tables(self, temp_db: Path) -> None:
        """Verify database and tables are created."""
        assert temp_db.exists()
        with get_db(temp_db) as conn:
            tables = [
                row["name"]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table';"
                ).fetchall()
            ]
            assert "websites" in tables
            assert "monitoring_checks" in tables

    def test_save_and_retrieve_checks(self, temp_db: Path) -> None:
        """Verify metric checks can be persisted and queried."""
        # Insert test website
        with get_db(temp_db) as conn:
            cur = conn.execute(
                "INSERT INTO websites (url, name, created_at, updated_at) "
                "VALUES ('https://test.com', 'Test Site', '2026-01-01', '2026-01-01');"
            )
            site_id = cur.lastrowid

        res1 = WebsiteCheckResult(
            url="https://test.com",
            timestamp="2026-03-01T12:00:00Z",
            is_up=True,
            status="UP",
            http_status_code=200,
            response_time_ms=45.2,
            ttfb_ms=30.1,
            dns_time_ms=8.5,
            ssl_valid=True,
            ssl_expiry_date="2027-01-01T00:00:00Z",
            ssl_days_remaining=300,
            response_size_bytes=1024,
            redirect_count=0,
            resolved_ip="93.184.216.34",
            error_message=None,
        )
        res2 = WebsiteCheckResult(
            url="https://test.com",
            timestamp="2026-03-01T12:01:00Z",
            is_up=False,
            status="DOWN",
            http_status_code=500,
            response_time_ms=250.0,
            ttfb_ms=240.0,
            dns_time_ms=9.0,
            ssl_valid=True,
            ssl_expiry_date="2027-01-01T00:00:00Z",
            ssl_days_remaining=300,
            response_size_bytes=512,
            redirect_count=0,
            resolved_ip="93.184.216.34",
            error_message="Server error",
        )

        id1 = save_check_result(site_id, res1, db_path=temp_db)
        id2 = save_check_result(site_id, res2, db_path=temp_db)

        assert id1 > 0
        assert id2 > id1

        checks = get_recent_checks(site_id, limit=10, db_path=temp_db)
        assert len(checks) == 2
        # Reverse chronological ordering
        assert checks[0]["timestamp"] == "2026-03-01T12:01:00Z"
        assert checks[1]["timestamp"] == "2026-03-01T12:00:00Z"

    def test_aggregate_stats_calculation(self, temp_db: Path) -> None:
        """Verify uptime percentage and latency averages are accurate."""
        with get_db(temp_db) as conn:
            cur = conn.execute(
                "INSERT INTO websites (url, name, created_at, updated_at) "
                "VALUES ('https://stats.com', 'Stats Site', '2026-01-01', '2026-01-01');"
            )
            site_id = cur.lastrowid

        # Insert 3 UP checks (50ms, 70ms, 90ms) and 1 DOWN check (150ms)
        for i, (up, rt) in enumerate(
            [(True, 50.0), (True, 70.0), (True, 90.0), (False, 150.0)]
        ):
            res = WebsiteCheckResult(
                url="https://stats.com",
                timestamp=f"2026-03-01T12:0{i}:00Z",
                is_up=up,
                status="UP" if up else "DOWN",
                http_status_code=200 if up else 500,
                response_time_ms=rt,
                ttfb_ms=rt * 0.8,
                dns_time_ms=10.0,
                ssl_valid=True,
                ssl_expiry_date="2027-01-01",
                ssl_days_remaining=300,
                response_size_bytes=1000,
                redirect_count=0,
                resolved_ip="93.184.216.34",
                error_message=None if up else "Down",
            )
            save_check_result(site_id, res, db_path=temp_db)

        stats = get_aggregate_stats(site_id, limit=10, db_path=temp_db)
        assert stats["total_checks"] == 4
        assert stats["uptime_percentage"] == 75.0  # 3/4
        assert stats["error_rate_percentage"] == 25.0  # 1/4
        assert stats["avg_response_time_ms"] == 90.0  # (50+70+90+150)/4
        assert stats["min_response_time_ms"] == 50.0
        assert stats["max_response_time_ms"] == 150.0

    def test_cascade_delete(self, temp_db: Path) -> None:
        """Verify deleting a website automatically deletes associated checks."""
        with get_db(temp_db) as conn:
            cur = conn.execute(
                "INSERT INTO websites (url, name, created_at, updated_at) "
                "VALUES ('https://delete.com', 'Delete Site', '2026-01-01', '2026-01-01');"
            )
            site_id = cur.lastrowid

        res = WebsiteCheckResult(
            url="https://delete.com",
            timestamp="2026-03-01T12:00:00Z",
            is_up=True,
            status="UP",
            http_status_code=200,
            response_time_ms=45.0,
            ttfb_ms=30.0,
            dns_time_ms=8.0,
            ssl_valid=True,
            ssl_expiry_date="2027-01-01",
            ssl_days_remaining=300,
            response_size_bytes=1024,
            redirect_count=0,
            resolved_ip="93.184.216.34",
            error_message=None,
        )
        save_check_result(site_id, res, db_path=temp_db)

        # Confirm check exists
        assert len(get_recent_checks(site_id, limit=5, db_path=temp_db)) == 1

        # Delete website
        with get_db(temp_db) as conn:
            conn.execute("DELETE FROM websites WHERE id = ?;", (site_id,))

        # Verify checks were cascaded
        assert len(get_recent_checks(site_id, limit=5, db_path=temp_db)) == 0
