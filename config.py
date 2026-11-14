"""Centralized Configuration Module for AIOps Anomaly Detection.

Uses pathlib for cross-platform path handling, resolving all paths relative
to the project root directory.
"""

from pathlib import Path

# Project metadata
PROJECT_NAME: str = "AIOps - Cloud Infrastructure Anomaly Detection"
PROJECT_VERSION: str = "0.1.0"
PROJECT_DESCRIPTION: str = (
    "AIOps solution for cloud infrastructure anomaly detection using "
    "Machine Learning."
)

# Project root directory resolved relative to this file
PROJECT_ROOT: Path = Path(__file__).resolve().parent

# Core project directories
DATA_DIR: Path = PROJECT_ROOT / "data"
RAW_DATA_DIR: Path = DATA_DIR / "raw"
PROCESSED_DATA_DIR: Path = DATA_DIR / "processed"

NOTEBOOKS_DIR: Path = PROJECT_ROOT / "notebooks"
SRC_DIR: Path = PROJECT_ROOT / "src"
API_DIR: Path = PROJECT_ROOT / "api"
DASHBOARD_DIR: Path = PROJECT_ROOT / "dashboard"
MODELS_DIR: Path = PROJECT_ROOT / "models"
LOGS_DIR: Path = PROJECT_ROOT / "logs"
TESTS_DIR: Path = PROJECT_ROOT / "tests"

# List of essential directories for validation and setup
PROJECT_DIRECTORIES: tuple[Path, ...] = (
    DATA_DIR,
    RAW_DATA_DIR,
    PROCESSED_DATA_DIR,
    NOTEBOOKS_DIR,
    SRC_DIR,
    API_DIR,
    DASHBOARD_DIR,
    MODELS_DIR,
    LOGS_DIR,
    TESTS_DIR,
)


def ensure_directories_exist() -> None:
    """Create essential project directories if they do not exist."""
    for directory in PROJECT_DIRECTORIES:
        directory.mkdir(parents=True, exist_ok=True)
