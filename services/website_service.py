"""Website Management and Monitoring Service.

Orchestrates URL registration, security vetting, on-demand probing,
and SQLite persistence operations.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sqlite3

from database.db import (
    get_aggregate_stats,
    get_db,
    get_recent_checks,
    save_check_result,
)
from monitoring.engine import WebsiteCheckResult, check_website_async
from monitoring.security import validate_url_security


class WebsiteNotFoundError(Exception):
    """Raised when a website record does not exist."""

    pass


class WebsiteAlreadyExistsError(Exception):
    """Raised when registering a URL that is already monitored."""

    pass


class WebsiteService:
    """Core domain service for managing monitored websites."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self.db_path = db_path

    async def register_website(
        self,
        url: str,
        name: str | None = None,
        check_interval: int = 60,
        perform_initial_check: bool = True,
    ) -> dict:
        """Validate, register, and optionally execute an immediate probe.

        Args:
            url: Target website URL.
            name: Optional display name.
            check_interval: Monitoring frequency in seconds.
            perform_initial_check: Whether to immediately probe website upon registration.

        Returns:
            Dictionary containing registered website and initial check telemetry.
        """
        # Validate security and anti-SSRF rules
        normalized_url, _, _ = validate_url_security(url)

        now_iso = datetime.now(timezone.utc).isoformat()
        display_name = name.strip() if name and name.strip() else normalized_url

        query = """
        INSERT INTO websites (url, name, check_interval, is_active, created_at, updated_at)
        VALUES (?, ?, ?, 1, ?, ?);
        """
        try:
            with get_db(self.db_path) as conn:
                cursor = conn.execute(
                    query,
                    (normalized_url, display_name, check_interval, now_iso, now_iso),
                )
                website_id = cursor.lastrowid
        except sqlite3.IntegrityError as exc:
            raise WebsiteAlreadyExistsError(
                f"Website '{normalized_url}' is already registered for monitoring."
            ) from exc

        latest_check_dict = None
        if perform_initial_check and website_id is not None:
            check_res = await check_website_async(normalized_url)
            save_check_result(website_id, check_res, db_path=self.db_path)
            latest_check_dict = check_res.to_dict()

        return {
            "id": website_id,
            "url": normalized_url,
            "name": display_name,
            "check_interval": check_interval,
            "is_active": True,
            "created_at": now_iso,
            "updated_at": now_iso,
            "latest_check": latest_check_dict,
        }

    def get_website(self, website_id: int) -> dict:
        """Fetch a website by primary key ID along with latest check and summary stats."""
        query = "SELECT * FROM websites WHERE id = ?;"
        with get_db(self.db_path) as conn:
            row = conn.execute(query, (website_id,)).fetchone()
            if not row:
                raise WebsiteNotFoundError(f"Website with ID {website_id} not found.")
            data = dict(row)

        data["is_active"] = bool(data["is_active"])
        recent = get_recent_checks(website_id, limit=1, db_path=self.db_path)
        data["latest_check"] = recent[0] if recent else None
        data["stats"] = get_aggregate_stats(website_id, limit=100, db_path=self.db_path)
        return data

    def list_websites(self, active_only: bool = False) -> list[dict]:
        """Retrieve all monitored websites along with their most recent status."""
        query = "SELECT * FROM websites"
        if active_only:
            query += " WHERE is_active = 1"
        query += " ORDER BY id ASC;"

        with get_db(self.db_path) as conn:
            rows = conn.execute(query).fetchall()

        results: list[dict] = []
        for r in rows:
            w_dict = dict(r)
            w_dict["is_active"] = bool(w_dict["is_active"])
            recent = get_recent_checks(w_dict["id"], limit=1, db_path=self.db_path)
            w_dict["latest_check"] = recent[0] if recent else None
            w_dict["stats"] = get_aggregate_stats(
                w_dict["id"], limit=50, db_path=self.db_path
            )
            results.append(w_dict)

        return results

    def update_website(
        self,
        website_id: int,
        name: str | None = None,
        check_interval: int | None = None,
        is_active: bool | None = None,
    ) -> dict:
        """Update website metadata or monitoring schedule."""
        self.get_website(website_id)  # Validate existence

        updates: list[str] = []
        params: list = []

        if name is not None:
            updates.append("name = ?")
            params.append(name.strip())
        if check_interval is not None:
            updates.append("check_interval = ?")
            params.append(check_interval)
        if is_active is not None:
            updates.append("is_active = ?")
            params.append(1 if is_active else 0)

        if updates:
            updates.append("updated_at = ?")
            params.append(datetime.now(timezone.utc).isoformat())
            params.append(website_id)

            query = f"UPDATE websites SET {', '.join(updates)} WHERE id = ?;"
            with get_db(self.db_path) as conn:
                conn.execute(query, tuple(params))

        return self.get_website(website_id)

    def delete_website(self, website_id: int) -> bool:
        """Remove a website and cascade delete its historical metrics."""
        self.get_website(website_id)  # Validate existence
        query = "DELETE FROM websites WHERE id = ?;"
        with get_db(self.db_path) as conn:
            conn.execute(query, (website_id,))
        return True

    async def trigger_check(self, website_id: int) -> WebsiteCheckResult:
        """Trigger an immediate monitoring check and record metrics."""
        website = self.get_website(website_id)
        result = await check_website_async(website["url"])
        save_check_result(website_id, result, db_path=self.db_path)
        return result

    def get_metrics_history(self, website_id: int, limit: int = 50) -> list[dict]:
        """Fetch historical monitoring checks for telemetry graphs or analysis."""
        self.get_website(website_id)  # Validate existence
        return get_recent_checks(website_id, limit=limit, db_path=self.db_path)
