"""SQLite Database Layer for Universal Website Monitoring.

Provides persistent storage, connection pooling conventions, and schema
management for registered websites and time-series monitoring metrics.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sqlite3
from typing import Generator

import config
from monitoring.engine import WebsiteCheckResult


SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS websites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT UNIQUE NOT NULL,
    name TEXT,
    check_interval INTEGER NOT NULL DEFAULT 60,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS monitoring_checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    website_id INTEGER NOT NULL,
    timestamp TEXT NOT NULL,
    is_up INTEGER NOT NULL,
    status TEXT NOT NULL,
    http_status_code INTEGER,
    response_time_ms REAL NOT NULL,
    ttfb_ms REAL NOT NULL,
    dns_time_ms REAL NOT NULL,
    ssl_valid INTEGER,
    ssl_expiry_date TEXT,
    ssl_days_remaining INTEGER,
    response_size_bytes INTEGER NOT NULL,
    redirect_count INTEGER NOT NULL DEFAULT 0,
    resolved_ip TEXT,
    error_message TEXT,
    FOREIGN KEY (website_id) REFERENCES websites(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_checks_website_time
ON monitoring_checks(website_id, timestamp DESC);
"""


def get_db_path(custom_path: Path | str | None = None) -> Path:
    """Resolve database location."""
    if custom_path is not None:
        return Path(custom_path)
    return config.DB_PATH


def init_db(db_path: Path | str | None = None) -> Path:
    """Initialize database schema, tables, and indexes."""
    target_path = get_db_path(db_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(target_path) as conn:
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.executescript(SCHEMA_SQL)
        conn.commit()

    return target_path


@contextmanager
def get_db(db_path: Path | str | None = None) -> Generator[sqlite3.Connection, None, None]:
    """Context manager yielding SQLite connection configured with row factory."""
    target_path = get_db_path(db_path)
    conn = sqlite3.connect(target_path, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def save_check_result(
    website_id: int,
    result: WebsiteCheckResult,
    db_path: Path | str | None = None,
) -> int:
    """Persist an individual monitoring check result to SQLite.

    Args:
        website_id: Foreign key ID of registered website.
        result: WebsiteCheckResult object.
        db_path: Optional custom database path.

    Returns:
        Generated primary key check ID.
    """
    query = """
    INSERT INTO monitoring_checks (
        website_id, timestamp, is_up, status, http_status_code,
        response_time_ms, ttfb_ms, dns_time_ms, ssl_valid,
        ssl_expiry_date, ssl_days_remaining, response_size_bytes,
        redirect_count, resolved_ip, error_message
    ) VALUES (
        ?, ?, ?, ?, ?,
        ?, ?, ?, ?,
        ?, ?, ?,
        ?, ?, ?
    );
    """
    with get_db(db_path) as conn:
        cursor = conn.execute(
            query,
            (
                website_id,
                result.timestamp,
                1 if result.is_up else 0,
                result.status,
                result.http_status_code,
                result.response_time_ms,
                result.ttfb_ms,
                result.dns_time_ms,
                None if result.ssl_valid is None else (1 if result.ssl_valid else 0),
                result.ssl_expiry_date,
                result.ssl_days_remaining,
                result.response_size_bytes,
                result.redirect_count,
                result.resolved_ip,
                result.error_message,
            ),
        )
        return cursor.lastrowid or 0


def get_recent_checks(
    website_id: int,
    limit: int = 50,
    db_path: Path | str | None = None,
) -> list[dict]:
    """Retrieve recent check records for a website in reverse chronological order."""
    query = """
    SELECT * FROM monitoring_checks
    WHERE website_id = ?
    ORDER BY timestamp DESC
    LIMIT ?;
    """
    with get_db(db_path) as conn:
        rows = conn.execute(query, (website_id, limit)).fetchall()
        return [dict(r) for r in rows]


def get_aggregate_stats(
    website_id: int,
    limit: int = 100,
    db_path: Path | str | None = None,
) -> dict:
    """Compute uptime percentage, error rate, and average latency over recent checks."""
    query = """
    SELECT
        COUNT(*) as total_checks,
        SUM(is_up) as up_checks,
        AVG(response_time_ms) as avg_response_time_ms,
        AVG(ttfb_ms) as avg_ttfb_ms,
        AVG(dns_time_ms) as avg_dns_time_ms,
        MIN(response_time_ms) as min_response_time_ms,
        MAX(response_time_ms) as max_response_time_ms
    FROM (
        SELECT is_up, response_time_ms, ttfb_ms, dns_time_ms
        FROM monitoring_checks
        WHERE website_id = ?
        ORDER BY timestamp DESC
        LIMIT ?
    );
    """
    with get_db(db_path) as conn:
        row = conn.execute(query, (website_id, limit)).fetchone()
        if not row or row["total_checks"] == 0:
            return {
                "total_checks": 0,
                "uptime_percentage": 0.0,
                "error_rate_percentage": 0.0,
                "avg_response_time_ms": 0.0,
                "avg_ttfb_ms": 0.0,
                "avg_dns_time_ms": 0.0,
            }

        total = row["total_checks"]
        up = row["up_checks"] or 0
        uptime_pct = round((up / total) * 100, 2)
        error_rate_pct = round(((total - up) / total) * 100, 2)

        return {
            "total_checks": total,
            "uptime_percentage": uptime_pct,
            "error_rate_percentage": error_rate_pct,
            "avg_response_time_ms": round(row["avg_response_time_ms"] or 0.0, 2),
            "avg_ttfb_ms": round(row["avg_ttfb_ms"] or 0.0, 2),
            "avg_dns_time_ms": round(row["avg_dns_time_ms"] or 0.0, 2),
            "min_response_time_ms": round(row["min_response_time_ms"] or 0.0, 2),
            "max_response_time_ms": round(row["max_response_time_ms"] or 0.0, 2),
        }

