"""Unit tests for SSL certificate inspection and expiry calculation."""

import asyncio
import ssl
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from monitoring.ssl_checker import SSLResult, check_ssl, parse_cert_expiry


class TestSSLChecker:
    """Validate TLS handshake inspection and certificate validity calculations."""

    def test_parse_cert_expiry_valid_future_date(self) -> None:
        """Verify parsing future notAfter date yields positive days remaining."""
        iso_str, days = parse_cert_expiry("Dec 31 23:59:59 2030 GMT")
        assert "2030-12-31" in iso_str
        assert days > 1000

    def test_parse_cert_expiry_expired_past_date(self) -> None:
        """Verify parsing past notAfter date yields negative days remaining."""
        iso_str, days = parse_cert_expiry("Jan 01 00:00:00 2020 GMT")
        assert "2020-01-01" in iso_str
        assert days < 0

    @pytest.mark.asyncio
    async def test_successful_ssl_inspection(self) -> None:
        """Verify valid certificate returns is_valid=True and positive days remaining."""
        mock_reader = MagicMock()
        mock_writer = MagicMock()
        mock_transport = MagicMock()
        mock_writer.transport.get_protocol.return_value = MagicMock()

        mock_ssl_obj = MagicMock()
        mock_ssl_obj.getpeercert.return_value = {"notAfter": "Dec 31 23:59:59 2030 GMT"}
        mock_transport.get_extra_info.return_value = mock_ssl_obj

        with patch("asyncio.open_connection", new_callable=AsyncMock) as mock_open:
            mock_open.return_value = (mock_reader, mock_writer)
            with patch("asyncio.base_events.BaseEventLoop.start_tls", new_callable=AsyncMock) as mock_tls:
                mock_tls.return_value = mock_transport

                result: SSLResult = await check_ssl("example.com", ip_address="93.184.216.34")

        assert result.is_valid is True
        assert result.days_remaining is not None and result.days_remaining > 0
        assert result.expiry_date is not None and "2030" in result.expiry_date
        assert result.handshake_duration_ms is not None
        assert result.error_type is None

    @pytest.mark.asyncio
    async def test_expired_ssl_certificate(self) -> None:
        """Verify expired certificate flags is_valid=False and error_type."""
        mock_reader = MagicMock()
        mock_writer = MagicMock()
        mock_transport = MagicMock()
        mock_writer.transport.get_protocol.return_value = MagicMock()

        mock_ssl_obj = MagicMock()
        mock_ssl_obj.getpeercert.return_value = {"notAfter": "Jan 01 00:00:00 2020 GMT"}
        mock_transport.get_extra_info.return_value = mock_ssl_obj

        with patch("asyncio.open_connection", new_callable=AsyncMock) as mock_open:
            mock_open.return_value = (mock_reader, mock_writer)
            with patch("asyncio.base_events.BaseEventLoop.start_tls", new_callable=AsyncMock) as mock_tls:
                mock_tls.return_value = mock_transport

                result: SSLResult = await check_ssl("expired.example.com", ip_address="93.184.216.34")

        assert result.is_valid is False
        assert result.days_remaining is not None and result.days_remaining < 0
        assert result.error_type == "SSLCertificateExpiredError"
        assert "expired" in result.error_message

    @pytest.mark.asyncio
    async def test_ssl_verification_failure(self) -> None:
        """Verify untrusted certificate error is captured."""
        mock_reader = MagicMock()
        mock_writer = MagicMock()
        mock_writer.transport.get_protocol.return_value = MagicMock()

        with patch("asyncio.open_connection", new_callable=AsyncMock) as mock_open:
            mock_open.return_value = (mock_reader, mock_writer)
            with patch(
                "asyncio.base_events.BaseEventLoop.start_tls",
                side_effect=ssl.SSLCertVerificationError("Self-signed cert"),
            ):
                result = await check_ssl("self-signed.badssl.com", ip_address="93.184.216.34")

        assert result.is_valid is False
        assert result.error_type == "SSLCertVerificationError"
        assert "Self-signed" in result.error_message

    @pytest.mark.asyncio
    async def test_connection_timeout_handling(self) -> None:
        """Verify connection timeout to TLS port is handled cleanly."""
        with patch("asyncio.open_connection", side_effect=asyncio.TimeoutError()):
            result = await check_ssl("unresponsive.com", ip_address="93.184.216.34", timeout=0.1)

        assert result.is_valid is False
        assert result.error_type == "ConnectionTimeoutError"
        assert "timed out" in result.error_message

