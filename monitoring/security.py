"""Security and Anti-SSRF Validation Engine for Website Monitoring.

Provides backward-compatible interface re-exporting from monitoring.url_validator.
"""

from monitoring.url_validator import (  # noqa: F401
    BLOCKED_METADATA_IPS,
    SecurityValidationError,
    is_ip_private_or_reserved,
    resolve_and_validate_hostname,
    validate_url_security,
)

__all__ = [
    "BLOCKED_METADATA_IPS",
    "SecurityValidationError",
    "is_ip_private_or_reserved",
    "resolve_and_validate_hostname",
    "validate_url_security",
]
