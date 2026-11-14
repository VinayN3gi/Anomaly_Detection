"""SSL / TLS Certificate Monitoring and Expiry Inspector.

Performs asynchronous TLS handshakes, measures handshake latency with monotonic
clocks, extracts certificate expiration dates, and calculates days remaining.
Skips SSL checks for HTTP-only websites and returns NULL values for unavailable metrics.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import ssl

import truststore

from monitoring.timing import elapsed_ms, monotonic_now

# Inject native platform trust store into Python SSL
try:
    truststore.inject_into_ssl()
except Exception:
    pass

logger = logging.getLogger("aiops.ssl")


@dataclass
class SSLResult:
    """Structured telemetry metrics from SSL certificate inspection."""

    is_valid: bool | None = None
    expiry_date: str | None = None
    days_remaining: int | None = None
    handshake_duration_ms: float | None = None
    error_type: str | None = None
    error_message: str | None = None


def parse_cert_expiry(not_after_str: str) -> tuple[str, int]:
    """Parse certificate 'notAfter' timestamp string to ISO format and calculate days.

    Args:
        not_after_str: e.g. "Dec 25 22:56:35 2026 GMT"

    Returns:
        Tuple of (ISO format UTC string, integer days remaining).
    """
    for date_fmt in ("%b %d %H:%M:%S %Y %Z", "%b  %d %H:%M:%S %Y %Z"):
        try:
            expiry_dt = datetime.strptime(not_after_str, date_fmt).replace(
                tzinfo=timezone.utc
            )
            break
        except ValueError:
            continue
    else:
        raise ValueError(f"Unable to parse certificate notAfter date: {not_after_str}")

    now_utc = datetime.now(timezone.utc)
    delta = expiry_dt - now_utc
    return expiry_dt.isoformat(), int(delta.total_seconds() // 86400)


async def check_ssl(
    hostname: str,
    ip_address: str | None = None,
    port: int = 443,
    timeout: float = 5.0,
) -> SSLResult:
    """Perform TLS inspection, measure handshake latency, and extract cert expiry.

    Args:
        hostname: Domain name for SNI server_hostname verification.
        ip_address: Pre-resolved public IP address to connect directly to (anti-rebinding).
        port: TLS port (default 443).
        timeout: Handshake connection timeout in seconds.

    Returns:
        Structured SSLResult.
    """
    target_host = ip_address or hostname
    context = ssl.create_default_context()

    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host=target_host, port=port),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        return SSLResult(
            is_valid=False,
            error_type="ConnectionTimeoutError",
            error_message=f"TCP connection to {target_host}:{port} timed out after {timeout}s.",
        )
    except Exception as exc:
        return SSLResult(
            is_valid=False,
            error_type="TCPConnectionError",
            error_message=f"Failed to connect to {target_host}:{port}: {exc}",
        )

    # Perform TLS upgrade on the established TCP stream to isolate TLS handshake duration
    loop = asyncio.get_running_loop()
    protocol = writer.transport.get_protocol()
    t_tls_start = monotonic_now()

    try:
        new_transport = await asyncio.wait_for(
            loop.start_tls(
                writer.transport,
                protocol,
                context,
                server_hostname=hostname,
            ),
            timeout=timeout,
        )
        handshake_ms = elapsed_ms(t_tls_start)

        ssl_obj = new_transport.get_extra_info("ssl_object")
        cert = ssl_obj.getpeercert() if ssl_obj else None
        new_transport.close()

        if not cert or "notAfter" not in cert:
            return SSLResult(
                is_valid=True,
                handshake_duration_ms=handshake_ms,
                error_type="MissingCertificateError",
                error_message="Peer did not return a parseable certificate.",
            )

        expiry_iso, days_remaining = parse_cert_expiry(cert["notAfter"])
        is_expired = days_remaining < 0

        if is_expired:
            return SSLResult(
                is_valid=False,
                expiry_date=expiry_iso,
                days_remaining=days_remaining,
                handshake_duration_ms=handshake_ms,
                error_type="SSLCertificateExpiredError",
                error_message=f"SSL certificate expired {abs(days_remaining)} days ago.",
            )

        return SSLResult(
            is_valid=True,
            expiry_date=expiry_iso,
            days_remaining=days_remaining,
            handshake_duration_ms=handshake_ms,
        )

    except asyncio.TimeoutError:
        writer.close()
        return SSLResult(
            is_valid=False,
            handshake_duration_ms=elapsed_ms(t_tls_start),
            error_type="TLSTimeoutError",
            error_message=f"TLS handshake with {hostname} timed out after {timeout}s.",
        )
    except ssl.SSLCertVerificationError as exc:
        writer.close()
        return SSLResult(
            is_valid=False,
            handshake_duration_ms=elapsed_ms(t_tls_start),
            error_type="SSLCertVerificationError",
            error_message=f"TLS certificate verification failed for '{hostname}': {exc}",
        )
    except ssl.SSLError as exc:
        writer.close()
        return SSLResult(
            is_valid=False,
            handshake_duration_ms=elapsed_ms(t_tls_start),
            error_type="TLSError",
            error_message=f"TLS protocol error for '{hostname}': {exc}",
        )
    except Exception as exc:
        writer.close()
        return SSLResult(
            is_valid=False,
            handshake_duration_ms=elapsed_ms(t_tls_start),
            error_type="TLSHandshakeError",
            error_message=f"TLS handshake failed: {exc}",
        )
