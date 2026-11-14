"""Unit tests for the end-to-end asynchronous website probing engine."""

from unittest.mock import AsyncMock, patch
import pytest

from monitoring.dns_checker import DNSResult
from monitoring.http_checker import HTTPResult
from monitoring.probe_engine import ProbeResult, probe_website
from monitoring.ssl_checker import SSLResult


@pytest.fixture
def mock_dns_resolution(monkeypatch: pytest.MonkeyPatch):
    """Ensure URL validator resolves public IP."""
    monkeypatch.setattr(
        "monitoring.security.resolve_and_validate_hostname",
        lambda host: ["93.184.216.34"],
    )


@pytest.mark.asyncio
class TestProbeEngine:
    """Validate orchestration of DNS, TLS, and HTTP monitoring phases."""

    async def test_successful_https_probe(self, mock_dns_resolution) -> None:
        """Verify successful probe captures all timing metrics across all phases."""
        mock_dns = DNSResult(
            hostname="example.com",
            is_success=True,
            lookup_duration_ms=12.5,
            ipv4_addresses=["93.184.216.34"],
            primary_ip="93.184.216.34",
        )
        mock_ssl = SSLResult(
            is_valid=True,
            expiry_date="2030-01-01T00:00:00+00:00",
            days_remaining=500,
            handshake_duration_ms=45.2,
        )
        mock_http = HTTPResult(
            is_success=True,
            status_code=200,
            ttfb_ms=25.0,
            download_ms=10.0,
            total_time_ms=35.0,
            response_size_bytes=2048,
            redirect_count=0,
            final_url="https://example.com/",
        )

        with patch(
            "monitoring.probe_engine.check_dns", new_callable=AsyncMock
        ) as m_dns:
            m_dns.return_value = mock_dns
            with patch(
                "monitoring.probe_engine.check_ssl", new_callable=AsyncMock
            ) as m_ssl:
                m_ssl.return_value = mock_ssl
                with patch(
                    "monitoring.probe_engine.check_http", new_callable=AsyncMock
                ) as m_http:
                    m_http.return_value = mock_http

                    result: ProbeResult = await probe_website("https://example.com")

        assert result.is_success is True
        assert result.status == "UP"
        assert result.http_status == 200
        assert result.dns_lookup_ms == 12.5
        assert result.tls_handshake_ms == 45.2
        assert result.ttfb_ms == 25.0
        assert result.download_ms == 10.0
        assert result.total_time_ms is not None and result.total_time_ms >= 0.0
        assert result.ssl_valid is True
        assert result.ssl_expiry_days == 500
        assert result.dns_success is True
        assert result.error_type is None

    async def test_http_only_probe_skips_ssl(self, mock_dns_resolution) -> None:
        """Verify HTTP-only website skips SSL inspection and leaves SSL metrics as None."""
        mock_dns = DNSResult(
            hostname="http-only.com",
            is_success=True,
            lookup_duration_ms=8.0,
            ipv4_addresses=["93.184.216.34"],
            primary_ip="93.184.216.34",
        )
        mock_http = HTTPResult(
            is_success=True,
            status_code=200,
            ttfb_ms=20.0,
            download_ms=5.0,
            total_time_ms=25.0,
            response_size_bytes=512,
            redirect_count=0,
            final_url="http://http-only.com/",
        )

        with patch(
            "monitoring.probe_engine.check_dns", new_callable=AsyncMock
        ) as m_dns:
            m_dns.return_value = mock_dns
            with patch(
                "monitoring.probe_engine.check_ssl", new_callable=AsyncMock
            ) as m_ssl:
                with patch(
                    "monitoring.probe_engine.check_http", new_callable=AsyncMock
                ) as m_http:
                    m_http.return_value = mock_http

                    result = await probe_website("http://http-only.com")

                    assert m_ssl.call_count == 0  # SSL check skipped!

        assert result.is_success is True
        assert result.status == "UP"
        assert result.tls_handshake_ms is None
        assert result.ssl_valid is None
        assert result.ssl_expiry_days is None
        assert result.ssl_expiry_date is None

    async def test_dns_failure_halts_subsequent_phases(
        self, mock_dns_resolution
    ) -> None:
        """Verify DNS failure immediately marks probe as DOWN without attempting HTTP/TLS."""
        mock_dns = DNSResult(
            hostname="unresolvable.org",
            is_success=False,
            lookup_duration_ms=15.0,
            error_type="DNSResolutionError",
            error_message="NXDOMAIN",
        )

        with patch(
            "monitoring.probe_engine.check_dns", new_callable=AsyncMock
        ) as m_dns:
            m_dns.return_value = mock_dns
            with patch(
                "monitoring.probe_engine.check_ssl", new_callable=AsyncMock
            ) as m_ssl:
                with patch(
                    "monitoring.probe_engine.check_http", new_callable=AsyncMock
                ) as m_http:

                    result = await probe_website("https://unresolvable.org")

                    assert m_ssl.call_count == 0
                    assert m_http.call_count == 0

        assert result.is_success is False
        assert result.status == "DOWN"
        assert result.dns_success is False
        assert result.error_type == "DNSResolutionError"
        assert result.http_status is None
        assert result.tls_handshake_ms is None

    async def test_ssrf_blocked_url_rejected_at_phase_1(self) -> None:
        """Verify private IP URL is rejected at Phase 1 before any network activity."""
        result = await probe_website("http://127.0.0.1:8080/secret")

        assert result.is_success is False
        assert result.status == "DOWN"
        assert result.error_type == "SSRFValidationError"
        assert "SSRF policy" in result.error_message
