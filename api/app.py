"""FastAPI REST API for Universal Website Monitoring Platform.

Provides endpoints for registering websites, querying telemetry metrics,
retrieving uptime statistics, and triggering on-demand performance probes.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
import time
from typing import Any, AsyncGenerator

from fastapi import FastAPI, HTTPException, Query, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import config
from config.logging_config import get_logger, setup_logging
from database.db import get_aggregate_stats, init_db
from models.schemas import (
    CheckResultResponse,
    WebsiteCreate,
    WebsiteResponse,
    WebsiteStatsResponse,
    WebsiteUpdate,
)
from monitoring.security import SecurityValidationError
from scheduler.monitor_scheduler import MonitoringScheduler
from services.website_service import (
    WebsiteAlreadyExistsError,
    WebsiteNotFoundError,
    WebsiteService,
)

# Initialize structured logging
setup_logging(default_level=config.LOG_LEVEL, log_format=config.LOG_FORMAT)
logger = get_logger("aiops.api")

# Shared global service and scheduler instances
service = WebsiteService()
scheduler = MonitoringScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifecycle management for database and background scheduler."""
    logger.info("Initializing %s v%s...", config.PROJECT_NAME, config.PROJECT_VERSION)
    init_db()
    config.ensure_directories_exist()
    scheduler.start()
    logger.info("Background monitoring scheduler started successfully.")
    yield
    logger.info("Shutting down background monitoring scheduler...")
    await scheduler.stop()
    logger.info("Platform shutdown complete.")


app = FastAPI(
    title=config.PROJECT_NAME,
    version=config.PROJECT_VERSION,
    description=(
        "Universal Website Monitoring Platform: Continuously inspects uptime, "
        "TTFB, latency, DNS, and SSL metrics across any hosting provider."
    ),
    lifespan=lifespan,
)

# Enable permissive CORS for frontend/dashboard access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next: Any) -> Response:
    """Log incoming HTTP request details, execution duration, and status code."""
    start_time = time.perf_counter()
    method = request.method
    path = request.url.path
    client_ip = request.client.host if request.client else "unknown"

    try:
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
        logger.info(
            "%s %s %d - %.2fms (client=%s)",
            method,
            path,
            response.status_code,
            duration_ms,
            client_ip,
        )
        return response
    except Exception as exc:
        duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
        logger.exception(
            "Unhandled exception during %s %s after %.2fms: %s",
            method,
            path,
            duration_ms,
            exc,
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Internal server error occurred."},
        )


@app.get("/health", tags=["Health"])
async def health_check() -> dict[str, str]:
    """Health check endpoint to verify API and monitoring operational status."""
    return {
        "status": "healthy",
        "service": config.PROJECT_NAME,
        "version": config.PROJECT_VERSION,
    }


@app.post(
    "/api/v1/websites",
    response_model=WebsiteResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Websites"],
)
async def register_website(payload: WebsiteCreate) -> Any:
    """Register a new website for continuous monitoring with anti-SSRF verification."""
    try:
        logger.info("Registering website URL: %s", payload.url)
        created = await service.register_website(
            url=payload.url,
            name=payload.name,
            check_interval=payload.check_interval,
            perform_initial_check=True,
        )
        logger.info("Successfully registered website ID: %s", created.get("id"))
        return created
    except SecurityValidationError as exc:
        logger.warning("SSRF / security validation failed for %s: %s", payload.url, exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Security Validation Error: {exc}",
        ) from exc
    except WebsiteAlreadyExistsError as exc:
        logger.warning("Website already exists: %s", payload.url)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc


@app.get(
    "/api/v1/websites",
    response_model=list[WebsiteResponse],
    tags=["Websites"],
)
async def list_websites(
    active_only: bool = Query(False, description="Filter for active websites only")
) -> Any:
    """Retrieve all registered websites with their latest status and stats."""
    return service.list_websites(active_only=active_only)


@app.get(
    "/api/v1/websites/{website_id}",
    response_model=WebsiteResponse,
    tags=["Websites"],
)
async def get_website(website_id: int) -> Any:
    """Retrieve detailed metadata, latest check, and performance stats for a website."""
    try:
        return service.get_website(website_id)
    except WebsiteNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@app.patch(
    "/api/v1/websites/{website_id}",
    response_model=WebsiteResponse,
    tags=["Websites"],
)
async def update_website(website_id: int, payload: WebsiteUpdate) -> Any:
    """Update website name, monitoring check interval, or active status."""
    try:
        return service.update_website(
            website_id=website_id,
            name=payload.name,
            check_interval=payload.check_interval,
            is_active=payload.is_active,
        )
    except WebsiteNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@app.delete(
    "/api/v1/websites/{website_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Websites"],
)
async def delete_website(website_id: int) -> None:
    """Permanently delete a website and all associated historical metric records."""
    try:
        service.delete_website(website_id)
    except WebsiteNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@app.post(
    "/api/v1/websites/{website_id}/check",
    response_model=CheckResultResponse,
    tags=["Monitoring"],
)
async def trigger_manual_check(website_id: int) -> Any:
    """Execute an immediate, on-demand health and performance probe."""
    try:
        logger.info("Executing on-demand probe for website ID: %s", website_id)
        result = await service.trigger_check(website_id)
        return result.to_dict()
    except WebsiteNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@app.get(
    "/api/v1/websites/{website_id}/metrics",
    response_model=list[CheckResultResponse],
    tags=["Monitoring"],
)
async def get_website_metrics(
    website_id: int,
    limit: int = Query(50, ge=1, le=500, description="Maximum check records to return"),
) -> Any:
    """Retrieve historical check records and telemetry metrics for a website."""
    # Ensure website exists
    try:
        service.get_website(website_id)
    except WebsiteNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    return service.get_metrics_history(website_id, limit=limit)


@app.get(
    "/api/v1/websites/{website_id}/stats",
    response_model=WebsiteStatsResponse,
    tags=["Monitoring"],
)
async def get_website_statistics(website_id: int) -> Any:
    """Calculate aggregate uptime percentage, average response time, TTFB, and DNS."""
    try:
        site = service.get_website(website_id)
    except WebsiteNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    stats = get_aggregate_stats(website_id, db_path=service.db_path)
    stats["website_id"] = website_id
    stats["url"] = site["url"]
    return stats
