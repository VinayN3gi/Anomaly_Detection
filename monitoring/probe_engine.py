"""Asynchronous Website Probing Engine.

Orchestrates multi-phase active probes: DNS resolution via dnspython,
TCP/TLS connection establishment, SSL certificate validation, and HTTPX
streaming telemetry (TTFB, download duration, response code, size, redirects).
Never fabricates timing values; unavailable metrics are stored as None (NULL).
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import logging
from urllib.parse import urlparse

import config
from monitoring.dns_checker import DNSResult, check_dns
from monitoring.http_checker import HTTPResult, check_http
from monitoring.ssl_checker import SSLResult, check_ssl
from monitoring.timing import elapsed_ms, monotonic_now
from monitoring.url_validator import SecurityValidationError, validate_url_security

logger = logging.getLogger("aiops.probe")


@dataclass
class ProbeResult:
    """Comprehensive telemetry data collected across all monitoring phases."""

    url: str
    timestamp: str  # ISO 8601 UTC string
    is_success: bool
    status: str  # "UP" or "DOWN"
    http_status: int | None
    dns_lookup_ms: float | None
    tcp_connect_ms: float | None
    tls_handshake_ms: float | None
    ttfb_ms: float | None
    download_ms: float | None
    total_time_ms: float | None
    response_size_bytes: int
    redirect_count: int
    ssl_valid: bool | None
    ssl_expiry_date: str | None
    ssl_expiry_days: int | None
    dns_success: bool
    resolved_ip: str | None
    error_type: str | None
    error_message: str | None

    # Backward compatibility properties for Phase 1 code
    @property
    def is_up(self) -> bool:
        """Alias for server responsiveness."""
        return self.status == "UP"

    @property
    def http_status_code(self) -> int | None:
        """Alias for http_status."""
        return self.http_status

    @property
    def response_time_ms(self) -> float:
        """Alias for total_time_ms (returns 0.0 if None)."""
        return self.total_time_ms or 0.0

    @property
    def dns_time_ms(self) -> float:
        """Alias for dns_lookup_ms (returns 0.0 if None)."""
        return self.dns_lookup_ms or 0.0

    @property
    def ssl_days_remaining(self) -> int | None:
        """Alias for ssl_expiry_days."""
        return self.ssl_expiry_days

    def to_dict(self) -> dict:
        """Convert dataclass to standard dictionary including legacy aliases."""
        data = asdict(self)
        data["is_up"] = self.is_up
        data["http_status_code"] = self.http_status_code
        data["response_time_ms"] = self.response_time_ms
        data["dns_time_ms"] = self.dns_time_ms
        data["ssl_days_remaining"] = self.ssl_days_remaining
        return data


async def probe_website(
    url: str,
    request_timeout: float | None = None,
    connect_timeout: float | None = None,
    max_redirects: int | None = None,
) -> ProbeResult:
    """Execute complete multi-phase asynchronous probe for a website.

    Phases executed:
    1. URL normalization & Anti-SSRF boundary enforcement
    2. DNS resolution (A/AAAA records, latency, and resolved address verification)
    3. TCP connection & SSL/TLS certificate inspection (HTTPS only)
    4. HTTP stream evaluation (TTFB, download latency, status code, size limits)

    Args:
        url: User-provided website URL.
        request_timeout: HTTP request timeout in seconds (default from config).
        connect_timeout: Connection timeout in seconds (default from config).
        max_redirects: Maximum allowed redirects (default from config).

    Returns:
        Structured ProbeResult containing all phase timings and diagnostics.
    """
    req_timeout = request_timeout or config.REQUEST_TIMEOUT
    conn_timeout = connect_timeout or config.CONNECT_TIMEOUT
    max_redirs = max_redirects or config.MAX_REDIRECTS

    now_utc = datetime.now(timezone.utc).isoformat()
    t_probe_start = monotonic_now()

    # Phase 1: Security and Anti-SSRF Validation
    try:
        norm_url, initial_ip, port = validate_url_security(url)
    except SecurityValidationError as exc:
        return ProbeResult(
            url=url,
            timestamp=now_utc,
            is_success=False,
            status="DOWN",
            http_status=None,
            dns_lookup_ms=None,
            tcp_connect_ms=None,
            tls_handshake_ms=None,
            ttfb_ms=None,
            download_ms=None,
            total_time_ms=elapsed_ms(t_probe_start),
            response_size_bytes=0,
            redirect_count=0,
            ssl_valid=None,
            ssl_expiry_date=None,
            ssl_expiry_days=None,
            dns_success=False,
            resolved_ip=None,
            error_type="SSRFValidationError",
            error_message=f"SSRF policy blocked URL: {exc}",
        )

    parsed = urlparse(norm_url)
    hostname = parsed.hostname or ""
    is_https = parsed.scheme.lower() == "https"

    # Phase 2: DNS Resolution
    dns_res: DNSResult = await check_dns(hostname, timeout=conn_timeout)
    if not dns_res.is_success:
        return ProbeResult(
            url=norm_url,
            timestamp=now_utc,
            is_success=False,
            status="DOWN",
            http_status=None,
            dns_lookup_ms=dns_res.lookup_duration_ms,
            tcp_connect_ms=None,
            tls_handshake_ms=None,
            ttfb_ms=None,
            download_ms=None,
            total_time_ms=elapsed_ms(t_probe_start),
            response_size_bytes=0,
            redirect_count=0,
            ssl_valid=None,
            ssl_expiry_date=None,
            ssl_expiry_days=None,
            dns_success=False,
            resolved_ip=None,
            error_type=dns_res.error_type or "DNSResolutionError",
            error_message=dns_res.error_message or "DNS resolution failed.",
        )

    primary_ip = dns_res.primary_ip or initial_ip

    # Phase 3: SSL / TLS Certificate Inspection (HTTPS only)
    ssl_res = SSLResult()
    tcp_connect_ms: float | None = None
    tls_handshake_ms: float | None = None

    if is_https:
        ssl_res = await check_ssl(
            hostname=hostname,
            ip_address=primary_ip,
            port=port,
            timeout=conn_timeout,
        )
        tls_handshake_ms = ssl_res.handshake_duration_ms

    # Phase 4: HTTP Request & Response Telemetry
    http_res: HTTPResult = await check_http(
        url=norm_url,
        request_timeout=req_timeout,
        connect_timeout=conn_timeout,
        max_redirects=max_redirs,
    )

    total_duration = elapsed_ms(t_probe_start)

    # Determine overall status:
    # A website is considered "UP" if it responded to HTTP with a non-5xx status code.
    # HTTP 500+ is recorded as DOWN / Failure per Task 5.
    status_code = http_res.status_code
    if status_code is not None and status_code < 500:
        status_label = "UP"
        # Success is True for 2xx/3xx, False for 4xx client errors
        is_success = http_res.is_success
    else:
        status_label = "DOWN"
        is_success = False

    error_type = http_res.error_type or (ssl_res.error_type if not ssl_res.is_valid else None)
    error_msg = http_res.error_message or (ssl_res.error_message if not ssl_res.is_valid else None)

    return ProbeResult(
        url=norm_url,
        timestamp=now_utc,
        is_success=is_success,
        status=status_label,
        http_status=status_code,
        dns_lookup_ms=dns_res.lookup_duration_ms,
        tcp_connect_ms=tcp_connect_ms,
        tls_handshake_ms=tls_handshake_ms,
        ttfb_ms=http_res.ttfb_ms,
        download_ms=http_res.download_ms,
        total_time_ms=total_duration,
        response_size_bytes=http_res.response_size_bytes,
        redirect_count=http_res.redirect_count,
        ssl_valid=ssl_res.is_valid,
        ssl_expiry_date=ssl_res.expiry_date,
        ssl_expiry_days=ssl_res.days_remaining,
        dns_success=True,
        resolved_ip=primary_ip,
        error_type=error_type,
        error_message=error_msg,
    )

