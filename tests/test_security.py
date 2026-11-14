"""Unit tests for URL validation and Anti-SSRF protection."""

import pytest

from monitoring.security import (
    SecurityValidationError,
    is_ip_private_or_reserved,
    validate_url_security,
)
import ipaddress


class TestSecurityValidation:
    """Validate strict security and SSRF boundary enforcement."""

    def test_valid_public_urls(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify valid public web URLs pass with normalized outputs."""
        # Mock DNS resolution to return a known public IP
        monkeypatch.setattr(
            "monitoring.security.resolve_and_validate_hostname",
            lambda host: ["93.184.216.34"],
        )

        norm_url, ip, port = validate_url_security("https://example.com")
        assert norm_url == "https://example.com/"
        assert ip == "93.184.216.34"
        assert port == 443

        norm_http, _, port_http = validate_url_security("http://example.com/api/status?v=1")
        assert norm_http == "http://example.com/api/status?v=1"
        assert port_http == 80

    def test_missing_scheme_defaults_to_https(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify scheme-less inputs default safely to HTTPS."""
        monkeypatch.setattr(
            "monitoring.security.resolve_and_validate_hostname",
            lambda host: ["93.184.216.34"],
        )
        norm_url, _, port = validate_url_security("example.com/health")
        assert norm_url == "https://example.com/health"
        assert port == 443

    @pytest.mark.parametrize(
        "invalid_scheme_url",
        [
            "ftp://example.com/file.txt",
            "file:///etc/passwd",
            "gopher://example.com",
            "ssh://example.com",
            "javascript:alert(1)",
        ],
    )
    def test_disallowed_schemes_blocked(self, invalid_scheme_url: str) -> None:
        """Verify non-HTTP/HTTPS protocols are strictly rejected."""
        with pytest.raises(SecurityValidationError, match="Only HTTP and HTTPS"):
            validate_url_security(invalid_scheme_url)

    @pytest.mark.parametrize(
        "localhost_url",
        [
            "http://localhost",
            "http://localhost:8080",
            "http://127.0.0.1",
            "http://127.0.0.1:80",
            "http://127.0.1.1",
            "http://[::1]",
            "http://subdomain.localhost",
        ],
    )
    def test_localhost_and_loopback_blocked(self, localhost_url: str) -> None:
        """Verify all variants of localhost and loopbacks are rejected."""
        with pytest.raises(SecurityValidationError):
            validate_url_security(localhost_url)

    @pytest.mark.parametrize(
        "private_ip_url",
        [
            "http://10.0.0.1/admin",
            "http://172.16.0.5:8080",
            "http://172.31.255.255",
            "http://192.168.1.1/router",
            "http://0.0.0.0",
        ],
    )
    def test_rfc1918_private_ips_blocked(self, private_ip_url: str) -> None:
        """Verify private internal RFC-1918 IP addresses are rejected."""
        with pytest.raises(SecurityValidationError):
            validate_url_security(private_ip_url)

    @pytest.mark.parametrize(
        "metadata_url",
        [
            "http://169.254.169.254/latest/meta-data/",
            "http://169.254.170.2/v2/metadata",
        ],
    )
    def test_cloud_metadata_services_blocked(self, metadata_url: str) -> None:
        """Verify AWS/cloud instance metadata endpoint requests are blocked."""
        with pytest.raises(SecurityValidationError):
            validate_url_security(metadata_url)

    def test_dns_resolving_to_private_ip_blocked(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify DNS rebinding / hostnames resolving to private IPs are caught."""
        monkeypatch.setattr(
            "socket.getaddrinfo",
            lambda host, port, family=0, type=0: [
                (2, 1, 6, "", ("10.0.0.5", 80))
            ],
        )
        with pytest.raises(SecurityValidationError, match="resolves to private/reserved IP"):
            validate_url_security("http://evil-internal-rebinding.com")

    @pytest.mark.parametrize("disallowed_port", [21, 22, 25, 3306, 5432, 6379, 27017])
    def test_disallowed_ports_blocked(
        self, disallowed_port: int, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify non-standard web ports are rejected."""
        monkeypatch.setattr(
            "monitoring.security.resolve_and_validate_hostname",
            lambda host: ["93.184.216.34"],
        )
        with pytest.raises(SecurityValidationError, match="not in the allowed monitoring ports"):
            validate_url_security(f"https://example.com:{disallowed_port}/")

    def test_embedded_credentials_blocked(self) -> None:
        """Verify user:pass in URL is rejected."""
        with pytest.raises(SecurityValidationError, match="userinfo credentials"):
            validate_url_security("https://user:password@example.com/")

    def test_empty_or_malformed_url(self) -> None:
        """Verify empty and invalid string inputs raise errors."""
        with pytest.raises(SecurityValidationError):
            validate_url_security("")
        with pytest.raises(SecurityValidationError):
            validate_url_security("   ")

