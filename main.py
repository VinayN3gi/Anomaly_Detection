"""Main entry-point for AIOps Website Monitoring & Anomaly Detection Platform.

Displays platform initialization status or launches the FastAPI API server
with integrated background monitoring scheduler.
"""

from __future__ import annotations

import argparse

import uvicorn

import config
from config.logging_config import get_logger, setup_logging
from database.db import init_db


def main() -> None:
    """Print platform configuration status or launch server."""
    parser = argparse.ArgumentParser(
        description="AIOps Website Monitoring & Anomaly Detection Platform"
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

    setup_logging(default_level=config.LOG_LEVEL, log_format=config.LOG_FORMAT)
    logger = get_logger("aiops.main")

    config.ensure_directories_exist()
    init_db()

    banner = "=" * 78
    print(banner)
    print(f"Platform       : {config.PROJECT_NAME}")
    print(f"Version        : {config.PROJECT_VERSION}")
    print(f"Database Path  : {config.DB_PATH}")
    print(f"Database URL   : {config.DATABASE_URL}")
    print(f"Check Interval : {config.DEFAULT_CHECK_INTERVAL} seconds (default)")
    print(banner)
    print("Status: Universal Website Monitoring Engine initialized successfully.")
    print("\nProject Architecture Directories:")
    print(f"  - Root Directory         : {config.PROJECT_ROOT}")
    print(f"  - Monitoring Engine      : {config.MONITORING_DIR}")
    print(f"  - Domain Services        : {config.SERVICES_DIR}")
    print(f"  - Database Layer         : {config.DATABASE_DIR}")
    print(f"  - Scheduler Layer        : {config.SCHEDULER_DIR}")
    print(f"  - REST API Layer         : {config.API_DIR}")
    print(f"  - Anomaly Detection      : {config.ANOMALY_DETECTION_DIR}")
    print(f"  - Alerting System        : {config.ALERTING_DIR}")
    print(f"  - Configuration & Logs   : {config.CONFIG_DIR} / {config.LOGS_DIR}")
    print(f"  - Data Directory         : {config.DATA_DIR}")
    print(f"  - Test Suite             : {config.TESTS_DIR}")
    print(banner)

    if args.serve:
        logger.info(
            "Launching FastAPI monitoring server on http://%s:%s ...",
            args.host,
            args.port,
        )
        print(f"\nLaunching FastAPI server on http://{args.host}:{args.port} ...")
        print("API Documentation available at: /docs and /redoc")
        uvicorn.run("api.app:app", host=args.host, port=args.port, reload=False)
    else:
        print(
            "\nTip: To start the API server and continuous background scheduler, run:"
        )
        print("  python main.py --serve")
        print("  or: uvicorn api.app:app --host 127.0.0.1 --port 8000\n")


if __name__ == "__main__":
    main()
