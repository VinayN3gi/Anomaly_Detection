"""Main entry-point for AIOps Universal Website Monitoring Platform.

Displays platform initialization status or launches the FastAPI API server
with integrated background monitoring scheduler.
"""

from __future__ import annotations

import argparse
import sys

import uvicorn

import config
from database.db import init_db


def main() -> None:
    """Print platform configuration status or launch server."""
    parser = argparse.ArgumentParser(
        description="AIOps Universal Website Monitoring & Anomaly Detection"
    )
    parser.add_argument(
        "--serve",
        action="store_true",
        help="Start the FastAPI web server and background monitoring scheduler.",
    )
    parser.add_argument(
        "--host",
        type=str,
        default=config.API_HOST,
        help=f"Host address to bind (default: {config.API_HOST}).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=config.API_PORT,
        help=f"Port to bind (default: {config.API_PORT}).",
    )
    args = parser.parse_args()

    config.ensure_directories_exist()
    init_db()

    banner = "=" * 75
    print(banner)
    print(f"Platform       : {config.PROJECT_NAME}")
    print(f"Version        : {config.PROJECT_VERSION}")
    print(f"Database Path  : {config.DB_PATH}")
    print(f"Check Interval : {config.DEFAULT_CHECK_INTERVAL} seconds (default)")
    print(banner)
    print("Status: Universal Website Monitoring Engine initialized successfully.")
    print("\nProject Architecture Directories:")
    print(f"  - Root Directory       : {config.PROJECT_ROOT}")
    print(f"  - Monitoring Engine    : {config.MONITORING_DIR}")
    print(f"  - Domain Services      : {config.SERVICES_DIR}")
    print(f"  - Database Layer       : {config.DATABASE_DIR}")
    print(f"  - Scheduler Layer      : {config.SCHEDULER_DIR}")
    print(f"  - REST API Layer       : {config.API_DIR}")
    print(f"  - Data Directory       : {config.DATA_DIR}")
    print(f"  - Test Suite           : {config.TESTS_DIR}")
    print(banner)

    if args.serve:
        print(f"\nLaunching FastAPI monitoring server on http://{args.host}:{args.port} ...")
        print("API Documentation available at: /docs and /redoc")
        uvicorn.run("api.app:app", host=args.host, port=args.port, reload=False)
    else:
        print("\nTip: To start the API server and continuous background scheduler, run:")
        print("  python main.py --serve")
        print("  or: uvicorn api.app:app --host 127.0.0.1 --port 8000\n")


if __name__ == "__main__":
    main()
