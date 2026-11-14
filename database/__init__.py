"""Database package for SQLite persistence and query operations."""

from database.db import (
    get_aggregate_stats,
    get_db,
    get_recent_checks,
    init_db,
    save_check_result,
)

__all__ = [
    "get_aggregate_stats",
    "get_db",
    "get_recent_checks",
    "init_db",
    "save_check_result",
]

