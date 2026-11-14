"""Database Package for Website Monitoring.

Provides persistent SQLite and TimescaleDB / PostgreSQL storage,
SQLAlchemy ORM models, and the MonitoringRepository abstraction.
"""

from database.db import (
    get_aggregate_stats,
    get_db,
    get_recent_checks,
    init_db,
    save_check_result,
)
from database.models import Base, MonitoringResult, Website
from database.repository import (
    MonitoringRepository,
    WebsiteAlreadyExistsError,
    WebsiteNotFoundError,
)

__all__ = [
    "Base",
    "Website",
    "MonitoringResult",
    "MonitoringRepository",
    "WebsiteNotFoundError",
    "WebsiteAlreadyExistsError",
    "init_db",
    "get_db",
    "save_check_result",
    "get_recent_checks",
    "get_aggregate_stats",
]
