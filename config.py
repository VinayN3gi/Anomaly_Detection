"""Centralized Configuration Module for Universal Website Monitoring.

Uses pathlib for cross-platform path handling, resolving all paths relative
to the project root directory.
"""

import os
from pathlib import Path

# Project metadata
PROJECT_NAME: str = "AIOps - Universal Website Monitoring & Anomaly Detection"
PROJECT_VERSION: str = "0.3.0"
PROJECT_DESCRIPTION: str = (
    "Universal website monitoring platform with performance telemetry, "
    "uptime tracking, and future anomaly detection."
)

# Project root directory resolved relative to this file
PROJECT_ROOT: Path = Path(__file__).resolve().parent

# Core project directories
DATA_DIR: Path = PROJECT_ROOT / "data"
RAW_DATA_DIR: Path = DATA_DIR / "raw"
PROCESSED_DATA_DIR: Path = DATA_DIR / "processed"
VISUALIZATIONS_DIR: Path = DATA_DIR / "visualizations"
NOTEBOOKS_DIR: Path = PROJECT_ROOT / "notebooks"
LOGS_DIR: Path = PROJECT_ROOT / "logs"
MODELS_DIR: Path = PROJECT_ROOT / "models"
TESTS_DIR: Path = PROJECT_ROOT / "tests"

# Platform architecture directories
MONITORING_DIR: Path = PROJECT_ROOT / "monitoring"
SERVICES_DIR: Path = PROJECT_ROOT / "services"
DATABASE_DIR: Path = PROJECT_ROOT / "database"
SCHEDULER_DIR: Path = PROJECT_ROOT / "scheduler"
API_DIR: Path = PROJECT_ROOT / "api"
SCRIPTS_DIR: Path = PROJECT_ROOT / "scripts"
SRC_DIR: Path = PROJECT_ROOT / "src"

# Database path (SQLite)
DEFAULT_DB_PATH: Path = DATA_DIR / "monitoring.db"
DB_PATH: Path = Path(os.getenv("DATABASE_PATH", str(DEFAULT_DB_PATH)))

# Monitoring engine defaults
DEFAULT_CHECK_INTERVAL: int = int(os.getenv("DEFAULT_CHECK_INTERVAL", "60"))
REQUEST_TIMEOUT: float = float(os.getenv("REQUEST_TIMEOUT", "10.0"))
CONNECT_TIMEOUT: float = float(os.getenv("CONNECT_TIMEOUT", "5.0"))
MAX_REDIRECTS: int = int(os.getenv("MAX_REDIRECTS", "5"))
USER_AGENT: str = "AIOps-Website-Monitor/1.0 (+https://aiops-monitor.local)"

# Network and SSRF security restrictions
ALLOWED_SCHEMES: tuple[str, ...] = ("http", "https")
ALLOWED_PORTS: tuple[int, ...] = (80, 443, 8080, 8443)

# API Server defaults
API_HOST: str = os.getenv("API_HOST", "127.0.0.1")
API_PORT: int = int(os.getenv("API_PORT", "8000"))

# Essential project directories for validation and setup
PROJECT_DIRECTORIES: tuple[Path, ...] = (
    DATA_DIR,
    RAW_DATA_DIR,
    PROCESSED_DATA_DIR,
    NOTEBOOKS_DIR,
    LOGS_DIR,
    MODELS_DIR,
    TESTS_DIR,
    MONITORING_DIR,
    SERVICES_DIR,
    DATABASE_DIR,
    SCHEDULER_DIR,
    API_DIR,
)


def ensure_directories_exist() -> None:
    """Create essential project directories if they do not exist."""
    for directory in PROJECT_DIRECTORIES:
        directory.mkdir(parents=True, exist_ok=True)
