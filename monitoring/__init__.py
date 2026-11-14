"""Website Monitoring Engine Package.

Provides asynchronous multi-phase website probing (DNS, TCP, TLS, TTFB, HTTP),
strict anti-SSRF URL validation, SSL certificate lifecycle inspection, and
timing telemetry instrumentation.
"""

from monitoring.dns_checker import DNSResult, check_dns
from monitoring.http_checker import HTTPResult, check_http
from monitoring.probe_engine import ProbeResult, probe_website
from monitoring.ssl_checker import SSLResult, check_ssl
from monitoring.timing import TimingMetrics, elapsed_ms, monotonic_now
from monitoring.url_validator import (
    SecurityValidationError,
    is_ip_private_or_reserved,
    resolve_and_validate_hostname,
    validate_url_security,
)

# Backward-compatibility aliases
from monitoring.engine import WebsiteCheckResult, check_website_async

__all__ = [
    "DNSResult",
    "check_dns",
    "SSLResult",
    "check_ssl",
    "HTTPResult",
    "check_http",
    "ProbeResult",
    "probe_website",
    "WebsiteCheckResult",
    "check_website_async",
    "TimingMetrics",
    "monotonic_now",
    "elapsed_ms",
    "SecurityValidationError",
    "is_ip_private_or_reserved",
    "resolve_and_validate_hostname",
    "validate_url_security",
]
