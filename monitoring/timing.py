"""Timing metrics and monotonic measurement instrumentation.

Captures fine-grained network phases: DNS lookup, TCP connection, TLS handshake,
Time to First Byte (TTFB), and content download duration using monotonic clocks.
Never fabricates timing values; unavailable measurements are represented as None (NULL).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import time


def monotonic_now() -> float:
    """Return the current value of a monotonic clock in seconds."""
    return time.perf_counter()


def elapsed_ms(start_time: float, end_time: float | None = None) -> float:
    """Compute elapsed duration in milliseconds rounded to 2 decimal places.

    Args:
        start_time: Monotonic start timestamp in seconds.
        end_time: Monotonic end timestamp in seconds (defaults to current monotonic time).

    Returns:
        Duration in milliseconds.
    """
    if end_time is None:
        end_time = monotonic_now()
    return round(max(0.0, (end_time - start_time) * 1000.0), 2)


@dataclass
class TimingMetrics:
    """Individual phase durations in milliseconds.

    All fields are nullable (None) to ensure absent or unperformed phases
    are accurately represented without fabrication.
    """

    dns_lookup_ms: float | None = None
    tcp_connect_ms: float | None = None
    tls_handshake_ms: float | None = None
    ttfb_ms: float | None = None
    download_ms: float | None = None
    total_time_ms: float | None = None

    def to_dict(self) -> dict[str, float | None]:
        """Convert metrics to a dictionary."""
        return asdict(self)
