"""Unit tests for the HTTP/DNS/SSL monitoring probe engine."""

import ssl
from unittest.mock import MagicMock, patch
import httpx
import pytest

from monitoring.engine import (
    WebsiteCheckResult,
    check_website_async,
    inspect_ssl_certificate,
)


@pytest.fixture
def mock_dns_resolution(monkeypatch: pytest.MonkeyPatch):
    """Ensure DNS resolution resolves to public IP for unit tests."""
    monkeypatch.setattr(
        "monitoring.security.resolve_and_validate_hostname",
        lambda host: ["93.184.216.34"],
    )


@pytest.mark.asyncio
class TestMonitoringEngine:
    """Validate HTTP probe execution, timing measurements, and error classification."""

    async def test_successful_http_probe(
        self, mock_dns_resolution, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify 200 OK responses mark website UP with recorded latency and TTFB."""
        # Bypass SSL socket inspection for test speed
        monkeypatch.setattr(
            "monitoring.engine.inspect_ssl_certificate",
            lambda host, port, timeout: (True, "2027-01-01T00:00:00+00:00", 365, None),
        )

        transport = httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                text="<html><head><title>Test</title></head><body>OK</body></html>",
                headers={"Content-Type": "text/html"},
            )
        )

        with patch("httpx.AsyncClient", return_value=httpx.AsyncClient(transport=transport)):
            result: WebsiteCheckResult = await check_website_async("https://example.com")

        assert result.is_up is True
        assert result.status == "UP"
        assert result.http_status_code == 200
        assert result.response_time_ms >= 0.0
        assert result.ttfb_ms >= 0.0
        assert result.response_size_bytes > 0
        assert result.error_message is None
        assert result.ssl_valid is True

    async def test_http_404_client_error(
        self, mock_dns_resolution, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify 404 responses mark server responsive/UP with 404 code recorded."""
        monkeypatch.setattr(
            "monitoring.engine.inspect_ssl_certificate",
            lambda host, port, timeout: (True, "2027-01-01T00:00:00+00:00", 365, None),
        )

        transport = httpx.MockTransport(
            lambda request: httpx.Response(404, text="Not Found")
        )

        with patch("httpx.AsyncClient", return_value=httpx.AsyncClient(transport=transport)):
            result = await check_website_async("https://example.com/missing")

        assert result.is_up is True
        assert result.status == "UP"
        assert result.http_status_code == 404

    async def test_http_500_server_downtime_detection(
        self, mock_dns_resolution, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify 500 Internal Server Error is detected as DOWN."""
        monkeypatch.setattr(
            "monitoring.engine.inspect_ssl_certificate",
            lambda host, port, timeout: (True, "2027-01-01T00:00:00+00:00", 365, None),
        )

        transport = httpx.MockTransport(
            lambda request: httpx.Response(500, text="Internal Server Error")
        )

        with patch("httpx.AsyncClient", return_value=httpx.AsyncClient(transport=transport)):
            result = await check_website_async("https://example.com/crash")

        assert result.is_up is False
        assert result.status == "DOWN"
        assert result.http_status_code == 500
        assert "HTTP 500" in result.error_message

    async def test_connection_timeout(
        self, mock_dns_resolution, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify connection timeout is caught and categorized as DOWN."""
        monkeypatch.setattr(
            "monitoring.engine.inspect_ssl_certificate",
            lambda host, port, timeout: (True, None, None, None),
        )

        def raise_timeout(request):
            raise httpx.ConnectTimeout("Connection timed out")

        transport = httpx.MockTransport(raise_timeout)

        with patch("httpx.AsyncClient", return_value=httpx.AsyncClient(transport=transport)):
            result = await check_website_async("https://example.com")

        assert result.is_up is False
        assert result.status == "DOWN"
        assert result.http_status_code is None
        assert "Connection timed out" in result.error_message

    async def test_dns_resolution_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify DNS failures are recorded with DOWN status."""
        monkeypatch.setattr(
            "monitoring.security.resolve_and_validate_hostname",
            MagicMock(side_effect=Exception("getaddrinfo failed: host not found")),
        )

        result = await check_website_async("https://nonexistent-fake-domain.xyz")

        assert result.is_up is False
        assert result.status == "DOWN"
        assert "DNS Resolution Error" in result.error_message


class TestSSLInspection:
    """Validate SSL certificate inspection and expiry parsing."""

    def test_valid_ssl_certificate_mock(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify valid certificate parsing produces positive days remaining."""
        fake_cert = {"notAfter": "Jan 01 00:00:00 2030 GMT"}

        mock_ssock = MagicMock()
        mock_ssock.getpeercert.return_value = fake_cert

        mock_context = MagicMock()
        mock_context.wrap_socket.return_value.__enter__.return_value = mock_ssock

        monkeypatch.setattr("ssl.create_default_context", lambda: mock_context)
        monkeypatch.setattr(
            "socket.create_connection",
            lambda addr, timeout: MagicMock(__enter__=lambda s: MagicMock(), __exit__=lambda *a: None),
        )

        is_valid, expiry_iso, days_left, err = inspect_ssl_certificate("example.com")
        assert is_valid is True
        assert days_left > 0
        assert "2030" in expiry_iso
        assert err is None

    def test_expired_ssl_certificate_mock(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify expired certificate flags is_valid=False with negative days."""
        fake_cert = {"notAfter": "Jan 01 00:00:00 2020 GMT"}

        mock_ssock = MagicMock()
        mock_ssock.getpeercert.return_value = fake_cert

        mock_context = MagicMock()
        mock_context.wrap_socket.return_value.__enter__.return_value = mock_ssock

        monkeypatch.setattr("ssl.create_default_context", lambda: mock_context)
        monkeypatch.setattr(
            "socket.create_connection",
            lambda addr, timeout: MagicMock(__enter__=lambda s: MagicMock(), __exit__=lambda *a: None),
        )

        is_valid, expiry_iso, days_left, err = inspect_ssl_certificate("expired.example.com")
        assert is_valid is False
        assert days_left < 0

