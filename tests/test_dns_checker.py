"""Unit tests for the DNS resolution and latency checker."""

from unittest.mock import MagicMock, patch
import pytest

import dns.exception
import dns.resolver

from monitoring.dns_checker import DNSResult, check_dns


@pytest.mark.asyncio
class TestDNSChecker:
    """Validate dnspython async resolution, timing metrics, and SSRF verification."""

    async def test_successful_dns_resolution(self) -> None:
        """Verify successful A/AAAA resolution records IPs and monotonic latency."""
        mock_a = MagicMock()
        mock_a.to_text.return_value = "93.184.216.34"
        mock_aaaa = MagicMock()
        mock_aaaa.to_text.return_value = "2606:2800:220:1:248:1893:25c8:1946"

        def fake_resolve(hostname, qtype):
            if qtype == "A":
                return [mock_a]
            elif qtype == "AAAA":
                return [mock_aaaa]
            return []

        with patch("dns.resolver.Resolver.resolve", side_effect=fake_resolve):
            result: DNSResult = await check_dns("example.com")

        assert result.is_success is True
        assert result.hostname == "example.com"
        assert result.lookup_duration_ms is not None
        assert result.lookup_duration_ms >= 0.0
        assert "93.184.216.34" in result.ipv4_addresses
        assert "2606:2800:220:1:248:1893:25c8:1946" in result.ipv6_addresses
        assert result.primary_ip == "93.184.216.34"
        assert result.error_type is None

    async def test_dns_nxdomain_failure(self) -> None:
        """Verify NXDOMAIN failure returns structured DNS failure result."""
        with patch(
            "dns.resolver.Resolver.resolve",
            side_effect=dns.resolver.NXDOMAIN("Nonexistent domain"),
        ):
            result = await check_dns("this-domain-does-not-exist.fake")

        assert result.is_success is False
        assert result.error_type == "DNSResolutionError"
        assert "NXDOMAIN" in result.error_message or "failed" in result.error_message

    async def test_dns_timeout(self) -> None:
        """Verify DNS timeout returns structured timeout error."""
        with patch(
            "dns.resolver.Resolver.resolve",
            side_effect=dns.exception.Timeout("Query timed out"),
        ):
            result = await check_dns("slow-nameserver.com", timeout=1.0)

        assert result.is_success is False
        assert result.error_type == "DNSTimeoutError"
        assert "timed out" in result.error_message

    async def test_dns_resolving_to_private_ip_is_blocked_by_ssrf(self) -> None:
        """Verify DNS results resolving to internal IPs are rejected by SSRF guard."""
        mock_private = MagicMock()
        mock_private.to_text.return_value = "10.0.0.1"

        with patch("dns.resolver.Resolver.resolve", return_value=[mock_private]):
            result = await check_dns("internal-service.local")

        assert result.is_success is False
        assert result.error_type == "SSRFValidationError"
        assert "SSRF violation" in result.error_message

    async def test_raw_ip_literals_handling(self) -> None:
        """Verify public IP literal passes immediately while loopback/private fails."""
        res_pub = await check_dns("93.184.216.34")
        assert res_pub.is_success is True
        assert res_pub.primary_ip == "93.184.216.34"

        res_priv = await check_dns("127.0.0.1")
        assert res_priv.is_success is False
        assert res_priv.error_type == "SSRFValidationError"

        res_local = await check_dns("localhost")
        assert res_local.is_success is False
        assert res_local.error_type == "SSRFValidationError"

