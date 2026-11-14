"""Security and Anti-SSRF Validation Engine for Website Monitoring.

Enforces strict URL sanitization, scheme restrictions, port boundaries,
private/link-local/loopback IP address blocking, and DNS resolution validation
to protect against Server-Side Request Forgery (SSRF) and DNS rebinding attacks.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

import config


class SecurityValidationError(ValueError):
    """Raised when a URL violates network or SSRF security policies."""

    pass


# Specific cloud metadata IP addresses to strictly prohibit
BLOCKED_METADATA_IPS: set[str] = {
    "169.254.169.254",  # AWS EC2 / Azure / GCP IMDSv1/v2
    "169.254.170.2",  # AWS ECS task metadata
    "fd00:ec2::254",  # AWS IPv6 IMDS
}


def is_ip_private_or_reserved(
    ip_obj: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> bool:
    """Determine whether an IP address is private, loopback, or reserved.

    Args:
        ip_obj: Parsed IPv4 or IPv6 object.

    Returns:
        True if IP is restricted or unsafe for outbound monitoring; False if public.
    """
    # Check standard Python ipaddress boundary flags
    if (
        ip_obj.is_private
        or ip_obj.is_loopback
        or ip_obj.is_link_local
        or ip_obj.is_multicast
        or ip_obj.is_reserved
        or ip_obj.is_unspecified
    ):
        return True

    ip_str = str(ip_obj)

    # Explicit cloud metadata host check
    if ip_str in BLOCKED_METADATA_IPS:
        return True

    # Check for IPv4-mapped IPv6 address (e.g., ::ffff:127.0.0.1)
    if isinstance(ip_obj, ipaddress.IPv6Address) and ip_obj.ipv4_mapped:
        return is_ip_private_or_reserved(ip_obj.ipv4_mapped)

    return False


def resolve_and_validate_hostname(hostname: str) -> list[str]:
    """Resolve domain via DNS and ensure every resolved IP address is public.

    Args:
        hostname: Domain name or IP string.

    Returns:
        List of verified public IP address strings.

    Raises:
        SecurityValidationError: If hostname resolves to private/reserved IP.
    """
    cleaned_host = hostname.strip().lower()

    # Block explicit localhost strings
    if cleaned_host == "localhost" or cleaned_host.endswith(".localhost"):
        raise SecurityValidationError(
            f"Access to localhost ('{hostname}') is blocked by SSRF policy."
        )

    # If already an IP address, validate directly
    try:
        ip_obj = ipaddress.ip_address(cleaned_host)
    except ValueError:
        ip_obj = None

    if ip_obj is not None:
        if is_ip_private_or_reserved(ip_obj):
            raise SecurityValidationError(
                f"IP address '{cleaned_host}' is private, loopback, or reserved."
            )
        return [str(ip_obj)]

    # Resolve all IPv4 and IPv6 addresses for the hostname
    try:
        addr_info = socket.getaddrinfo(
            cleaned_host,
            None,
            family=socket.AF_UNSPEC,
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror as exc:
        raise SecurityValidationError(
            f"DNS resolution failed for hostname '{hostname}': {exc}"
        ) from exc

    if not addr_info:
        raise SecurityValidationError(
            f"No DNS records found for hostname '{hostname}'."
        )

    resolved_ips: list[str] = []
    for entry in addr_info:
        sockaddr = entry[4]
        ip_str = sockaddr[0]
        try:
            ip_obj = ipaddress.ip_address(ip_str)
        except ValueError as exc:
            raise SecurityValidationError(
                f"Resolved invalid IP address '{ip_str}' for host '{hostname}'."
            ) from exc

        if is_ip_private_or_reserved(ip_obj):
            raise SecurityValidationError(
                f"Hostname '{hostname}' resolves to private/reserved IP '{ip_str}' "
                "(blocked by anti-SSRF policy)."
            )

        if ip_str not in resolved_ips:
            resolved_ips.append(ip_str)

    return resolved_ips


def validate_url_security(url: str) -> tuple[str, str, int]:
    """Validate a website URL for security compliance and return normalized components.

    Validates:
    - Non-empty URL string.
    - Allowed scheme (HTTP or HTTPS).
    - Hostname presence and absence of credentials in URL (userinfo).
    - Allowed port (80, 443, 8080, 8443).
    - Anti-SSRF: Every resolved DNS IP address is verified as public.

    Args:
        url: User-provided URL.

    Returns:
        Tuple of (normalized_url, primary_resolved_ip, port).

    Raises:
        SecurityValidationError: If URL fails any validation or security rule.
    """
    if not url or not isinstance(url, str):
        raise SecurityValidationError("URL must be a non-empty string.")

    cleaned_url = url.strip()

    # --- Scheme check BEFORE prepending a default scheme ---
    # Extract the scheme from the raw user input if '://' is present.
    if "://" in cleaned_url:
        raw_scheme = cleaned_url.split("://", 1)[0].lower()
        if raw_scheme not in config.ALLOWED_SCHEMES:
            raise SecurityValidationError(
                f"Scheme '{raw_scheme}' is not allowed. "
                "Only HTTP and HTTPS are permitted."
            )
    elif cleaned_url.startswith("javascript:"):
        raise SecurityValidationError(
            "Scheme 'javascript' is not allowed. "
            "Only HTTP and HTTPS are permitted."
        )

    # Add default HTTPS scheme if missing (safe now that illegal schemes caught)
    if not cleaned_url.startswith(("http://", "https://")):
        cleaned_url = f"https://{cleaned_url}"

    try:
        parsed = urlparse(cleaned_url)
    except Exception as exc:
        raise SecurityValidationError(f"Malformed URL '{url}': {exc}") from exc

    scheme = (parsed.scheme or "").lower()
    if scheme not in config.ALLOWED_SCHEMES:
        raise SecurityValidationError(
            f"Scheme '{scheme}' is not allowed. Only HTTP and HTTPS are permitted."
        )

    if not parsed.netloc:
        raise SecurityValidationError(f"Invalid URL '{url}': missing host authority.")

    if parsed.username or parsed.password:
        raise SecurityValidationError(
            "URLs containing embedded userinfo credentials are not permitted."
        )

    hostname = parsed.hostname
    if not hostname:
        raise SecurityValidationError(f"Invalid URL '{url}': cannot extract hostname.")

    # Determine port
    port = parsed.port
    if port is None:
        port = 443 if scheme == "https" else 80

    if port not in config.ALLOWED_PORTS:
        raise SecurityValidationError(
            f"Port '{port}' is not in the allowed monitoring ports list: "
            f"{config.ALLOWED_PORTS}."
        )

    # Validate hostname via DNS resolution and check every resolved IP against SSRF
    resolved_ips = resolve_and_validate_hostname(hostname)
    primary_ip = resolved_ips[0]

    # Reconstruct clean normalized URL
    path = parsed.path if parsed.path else "/"
    normalized = f"{scheme}://{hostname}"
    if parsed.port and parsed.port not in (80, 443):
        normalized += f":{parsed.port}"
    normalized += path
    if parsed.query:
        normalized += f"?{parsed.query}"

    return normalized, primary_ip, port
