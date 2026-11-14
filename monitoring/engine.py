"""HTTP, DNS, and SSL Monitoring Engine for Universal Website Checks.

Executes non-invasive, lightweight public HTTP/S probes collecting detailed
telemetry: uptime status, response time, TTFB, DNS lookup duration, SSL certificate
expiry & validity, response size, redirect tracking, and error categorization.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import ssl
import time
from urllib.parse import urlparse

import httpx

import config
from monitoring.security import (
    SecurityValidationError,
    resolve_and_validate_hostname,
    validate_url_security,
)


@dataclass
class WebsiteCheckResult:
    """Encapsulates all metric observations from an individual monitoring probe."""

    url: str
    timestamp: str
    is_up: bool
    status: str  # "UP" or "DOWN"
    http_status_code: int | None
    response_time_ms: float
    ttfb_ms: float
    dns_time_ms: float
    ssl_valid: bool | None
    ssl_expiry_date: str | None
    ssl_days_remaining: int | None
    response_size_bytes: int
    redirect_count: int
    resolved_ip: str | None
    error_message: str | None

    def to_dict(self) -> dict:
        """Convert dataclass to dictionary."""
        return asdict(self)


def inspect_ssl_certificate(
    hostname: str,
    port: int = 443,
    timeout: float = 5.0,
) -> tuple[bool | None, str | None, int | None, str | None]:
    """Retrieve and validate SSL certificate parameters using standard TLS handshake.

    Args:
        hostname: Domain name to inspect.
        port: TLS port (default 443).
        timeout: Socket timeout in seconds.

    Returns:
        Tuple of (is_valid, expiry_date_iso, days_remaining, error_message).
    """
    ctx = ssl.create_default_context()
    try:
        import socket

        with socket.create_connection((hostname, port), timeout=timeout) as sock:
            with ctx.wrap_socket(sock, server_hostname=hostname) as ssock:
                cert = ssock.getpeercert()
                if not cert or "notAfter" not in cert:
                    return False, None, None, "No peer certificate returned"

                # Parse notAfter date e.g. 'May 15 12:00:00 2026 GMT'
                not_after_str = cert["notAfter"]
                expiry_dt = datetime.strptime(
                    not_after_str, "%b %d %H:%M:%S %Y %Z"
                ).replace(tzinfo=timezone.utc)

                now_utc = datetime.now(timezone.utc)
                days_left = (expiry_dt - now_utc).days
                is_valid = days_left > 0

                return is_valid, expiry_dt.isoformat(), days_left, None

    except ssl.SSLCertVerificationError as exc:
        return False, None, None, f"SSL Certificate Verification Failed: {exc}"
    except (socket.timeout, TimeoutError):
        return False, None, None, "SSL Handshake timed out"
    except Exception as exc:
        return False, None, None, f"SSL Error: {exc}"


async def check_website_async(
    url: str,
    timeout: float = config.REQUEST_TIMEOUT,
    connect_timeout: float = config.CONNECT_TIMEOUT,
    max_redirects: int = config.MAX_REDIRECTS,
) -> WebsiteCheckResult:
    """Execute comprehensive asynchronous monitoring probe on a target website.

    Args:
        url: Target website URL.
        timeout: Total request timeout (seconds).
        connect_timeout: Socket connection timeout (seconds).
        max_redirects: Maximum allowable HTTP redirects.

    Returns:
        WebsiteCheckResult instance containing collected performance telemetry.
    """
    now_iso = datetime.now(timezone.utc).isoformat()

    # Step 1: URL & Anti-SSRF Security Validation + DNS Timing
    dns_start = time.perf_counter()
    try:
        normalized_url, resolved_ip, port = validate_url_security(url)
        dns_time_ms = round((time.perf_counter() - dns_start) * 1000, 2)
    except SecurityValidationError as exc:
        return WebsiteCheckResult(
            url=url,
            timestamp=now_iso,
            is_up=False,
            status="DOWN",
            http_status_code=None,
            response_time_ms=0.0,
            ttfb_ms=0.0,
            dns_time_ms=0.0,
            ssl_valid=None,
            ssl_expiry_date=None,
            ssl_days_remaining=None,
            response_size_bytes=0,
            redirect_count=0,
            resolved_ip=None,
            error_message=f"Security Validation Blocked: {exc}",
        )
    except Exception as exc:
        dns_time_ms = round((time.perf_counter() - dns_start) * 1000, 2)
        return WebsiteCheckResult(
            url=url,
            timestamp=now_iso,
            is_up=False,
            status="DOWN",
            http_status_code=None,
            response_time_ms=0.0,
            ttfb_ms=0.0,
            dns_time_ms=dns_time_ms,
            ssl_valid=None,
            ssl_expiry_date=None,
            ssl_days_remaining=None,
            response_size_bytes=0,
            redirect_count=0,
            resolved_ip=None,
            error_message=f"DNS Resolution Error: {exc}",
        )

    parsed = urlparse(normalized_url)
    is_https = parsed.scheme == "https"

    # Step 2: SSL Certificate Inspection for HTTPS targets
    ssl_valid = None
    ssl_expiry_date = None
    ssl_days_remaining = None
    ssl_error = None

    if is_https:
        # Run blocking socket SSL inspection in thread pool
        ssl_valid, ssl_expiry_date, ssl_days_remaining, ssl_error = (
            await asyncio.to_thread(
                inspect_ssl_certificate,
                parsed.hostname,
                port,
                connect_timeout,
            )
        )

    # Step 3: Execute Lightweight HTTP Request
    headers = {
        "User-Agent": config.USER_AGENT,
        "Accept": "*/*",
        "Connection": "close",
    }
    client_timeout = httpx.Timeout(
        timeout,
        connect=connect_timeout,
        read=timeout,
        write=timeout,
    )

    t_start = time.perf_counter()
    ttfb_ms = 0.0
    total_time_ms = 0.0
    status_code: int | None = None
    response_size = 0
    redirect_count = 0
    error_message: str | None = None
    is_up = False

    try:
        async with httpx.AsyncClient(
            timeout=client_timeout,
            follow_redirects=True,
            max_redirects=max_redirects,
            verify=True,
        ) as client:
            async with client.stream("GET", normalized_url, headers=headers) as response:
                ttfb_ms = round((time.perf_counter() - t_start) * 1000, 2)
                status_code = response.status_code
                redirect_count = len(response.history)

                # Validate redirects against anti-SSRF policy
                for redir in response.history:
                    redir_host = redir.url.host
                    if redir_host:
                        resolve_and_validate_hostname(redir_host)

                # Read body stream to compute exact response payload size
                body_bytes = await response.aread()
                response_size = len(body_bytes)

        total_time_ms = round((time.perf_counter() - t_start) * 1000, 2)

        # Uptime definition: 2xx, 3xx, 4xx indicate server is responsive and UP.
        # 5xx responses indicate internal server failures/downtime.
        if 200 <= status_code < 500:
            is_up = True
            if ssl_valid is False and is_https:
                # Flag SSL verification error while recording server responsiveness
                error_message = ssl_error or "SSL Certificate is invalid or expired"
        else:
            is_up = False
            error_message = f"Server returned error HTTP {status_code}"

    except httpx.ConnectTimeout:
        total_time_ms = round((time.perf_counter() - t_start) * 1000, 2)
        is_up = False
        error_message = "Connection timed out"
    except httpx.ReadTimeout:
        total_time_ms = round((time.perf_counter() - t_start) * 1000, 2)
        is_up = False
        error_message = "Read response timed out"
    except httpx.ConnectError as exc:
        total_time_ms = round((time.perf_counter() - t_start) * 1000, 2)
        is_up = False
        error_message = f"Connection failed: {exc}"
    except httpx.TooManyRedirects:
        total_time_ms = round((time.perf_counter() - t_start) * 1000, 2)
        is_up = False
        error_message = f"Exceeded maximum allowed redirects ({max_redirects})"
    except SecurityValidationError as exc:
        total_time_ms = round((time.perf_counter() - t_start) * 1000, 2)
        is_up = False
        error_message = f"Redirect blocked by SSRF policy: {exc}"
    except Exception as exc:
        total_time_ms = round((time.perf_counter() - t_start) * 1000, 2)
        is_up = False
        error_message = f"HTTP Probe Error: {exc}"

    return WebsiteCheckResult(
        url=normalized_url,
        timestamp=now_iso,
        is_up=is_up,
        status="UP" if is_up else "DOWN",
        http_status_code=status_code,
        response_time_ms=total_time_ms,
        ttfb_ms=ttfb_ms if ttfb_ms > 0 else total_time_ms,
        dns_time_ms=dns_time_ms,
        ssl_valid=ssl_valid,
        ssl_expiry_date=ssl_expiry_date,
        ssl_days_remaining=ssl_days_remaining,
        response_size_bytes=response_size,
        redirect_count=redirect_count,
        resolved_ip=resolved_ip,
        error_message=error_message,
    )


def check_website(
    url: str,
    timeout: float = config.REQUEST_TIMEOUT,
    connect_timeout: float = config.CONNECT_TIMEOUT,
    max_redirects: int = config.MAX_REDIRECTS,
) -> WebsiteCheckResult:
    """Synchronous convenience wrapper for check_website_async."""
    return asyncio.run(
        check_website_async(
            url=url,
            timeout=timeout,
            connect_timeout=connect_timeout,
            max_redirects=max_redirects,
        )
    )

