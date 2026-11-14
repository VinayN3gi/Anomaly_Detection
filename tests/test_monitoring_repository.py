"""Unit tests for SQLAlchemy MonitoringRepository and database models."""

from pathlib import Path
import pytest

from database.models import MonitoringResult, Website
from database.repository import (
    MonitoringRepository,
    WebsiteAlreadyExistsError,
    WebsiteNotFoundError,
)
from monitoring.probe_engine import ProbeResult
from monitoring.url_validator import SecurityValidationError


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> MonitoringRepository:
    """Initialize an isolated MonitoringRepository using a SQLite temporary database."""
    monkeypatch.setattr(
        "socket.getaddrinfo",
        lambda host, port, family=0, type=0: [
            (2, 1, 6, "", ("93.184.216.34", 80))
        ],
    )
    db_file = tmp_path / "repo_test.db"
    return MonitoringRepository(db_file)


class TestMonitoringRepository:
    """Validate CRUD operations, foreign-key cascading, and metric persistence."""

    def test_register_website_enforces_minimum_60s_interval(self, repo: MonitoringRepository) -> None:
        """Verify registration enforces >= 60 seconds minimum interval per Task 1."""
        site = repo.register_website(
            url="https://example.com",
            name="Example Prod",
            check_interval=10,  # Below minimum!
        )
        assert site.id is not None
        assert site.url == "https://example.com/"
        assert site.name == "Example Prod"
        assert site.check_interval == 60  # Enforced to 60s
        assert site.is_active is True

    def test_duplicate_registration_rejected(self, repo: MonitoringRepository) -> None:
        """Verify registering existing URL raises WebsiteAlreadyExistsError."""
        repo.register_website("https://duplicate.com")
        with pytest.raises(WebsiteAlreadyExistsError):
            repo.register_website("https://duplicate.com")

    def test_ssrf_blocked_url_rejected(self, repo: MonitoringRepository) -> None:
        """Verify private IP URL raises SecurityValidationError."""
        with pytest.raises(SecurityValidationError):
            repo.register_website("http://192.168.1.1:8080/admin")

    def test_website_activation_and_deactivation(self, repo: MonitoringRepository) -> None:
        """Verify active status toggling."""
        site = repo.register_website("https://toggle.com")
        assert site.is_active is True

        updated = repo.set_website_active(site.id, False)
        assert updated.is_active is False

        active_list = repo.list_websites(active_only=True)
        assert len(active_list) == 0

        repo.set_website_active(site.id, True)
        assert len(repo.list_websites(active_only=True)) == 1

    def test_save_and_retrieve_successful_probe(self, repo: MonitoringRepository) -> None:
        """Verify saving complete probe with all timing phases."""
        site = repo.register_website("https://metrics-test.com")

        probe = ProbeResult(
            url=site.url,
            timestamp="2026-03-01T12:00:00Z",
            is_success=True,
            status="UP",
            http_status=200,
            dns_lookup_ms=10.5,
            tcp_connect_ms=15.2,
            tls_handshake_ms=35.0,
            ttfb_ms=22.0,
            download_ms=8.0,
            total_time_ms=90.7,
            response_size_bytes=1024,
            redirect_count=0,
            ssl_valid=True,
            ssl_expiry_date="2027-01-01T00:00:00Z",
            ssl_expiry_days=300,
            dns_success=True,
            resolved_ip="93.184.216.34",
            error_type=None,
            error_message=None,
        )

        record: MonitoringResult = repo.save_probe_result(site.id, probe)
        assert record.id is not None
        assert record.website_id == site.id
        assert record.dns_lookup_ms == 10.5
        assert record.tcp_connect_ms == 15.2
        assert record.tls_handshake_ms == 35.0
        assert record.ttfb_ms == 22.0
        assert record.download_ms == 8.0
        assert record.total_time_ms == 90.7
        assert record.http_status == 200
        assert record.is_success is True

    def test_save_failed_probe_with_null_timings(self, repo: MonitoringRepository) -> None:
        """Verify failed probe saves unavailable timing phases as NULL (None)."""
        site = repo.register_website("https://failed-test.com")

        failed_probe = ProbeResult(
            url=site.url,
            timestamp="2026-03-01T12:05:00Z",
            is_success=False,
            status="DOWN",
            http_status=None,
            dns_lookup_ms=15.0,
            tcp_connect_ms=None,  # Unavailable
            tls_handshake_ms=None,  # Unavailable
            ttfb_ms=None,  # Unavailable
            download_ms=None,  # Unavailable
            total_time_ms=15.0,
            response_size_bytes=0,
            redirect_count=0,
            ssl_valid=None,
            ssl_expiry_date=None,
            ssl_expiry_days=None,
            dns_success=False,
            resolved_ip=None,
            error_type="DNSResolutionError",
            error_message="Host unreachable",
        )

        record = repo.save_probe_result(site.id, failed_probe)
        assert record.id is not None
        assert record.is_success is False
        assert record.http_status is None
        assert record.tcp_connect_ms is None
        assert record.tls_handshake_ms is None
        assert record.ttfb_ms is None
        assert record.download_ms is None
        assert record.error_type == "DNSResolutionError"

    def test_cascade_delete_removes_monitoring_results(self, repo: MonitoringRepository) -> None:
        """Verify deleting a website cascades and removes all associated results."""
        site = repo.register_website("https://delete-cascade.com")

        dummy_probe = ProbeResult(
            url=site.url,
            timestamp="2026-03-01T12:00:00Z",
            is_success=True,
            status="UP",
            http_status=200,
            dns_lookup_ms=5.0,
            tcp_connect_ms=10.0,
            tls_handshake_ms=20.0,
            ttfb_ms=15.0,
            download_ms=5.0,
            total_time_ms=55.0,
            response_size_bytes=500,
            redirect_count=0,
            ssl_valid=True,
            ssl_expiry_date="2027-01-01",
            ssl_expiry_days=250,
            dns_success=True,
            resolved_ip="93.184.216.34",
            error_type=None,
            error_message=None,
        )
        repo.save_probe_result(site.id, dummy_probe)
        assert len(repo.get_recent_results(site.id)) == 1

        repo.delete_website(site.id)

        with pytest.raises(WebsiteNotFoundError):
            repo.get_website(site.id)
        assert len(repo.get_recent_results(site.id)) == 0

    def test_aggregate_stats_computation(self, repo: MonitoringRepository) -> None:
        """Verify aggregate statistics (uptime, average response time, TTFB)."""
        site = repo.register_website("https://stats-test.com")

        p1 = ProbeResult(
            url=site.url,
            timestamp="2026-03-01T12:00:00Z",
            is_success=True,
            status="UP",
            http_status=200,
            dns_lookup_ms=10.0,
            tcp_connect_ms=10.0,
            tls_handshake_ms=20.0,
            ttfb_ms=30.0,
            download_ms=10.0,
            total_time_ms=70.0,
            response_size_bytes=1000,
            redirect_count=0,
            ssl_valid=True,
            ssl_expiry_date="2027-01-01",
            ssl_expiry_days=300,
            dns_success=True,
            resolved_ip="93.184.216.34",
            error_type=None,
            error_message=None,
        )
        p2 = ProbeResult(
            url=site.url,
            timestamp="2026-03-01T12:01:00Z",
            is_success=False,
            status="DOWN",
            http_status=500,
            dns_lookup_ms=10.0,
            tcp_connect_ms=10.0,
            tls_handshake_ms=20.0,
            ttfb_ms=50.0,
            download_ms=10.0,
            total_time_ms=130.0,
            response_size_bytes=200,
            redirect_count=0,
            ssl_valid=True,
            ssl_expiry_date="2027-01-01",
            ssl_expiry_days=300,
            dns_success=True,
            resolved_ip="93.184.216.34",
            error_type="HttpServerError",
            error_message="HTTP 500",
        )

        repo.save_probe_result(site.id, p1)
        repo.save_probe_result(site.id, p2)

        stats = repo.get_aggregate_stats(site.id)
        assert stats["total_checks"] == 2
        assert stats["uptime_percentage"] == 50.0
        assert stats["error_rate_percentage"] == 50.0
        assert stats["avg_response_time_ms"] == 100.0  # (70 + 130) / 2
        assert stats["avg_ttfb_ms"] == 40.0           # (30 + 50) / 2
