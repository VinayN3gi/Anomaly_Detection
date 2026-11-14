"""Main entry-point for AIOps Cloud Infrastructure Anomaly Detection.

Initializes and validates the project setup for Phase 1.
"""

import sys
from pathlib import Path

# Add project root to sys.path if not already present
project_root = Path(__file__).resolve().parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import config


def main() -> None:
    """Print project initialization information and directory structure."""
    print("=" * 70)
    print(f"Project Name   : {config.PROJECT_NAME}")
    print(f"Project Version: {config.PROJECT_VERSION}")
    print("=" * 70)
    print("Status: Project environment successfully initialized (Phase 1).")
    print("\nProject Directories:")
    print(f"  - Root Directory      : {config.PROJECT_ROOT}")
    print(f"  - Raw Data Directory  : {config.RAW_DATA_DIR}")
    print(f"  - Processed Data Dir  : {config.PROCESSED_DATA_DIR}")
    print(f"  - Model Directory     : {config.MODELS_DIR}")
    print(f"  - Notebooks Directory : {config.NOTEBOOKS_DIR}")
    print(f"  - Logs Directory      : {config.LOGS_DIR}")
    print(f"  - API Directory       : {config.API_DIR}")
    print(f"  - Dashboard Directory : {config.DASHBOARD_DIR}")
    print(f"  - Source Directory    : {config.SRC_DIR}")
    print(f"  - Tests Directory     : {config.TESTS_DIR}")
    print("=" * 70)


if __name__ == "__main__":
    main()

