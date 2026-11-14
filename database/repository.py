"""SQLAlchemy Repository Pattern for Websites and Monitoring Results.

Encapsulates database access, atomic transactions, entity persistence,
querying, and aggregate metrics computation for SQLite and PostgreSQL/TimescaleDB.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, desc, func, select
from sqlalchemy.orm import Session, sessionmaker

import config
from database.models import Base, MonitoringResult, Website
from monitoring.probe_engine import ProbeResult
from monitoring.url_validator import SecurityValidationError, validate_url_security


class WebsiteNotFoundError(Exception):
    """Raised when a website record does not exist."""

    pass


class WebsiteAlreadyExistsError(Exception):
    """Raised when registering a URL that is already monitored."""

    pass


class MonitoringRepository:
    """Repository handling CRUD operations for websites and probe results."""

    def __init__(self, db_url_or_path: str | Path | None = None) -> None:
        """Initialize database engine and session factory.

        Args:
            db_url_or_path: Optional custom database connection string or file path.
        """
        if db_url_or_path is None:
            db_url = config.DATABASE_URL
        elif isinstance(db_url_or_path, Path) or (
            isinstance(db_url_or_path, str) and not ("://" in db_url_or_path)
        ):
            path = Path(db_url_or_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            db_url = f"sqlite:///{path}"
        else:
            db_url = str(db_url_or_path)

        connect_args = {}
        if db_url.startswith("sqlite"):
            connect_args["check_same_thread"] = False
            connect_args["timeout"] = 15.0

        self.engine = create_engine(
            db_url,
            connect_args=connect_args,
            pool_pre_ping=True,
        )
        self.SessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=self.engine,
        )

        # Ensure tables exist
        Base.metadata.create_all(bind=self.engine)

    def get_session(self) -> Session:
        """Create a new database session."""
        return self.SessionLocal()

    # --- Website Registry Management (Task 1) ---

    def register_website(
        self,
        url: str,
        name: str | None = None,
        check_interval: int = 60,
    ) -> Website:
        """Validate and register a new website for monitoring.

        Args:
            url: Target URL (HTTP/HTTPS only).
            name: Optional display name.
            check_interval: Monitoring interval in seconds (minimum 60s enforced).

        Returns:
            Created Website instance.

        Raises:
            SecurityValidationError: If URL violates security or anti-SSRF rules.
            WebsiteAlreadyExistsError: If normalized URL is already monitored.
        """
        norm_url, _, _ = validate_url_security(url)
        min_interval = max(60, check_interval)
        display_name = name.strip() if name and name.strip() else norm_url
        now_iso = datetime.now(timezone.utc).isoformat()

        with self.get_session() as session:
            existing = session.execute(
                select(Website).where(Website.url == norm_url)
            ).scalar_one_or_none()
            if existing:
                raise WebsiteAlreadyExistsError(
                    f"Website '{norm_url}' is already registered for monitoring."
                )

            website = Website(
                url=norm_url,
                name=display_name,
                check_interval=min_interval,
                is_active=True,
                created_at=now_iso,
                updated_at=now_iso,
            )
            session.add(website)
            session.commit()
            session.refresh(website)
            return website

    def get_website(self, website_id: int) -> Website:
        """Fetch a website by its primary key ID.

        Raises:
            WebsiteNotFoundError: If ID is not found.
        """
        with self.get_session() as session:
            website = session.get(Website, website_id)
            if not website:
                raise WebsiteNotFoundError(f"Website with ID {website_id} not found.")
            return website

    def get_website_by_url(self, url: str) -> Website | None:
        """Fetch a website by normalized URL."""
        with self.get_session() as session:
            return session.execute(
                select(Website).where(Website.url == url)
            ).scalar_one_or_none()

    def list_websites(self, active_only: bool = False) -> list[Website]:
        """Retrieve list of registered websites."""
        with self.get_session() as session:
            stmt = select(Website)
            if active_only:
                stmt = stmt.where(Website.is_active == True)  # noqa: E712
            stmt = stmt.order_by(Website.id)
            return list(session.execute(stmt).scalars().all())

    def update_website(
        self,
        website_id: int,
        name: str | None = None,
        check_interval: int | None = None,
        is_active: bool | None = None,
    ) -> Website:
        """Update website metadata, active status, or check interval."""
        now_iso = datetime.now(timezone.utc).isoformat()
        with self.get_session() as session:
            website = session.get(Website, website_id)
            if not website:
                raise WebsiteNotFoundError(f"Website with ID {website_id} not found.")

            if name is not None:
                website.name = name.strip() or website.url
            if check_interval is not None:
                website.check_interval = max(60, check_interval)
            if is_active is not None:
                website.is_active = is_active

            website.updated_at = now_iso
            session.commit()
            session.refresh(website)
            return website

    def set_website_active(self, website_id: int, is_active: bool) -> Website:
        """Activate or deactivate a website's monitoring status."""
        return self.update_website(website_id, is_active=is_active)

    def delete_website(self, website_id: int) -> None:
        """Permanently delete a website and all associated monitoring results."""
        with self.get_session() as session:
            website = session.get(Website, website_id)
            if not website:
                raise WebsiteNotFoundError(f"Website with ID {website_id} not found.")
            session.delete(website)
            session.commit()

    # --- Probe Result Persistence (Task 7) ---

    def save_probe_result(
        self,
        website_id: int,
        result: ProbeResult | Any,
    ) -> MonitoringResult:
        """Persist a completed or failed probe result to the database.

        Args:
            website_id: Foreign key ID of registered website.
            result: ProbeResult or WebsiteCheckResult instance.

        Returns:
            Created MonitoringResult record.
        """
        # Extract fields handling both ProbeResult and WebsiteCheckResult
        http_code = getattr(result, "http_status", getattr(result, "http_status_code", None))
        is_up_bool = getattr(result, "is_up", result.status == "UP")
        total_time = getattr(result, "total_time_ms", getattr(result, "response_time_ms", 0.0))
        dns_time = getattr(result, "dns_lookup_ms", getattr(result, "dns_time_ms", 0.0))
        ssl_days = getattr(result, "ssl_expiry_days", getattr(result, "ssl_days_remaining", None))

        with self.get_session() as session:
            record = MonitoringResult(
                website_id=website_id,
                timestamp=result.timestamp,
                dns_lookup_ms=getattr(result, "dns_lookup_ms", dns_time),
                tcp_connect_ms=getattr(result, "tcp_connect_ms", None),
                tls_handshake_ms=getattr(result, "tls_handshake_ms", None),
                ttfb_ms=getattr(result, "ttfb_ms", None),
                download_ms=getattr(result, "download_ms", None),
                total_time_ms=total_time,
                http_status=http_code,
                response_size_bytes=result.response_size_bytes or 0,
                redirect_count=result.redirect_count or 0,
                ssl_expiry_days=ssl_days,
                ssl_valid=1 if result.ssl_valid else (0 if result.ssl_valid is False else None),
                ssl_expiry_date=result.ssl_expiry_date,
                dns_success=getattr(result, "dns_success", True),
                is_success=getattr(result, "is_success", is_up_bool),
                error_type=getattr(result, "error_type", None),
                error_message=result.error_message,
                resolved_ip=result.resolved_ip,
                # Phase 1 backward compatibility
                is_up=1 if is_up_bool else 0,
                status="UP" if is_up_bool else "DOWN",
                http_status_code=http_code,
                response_time_ms=total_time or 0.0,
                dns_time_ms=dns_time or 0.0,
                ssl_days_remaining=ssl_days,
            )
            session.add(record)
            session.commit()
            session.refresh(record)
            return record

    def get_recent_results(
        self,
        website_id: int,
        limit: int = 50,
    ) -> list[MonitoringResult]:
        """Retrieve recent monitoring results for a website in reverse chronological order."""
        with self.get_session() as session:
            stmt = (
                select(MonitoringResult)
                .where(MonitoringResult.website_id == website_id)
                .order_by(desc(MonitoringResult.timestamp))
                .limit(limit)
            )
            return list(session.execute(stmt).scalars().all())

    def get_latest_result(self, website_id: int) -> MonitoringResult | None:
        """Fetch the most recent probe result for a website."""
        with self.get_session() as session:
            stmt = (
                select(MonitoringResult)
                .where(MonitoringResult.website_id == website_id)
                .order_by(desc(MonitoringResult.timestamp))
                .limit(1)
            )
            return session.execute(stmt).scalar_one_or_none()

    def get_aggregate_stats(
        self,
        website_id: int,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Compute aggregate uptime percentage, average response time, TTFB, and DNS."""
        with self.get_session() as session:
            subq = (
                select(
                    MonitoringResult.is_up,
                    MonitoringResult.is_success,
                    MonitoringResult.response_time_ms,
                    MonitoringResult.ttfb_ms,
                    MonitoringResult.dns_time_ms,
                )
                .where(MonitoringResult.website_id == website_id)
                .order_by(desc(MonitoringResult.timestamp))
                .limit(limit)
                .subquery()
            )

            stmt = select(
                func.count().label("total_checks"),
                func.sum(subq.c.is_up).label("up_checks"),
                func.avg(subq.c.response_time_ms).label("avg_response_time_ms"),
                func.avg(subq.c.ttfb_ms).label("avg_ttfb_ms"),
                func.avg(subq.c.dns_time_ms).label("avg_dns_time_ms"),
                func.min(subq.c.response_time_ms).label("min_response_time_ms"),
                func.max(subq.c.response_time_ms).label("max_response_time_ms"),
            )

            row = session.execute(stmt).one()
            total = row.total_checks or 0
            if total == 0:
                return {
                    "total_checks": 0,
                    "uptime_percentage": 0.0,
                    "error_rate_percentage": 0.0,
                    "avg_response_time_ms": 0.0,
                    "avg_ttfb_ms": 0.0,
                    "avg_dns_time_ms": 0.0,
                    "min_response_time_ms": 0.0,
                    "max_response_time_ms": 0.0,
                }

            up = row.up_checks or 0
            uptime_pct = round((up / total) * 100, 2)
            error_rate_pct = round(((total - up) / total) * 100, 2)

            return {
                "total_checks": total,
                "uptime_percentage": uptime_pct,
                "error_rate_percentage": error_rate_pct,
                "avg_response_time_ms": round(row.avg_response_time_ms or 0.0, 2),
                "avg_ttfb_ms": round(row.avg_ttfb_ms or 0.0, 2),
                "avg_dns_time_ms": round(row.avg_dns_time_ms or 0.0, 2),
                "min_response_time_ms": round(row.min_response_time_ms or 0.0, 2),
                "max_response_time_ms": round(row.max_response_time_ms or 0.0, 2),
            }
