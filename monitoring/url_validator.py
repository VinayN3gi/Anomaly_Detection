"""URL and Anti-SSRF Validation Engine.

Provides clean modular interface forwarding to monitoring.security to ensure
seamless interoperability and monkeypatch support across test suites.
"""

from __future__ import annotations

import monitoring.security as _sec

SecurityValidationError = _sec.SecurityValidationError
BLOCKED_METADATA_IPS = _sec.BLOCKED_METADATA_IPS


def is_ip_private_or_reserved(*args, **kwargs):
    """Delegate to monitoring.security.is_ip_private_or_reserved."""
    return _sec.is_ip_private_or_reserved(*args, **kwargs)


def resolve_and_validate_hostname(*args, **kwargs):
    """Delegate dynamically to monitoring.security.resolve_and_validate_hostname."""
    fn = getattr(
        _sec, "resolve_and_validate_hostname", _sec.resolve_and_validate_hostname
    )
    return fn(*args, **kwargs)


def validate_url_security(*args, **kwargs):
    """Delegate dynamically to monitoring.security.validate_url_security."""
    fn = getattr(_sec, "validate_url_security", _sec.validate_url_security)
    return fn(*args, **kwargs)


__all__ = [
    "SecurityValidationError",
    "BLOCKED_METADATA_IPS",
    "is_ip_private_or_reserved",
    "resolve_and_validate_hostname",
    "validate_url_security",
]
