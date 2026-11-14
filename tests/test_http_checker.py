"""Unit tests for instrumented HTTP telemetry and probe checker."""

from unittest.mock import MagicMock, patch
import httpx
import pytest

from monitoring.http_checker import HTTPResult, check_http


@pytest.fixture
def mock_dns_resolution(monkeypatch: pytest.MonkeyPatch):
    """Ensure DNS resolution returns public IP for URL validation."""
    monkeypatch.setattr(
        "socket.getaddrinfo",
        lambda host, port, family=0, type=0: [(2, 1, 6, "", ("93.184.216.34", 80))],
    )


@pytest.mark.asyncio
class TestHTTPChecker:
    """Validate HTTP metrics, response timing, redirect vetting, and size guards."""

    async def test_http_200_success(self, mock_dns_resolution) -> None:
        """Verify 200 OK records positive TTFB, content size, and success flag."""
        transport = httpx.MockTransport(
            lambda req: httpx.Response(
                200,
                text="<html><body>Hello World</body></html>",
                headers={"Content-Type": "text/html"},
            )
        )
        client = httpx.AsyncClient(transport=transport)

        result: HTTPResult = await check_http("https://example.com/", client=client)

        assert result.is_success is True
        assert result.status_code == 200
        assert result.ttfb_ms is not None and result.ttfb_ms >= 0.0
        assert result.download_ms is not None and result.download_ms >= 0.0
        assert result.total_time_ms is not None and result.total_time_ms >= 0.0
        assert result.response_size_bytes > 0
        assert result.redirect_count == 0
        assert result.error_type is None

    async def test_http_404_client_error(self, mock_dns_resolution) -> None:
        """Verify 404 response records status code and is_success=False."""
        transport = httpx.MockTransport(
            lambda req: httpx.Response(404, text="Not Found")
        )
        client = httpx.AsyncClient(transport=transport)

        result = await check_http("https://example.com/not-found", client=client)

        assert result.is_success is False
        assert result.status_code == 404
        assert result.error_type == "HttpClientError"
        assert "404" in result.error_message

    async def test_http_500_server_error(self, mock_dns_resolution) -> None:
        """Verify HTTP 500 is recorded as a failure per Task 5."""
        transport = httpx.MockTransport(
            lambda req: httpx.Response(500, text="Internal Server Error")
        )
        client = httpx.AsyncClient(transport=transport)

        result = await check_http("https://example.com/crash", client=client)

        assert result.is_success is False
        assert result.status_code == 500
        assert result.error_type == "HttpServerError"
        assert "500" in result.error_message

    async def test_connection_timeout(self, mock_dns_resolution) -> None:
        """Verify connection timeout is caught and categorized cleanly."""

        def raise_timeout(req):
            raise httpx.ConnectTimeout("Connection timed out")

        transport = httpx.MockTransport(raise_timeout)
        client = httpx.AsyncClient(transport=transport)

        result = await check_http("https://example.com/slow", client=client)

        assert result.is_success is False
        assert result.status_code is None
        assert result.error_type == "ConnectTimeoutError"
        assert "timed out" in result.error_message

    async def test_safe_redirect_handling(self, mock_dns_resolution) -> None:
        """Verify redirects are tracked and followed when destination is public."""
        call_count = 0

        def handle_redirect(req):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return httpx.Response(
                    301, headers={"Location": "https://example.com/final"}
                )
            return httpx.Response(200, text="Final Destination")

        transport = httpx.MockTransport(handle_redirect)
        client = httpx.AsyncClient(transport=transport)

        result = await check_http("https://example.com/start", client=client)

        assert result.is_success is True
        assert result.status_code == 200
        assert result.redirect_count == 1
        assert "final" in result.final_url

    async def test_redirect_to_private_ip_blocked_by_ssrf(
        self, mock_dns_resolution
    ) -> None:
        """Verify redirect pointing to internal/private IP is blocked immediately."""
        transport = httpx.MockTransport(
            lambda req: httpx.Response(
                302, headers={"Location": "http://127.0.0.1:8080/admin"}
            )
        )
        client = httpx.AsyncClient(transport=transport)

        result = await check_http(
            "https://example.com/redirect-to-internal", client=client
        )

        assert result.is_success is False
        assert result.error_type == "SSRFValidationError"
        assert "SSRF policy" in result.error_message

    async def test_too_many_redirects_exceeded(self, mock_dns_resolution) -> None:
        """Verify exceeding max redirect limit is halted."""
        transport = httpx.MockTransport(
            lambda req: httpx.Response(
                302, headers={"Location": "https://example.com/loop"}
            )
        )
        client = httpx.AsyncClient(transport=transport)

        result = await check_http(
            "https://example.com/loop", max_redirects=2, client=client
        )

        assert result.is_success is False
        assert result.error_type == "TooManyRedirectsError"
        assert result.redirect_count == 2

    async def test_response_size_limit_exceeded(self, mock_dns_resolution) -> None:
        """Verify oversized response download is halted to prevent memory exhaustion."""
        large_payload = b"X" * 1024 * 100  # 100 KB

        transport = httpx.MockTransport(
            lambda req: httpx.Response(200, content=large_payload)
        )
        client = httpx.AsyncClient(transport=transport)

        # Enforce strict 10 KB limit
        result = await check_http(
            "https://example.com/large",
            max_response_size=10 * 1024,
            client=client,
        )

        assert result.is_success is False
        assert result.error_type == "ResponseSizeLimitExceededError"
        assert "exceeded limit" in result.error_message
