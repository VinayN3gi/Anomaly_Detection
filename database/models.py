"""SQLAlchemy Declarative Models for Universal Website Monitoring.

Provides models for registered websites and time-series monitoring check results
compatible with both SQLite and TimescaleDB / PostgreSQL.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    Boolean,
    Column,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class Website(Base):
    """Monitored website record."""

    __tablename__ = "websites"

    id = Column(Integer, primary_key=True, autoincrement=True)
    url = Column(String(2048), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=True)
    check_interval = Column(Integer, nullable=False, default=60)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(
        String(50),
        nullable=False,
        default=lambda: datetime.now(timezone.utc).isoformat(),
    )
    updated_at = Column(
        String(50),
        nullable=False,
        default=lambda: datetime.now(timezone.utc).isoformat(),
    )

    # One-to-many relationship with monitoring results, cascading delete
    results = relationship(
        "MonitoringResult",
        back_populates="website",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def to_dict(self) -> dict[str, Any]:
        """Convert website model to dictionary representation."""
        return {
            "id": self.id,
            "url": self.url,
            "name": self.name,
            "check_interval": self.check_interval,
            "is_active": bool(self.is_active),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class MonitoringResult(Base):
    """Telemetry observations and timing metrics from an individual probe."""

    __tablename__ = "monitoring_checks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    website_id = Column(
        Integer,
        ForeignKey("websites.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    timestamp = Column(
        String(50),
        nullable=False,
        index=True,
        default=lambda: datetime.now(timezone.utc).isoformat(),
    )

    # Core Phase 2 timing measurements (in ms, NULL when unperformed)
    dns_lookup_ms = Column(Float, nullable=True)
    tcp_connect_ms = Column(Float, nullable=True)
    tls_handshake_ms = Column(Float, nullable=True)
    ttfb_ms = Column(Float, nullable=True)
    download_ms = Column(Float, nullable=True)
    total_time_ms = Column(Float, nullable=True)

    # HTTP & Payload telemetry
    http_status = Column(Integer, nullable=True)
    response_size_bytes = Column(Integer, nullable=True, default=0)
    redirect_count = Column(Integer, nullable=False, default=0)

    # SSL telemetry
    ssl_expiry_days = Column(Integer, nullable=True)
    ssl_valid = Column(Integer, nullable=True)  # 1 for True, 0 for False, NULL for HTTP
    ssl_expiry_date = Column(String(50), nullable=True)

    # Status & diagnostics
    dns_success = Column(Boolean, nullable=False, default=False)
    is_success = Column(Boolean, nullable=False, default=False)
    error_type = Column(String(100), nullable=True)
    error_message = Column(Text, nullable=True)
    resolved_ip = Column(String(100), nullable=True)

    # Phase 1 backward-compatibility columns
    is_up = Column(Integer, nullable=False, default=1)
    status = Column(String(20), nullable=False, default="UP")
    http_status_code = Column(Integer, nullable=True)
    response_time_ms = Column(Float, nullable=False, default=0.0)
    dns_time_ms = Column(Float, nullable=False, default=0.0)
    ssl_days_remaining = Column(Integer, nullable=True)

    website = relationship("Website", back_populates="results")

    __table_args__ = (
        Index("idx_checks_website_timestamp", "website_id", "timestamp"),
    )

    def to_dict(self) -> dict[str, Any]:
        """Convert monitoring result to dictionary representation."""
        return {
            "id": self.id,
            "website_id": self.website_id,
            "timestamp": self.timestamp,
            "dns_lookup_ms": self.dns_lookup_ms,
            "tcp_connect_ms": self.tcp_connect_ms,
            "tls_handshake_ms": self.tls_handshake_ms,
            "ttfb_ms": self.ttfb_ms,
            "download_ms": self.download_ms,
            "total_time_ms": self.total_time_ms,
            "http_status": self.http_status,
            "response_size_bytes": self.response_size_bytes or 0,
            "redirect_count": self.redirect_count,
            "ssl_expiry_days": self.ssl_expiry_days,
            "ssl_valid": bool(self.ssl_valid) if self.ssl_valid is not None else None,
            "ssl_expiry_date": self.ssl_expiry_date,
            "dns_success": bool(self.dns_success),
            "is_success": bool(self.is_success),
            "error_type": self.error_type,
            "error_message": self.error_message,
            "resolved_ip": self.resolved_ip,
            # Phase 1 aliases
            "is_up": bool(self.is_up),
            "status": self.status,
            "http_status_code": self.http_status_code,
            "response_time_ms": self.response_time_ms,
            "dns_time_ms": self.dns_time_ms,
            "ssl_days_remaining": self.ssl_days_remaining,
        }

