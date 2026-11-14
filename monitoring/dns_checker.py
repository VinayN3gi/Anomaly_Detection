"""DNS Resolution and Latency Checker using dnspython.

Performs asynchronous DNS lookups for IPv4 (A) and IPv6 (AAAA) records,
records precise resolution latency using monotonic clocks, and enforces
anti-SSRF security verification on all resolved addresses.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import ipaddress
import logging

import dns.asyncresolver
import dns.exception
import dns.resolver

from monitoring.timing import elapsed_ms, monotonic_now
from monitoring.url_validator import SecurityValidationError, is_ip_private_or_reserved

logger = logging.getLogger("aiops.dns")


@dataclass
class DNSResult:
    """Structured result of a DNS resolution operation."""

    hostname: str
    is_success: bool
    lookup_duration_ms: float | None
    ipv4_addresses: list[str] = field(default_factory=list)
    ipv6_addresses: list[str] = field(default_factory=list)
    primary_ip: str | None = None
    error_type: str | None = None
    error_message: str | None = None

    @property
    def all_addresses(self) -> list[str]:
        """Return combined list of IPv4 and IPv6 addresses."""
        return self.ipv4_addresses + self.ipv6_addresses


def _sync_resolve(
    hostname: str,
    timeout: float,
    nameservers: list[str] | None = None,
) -> tuple[list[str], list[str]]:
    """Synchronous worker for DNS resolution (executed via asyncio.to_thread)."""
    resolver = dns.resolver.Resolver()
    resolver.lifetime = timeout
    resolver.timeout = timeout
    if nameservers:
        resolver.nameservers = nameservers

    ipv4_addrs: list[str] = []
    ipv6_addrs: list[str] = []

    # Query A (IPv4)
    try:
        answers_a = resolver.resolve(hostname, "A")
        for rdata in answers_a:
            ipv4_addrs.append(rdata.to_text())
    except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN):
        pass
    except Exception as exc:
        logger.debug("IPv4 lookup failed for %s: %s", hostname, exc)

    # Query AAAA (IPv6)
    try:
        answers_aaaa = resolver.resolve(hostname, "AAAA")
        for rdata in answers_aaaa:
            ipv6_addrs.append(rdata.to_text())
    except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN):
        pass
    except Exception as exc:
        logger.debug("IPv6 lookup failed for %s: %s", hostname, exc)

    if not ipv4_addrs and not ipv6_addrs:
        # If neither returned answers, perform a final query to trigger proper exception
        resolver.resolve(hostname, "A")

    return ipv4_addrs, ipv6_addrs


async def check_dns(
    hostname: str,
    timeout: float = 5.0,
    nameservers: list[str] | None = None,
) -> DNSResult:
    """Resolve website hostname via DNS and validate against SSRF boundaries.

    Args:
        hostname: Domain name or raw IP literal to resolve.
        timeout: Maximum duration in seconds for resolution.
        nameservers: Optional list of custom DNS nameserver IP addresses.

    Returns:
        Structured DNSResult with status, timing, resolved IPs, or error details.
    """
    cleaned_host = hostname.strip().lower()

    # Direct IP literal check
    try:
        ip_obj = ipaddress.ip_address(cleaned_host)
        if is_ip_private_or_reserved(ip_obj):
            return DNSResult(
                hostname=cleaned_host,
                is_success=False,
                lookup_duration_ms=0.0,
                error_type="SSRFValidationError",
                error_message=f"IP literal '{cleaned_host}' is private/reserved.",
            )
        is_v4 = isinstance(ip_obj, ipaddress.IPv4Address)
        return DNSResult(
            hostname=cleaned_host,
            is_success=True,
            lookup_duration_ms=0.0,
            ipv4_addresses=[str(ip_obj)] if is_v4 else [],
            ipv6_addresses=[str(ip_obj)] if not is_v4 else [],
            primary_ip=str(ip_obj),
        )
    except ValueError:
        pass

    # Block localhost explicitly
    if cleaned_host == "localhost" or cleaned_host.endswith(".localhost"):
        return DNSResult(
            hostname=cleaned_host,
            is_success=False,
            lookup_duration_ms=0.0,
            error_type="SSRFValidationError",
            error_message=f"Access to localhost ('{hostname}') is blocked by SSRF policy.",
        )

    t_start = monotonic_now()

    try:
        ipv4_addrs, ipv6_addrs = await asyncio.to_thread(
            _sync_resolve, cleaned_host, timeout, nameservers
        )
        duration = elapsed_ms(t_start)

        all_ips = ipv4_addrs + ipv6_addrs
        if not all_ips:
            return DNSResult(
                hostname=cleaned_host,
                is_success=False,
                lookup_duration_ms=duration,
                error_type="DNSResolutionError",
                error_message=f"No DNS A or AAAA records found for '{hostname}'.",
            )

        # Validate anti-SSRF: Every resolved address must be public
        for ip_str in all_ips:
            try:
                ip_obj = ipaddress.ip_address(ip_str)
                if is_ip_private_or_reserved(ip_obj):
                    return DNSResult(
                        hostname=cleaned_host,
                        is_success=False,
                        lookup_duration_ms=duration,
                        ipv4_addresses=ipv4_addrs,
                        ipv6_addresses=ipv6_addrs,
                        error_type="SSRFValidationError",
                        error_message=(
                            f"Hostname '{hostname}' resolved to private/reserved IP "
                            f"'{ip_str}' (SSRF violation)."
                        ),
                    )
            except ValueError:
                return DNSResult(
                    hostname=cleaned_host,
                    is_success=False,
                    lookup_duration_ms=duration,
                    error_type="DNSResolutionError",
                    error_message=f"Resolved invalid IP literal '{ip_str}'.",
                )

        primary_ip = ipv4_addrs[0] if ipv4_addrs else ipv6_addrs[0]
        return DNSResult(
            hostname=cleaned_host,
            is_success=True,
            lookup_duration_ms=duration,
            ipv4_addresses=ipv4_addrs,
            ipv6_addresses=ipv6_addrs,
            primary_ip=primary_ip,
        )

    except (dns.resolver.NXDOMAIN, dns.resolver.NoNameservers, dns.resolver.NoAnswer) as exc:
        return DNSResult(
            hostname=cleaned_host,
            is_success=False,
            lookup_duration_ms=elapsed_ms(t_start),
            error_type="DNSResolutionError",
            error_message=f"DNS resolution failed for '{hostname}': {exc}",
        )
    except dns.exception.Timeout as exc:
        return DNSResult(
            hostname=cleaned_host,
            is_success=False,
            lookup_duration_ms=elapsed_ms(t_start),
            error_type="DNSTimeoutError",
            error_message=f"DNS resolution timed out after {timeout}s: {exc}",
        )
    except Exception as exc:
        return DNSResult(
            hostname=cleaned_host,
            is_success=False,
            lookup_duration_ms=elapsed_ms(t_start),
            error_type="DNSResolutionError",
            error_message=f"DNS lookup error for '{hostname}': {exc}",
        )

