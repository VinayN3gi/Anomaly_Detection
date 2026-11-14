"""HTTP Telemetry and Probe Checker using HTTPX.

Measures precise HTTP response phases: Time to First Byte (TTFB), content download
duration, and total latency using monotonic clocks. Implements safe manual redirect
following with per-hop anti-SSRF vetting and response body size bounding.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
from urllib.parse import urljoin

import httpx

import config
from monitoring.timing import elapsed_ms, monotonic_now
from monitoring.url_validator import SecurityValidationError, validate_url_security

logger = logging.getLogger("aiops.http")


@dataclass
class HTTPResult:
    """Structured telemetry metrics from an HTTP/S probe check."""

    is_success: bool
    status_code: int | None
    ttfb_ms: float | None
    download_ms: float | None
    total_time_ms: float | None
    response_size_bytes: int
    redirect_count: int
    final_url: str
    error_type: str | None = None
    error_message: str | None = None


async def check_http(
    url: str,
    request_timeout: float = 10.0,
    connect_timeout: float = 5.0,
    max_redirects: int = 5,
    max_response_size: int = 5 * 1024 * 1024,
    user_agent: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> HTTPResult:
    """Execute instrumented HTTP request with safe redirect tracking and TTFB timing.

    Args:
        url: Validated public target URL.
        request_timeout: Total request timeout in seconds.
        connect_timeout: Initial connection timeout in seconds.
        max_redirects: Maximum number of allowed redirects (default 5).
        max_response_size: Maximum download payload in bytes (default 5MB).
        user_agent: Custom User-Agent header string.
        client: Optional pre-configured httpx.AsyncClient (for testing/mocking).

    Returns:
        Structured HTTPResult containing status, sizes, timings, and error info.
    """
    ua = user_agent or config.USER_AGENT
    headers = {
        "User-Agent": ua,
        "Accept": "*/*",
        "Connection": "close",
    }

    current_url = url
    redirect_count = 0
    t_overall_start = monotonic_now()

    timeout_cfg = httpx.Timeout(
        timeout=request_timeout,
        connect=connect_timeout,
        read=request_timeout,
        write=request_timeout,
    )

    should_close_client = client is None
    active_client = client or httpx.AsyncClient(
        timeout=timeout_cfg,
        follow_redirects=False,
        verify=True,
    )

    try:
        while True:
            # Validate every hop URL (including initial URL and redirect targets)
            try:
                norm_url, _, _ = validate_url_security(current_url)
                current_url = norm_url
            except SecurityValidationError as exc:
                return HTTPResult(
                    is_success=False,
                    status_code=None,
                    ttfb_ms=None,
                    download_ms=None,
                    total_time_ms=elapsed_ms(t_overall_start),
                    response_size_bytes=0,
                    redirect_count=redirect_count,
                    final_url=current_url,
                    error_type="SSRFValidationError",
                    error_message=f"SSRF policy blocked redirect target: {exc}",
                )

            t_req_start = monotonic_now()

            try:
                async with active_client.stream(
                    "GET",
                    current_url,
                    headers=headers,
                ) as response:
                    t_first_byte = monotonic_now()
                    ttfb_ms = elapsed_ms(t_req_start, t_first_byte)
                    status_code = response.status_code

                    # Handle HTTP redirects (301, 302, 303, 307, 308)
                    if status_code in (301, 302, 303, 307, 308):
                        if redirect_count >= max_redirects:
                            return HTTPResult(
                                is_success=False,
                                status_code=status_code,
                                ttfb_ms=ttfb_ms,
                                download_ms=0.0,
                                total_time_ms=elapsed_ms(t_overall_start),
                                response_size_bytes=0,
                                redirect_count=redirect_count,
                                final_url=current_url,
                                error_type="TooManyRedirectsError",
                                error_message=(
                                    f"Exceeded maximum allowed redirects ({max_redirects})."
                                ),
                            )

                        location = response.headers.get("location")
                        if not location:
                            # Redirect header missing; treat as terminal
                            pass
                        else:
                            redirect_count += 1
                            current_url = urljoin(current_url, location)
                            continue

                    # Read response content with size limit protection
                    bytes_read = 0
                    async for chunk in response.aiter_bytes():
                        bytes_read += len(chunk)
                        if bytes_read > max_response_size:
                            return HTTPResult(
                                is_success=False,
                                status_code=status_code,
                                ttfb_ms=ttfb_ms,
                                download_ms=elapsed_ms(t_first_byte),
                                total_time_ms=elapsed_ms(t_overall_start),
                                response_size_bytes=bytes_read,
                                redirect_count=redirect_count,
                                final_url=current_url,
                                error_type="ResponseSizeLimitExceededError",
                                error_message=(
                                    f"Response size exceeded limit of {max_response_size} bytes."
                                ),
                            )

                    t_download_end = monotonic_now()
                    download_ms = elapsed_ms(t_first_byte, t_download_end)
                    total_time_ms = elapsed_ms(t_overall_start, t_download_end)

                    # Determine success according to status code requirements:
                    # 2xx / 3xx = Success
                    # 4xx = Client Error (is_success = False)
                    # 5xx = Server Error (is_success = False, recorded as HTTP failure)
                    if status_code >= 500:
                        is_success = False
                        err_type = "HttpServerError"
                        err_msg = f"HTTP {status_code} Internal Server Error"
                    elif status_code >= 400:
                        is_success = False
                        err_type = "HttpClientError"
                        err_msg = f"HTTP {status_code} Client Error"
                    else:
                        is_success = True
                        err_type = None
                        err_msg = None

                    return HTTPResult(
                        is_success=is_success,
                        status_code=status_code,
                        ttfb_ms=ttfb_ms,
                        download_ms=download_ms,
                        total_time_ms=total_time_ms,
                        response_size_bytes=bytes_read,
                        redirect_count=redirect_count,
                        final_url=current_url,
                        error_type=err_type,
                        error_message=err_msg,
                    )

            except httpx.ConnectTimeout as exc:
                return HTTPResult(
                    is_success=False,
                    status_code=None,
                    ttfb_ms=None,
                    download_ms=None,
                    total_time_ms=elapsed_ms(t_overall_start),
                    response_size_bytes=0,
                    redirect_count=redirect_count,
                    final_url=current_url,
                    error_type="ConnectTimeoutError",
                    error_message=f"TCP connection timed out: {exc}",
                )
            except httpx.ReadTimeout as exc:
                return HTTPResult(
                    is_success=False,
                    status_code=None,
                    ttfb_ms=None,
                    download_ms=None,
                    total_time_ms=elapsed_ms(t_overall_start),
                    response_size_bytes=0,
                    redirect_count=redirect_count,
                    final_url=current_url,
                    error_type="ReadTimeoutError",
                    error_message=f"Server read timed out: {exc}",
                )
            except httpx.ConnectError as exc:
                return HTTPResult(
                    is_success=False,
                    status_code=None,
                    ttfb_ms=None,
                    download_ms=None,
                    total_time_ms=elapsed_ms(t_overall_start),
                    response_size_bytes=0,
                    redirect_count=redirect_count,
                    final_url=current_url,
                    error_type="ConnectError",
                    error_message=f"Connection failed: {exc}",
                )
            except Exception as exc:
                return HTTPResult(
                    is_success=False,
                    status_code=None,
                    ttfb_ms=None,
                    download_ms=None,
                    total_time_ms=elapsed_ms(t_overall_start),
                    response_size_bytes=0,
                    redirect_count=redirect_count,
                    final_url=current_url,
                    error_type="HTTPRequestError",
                    error_message=f"HTTP probe encountered error: {exc}",
                )

    finally:
        if should_close_client:
            await active_client.aclose()

