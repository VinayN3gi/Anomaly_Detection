"""FastAPI REST API for Universal Website Monitoring Platform.

Provides endpoints for registering websites, querying telemetry metrics,
retrieving uptime statistics, and triggering on-demand performance probes.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

from fastapi import FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware

import config
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

# Shared global service and scheduler instances
service = WebsiteService()
scheduler = MonitoringScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifecycle management for database and background scheduler."""
    # Startup: Ensure database schema exists and start scheduler
    init_db()
    config.ensure_directories_exist()
    scheduler.start()
    yield
    # Shutdown: Cleanly cancel background scheduler
    await scheduler.stop()


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
        created = await service.register_website(
            url=payload.url,
            name=payload.name,
            check_interval=payload.check_interval,
            perform_initial_check=True,
        )
        return created
    except SecurityValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Security Validation Error: {exc}",
        ) from exc
    except WebsiteAlreadyExistsError as exc:
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
    """Update website name, interval, or active monitoring status."""
    try:
        return service.update_website(
            website_id,
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
    """Delete a monitored website and all associated telemetry metrics."""
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
async def trigger_website_check(website_id: int) -> Any:
    """Trigger an immediate real-time monitoring probe for a specific website."""
    try:
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
    limit: int = Query(50, ge=1, le=500, description="Max check records to return"),
) -> Any:
    """Retrieve historical time-series metrics for a registered website."""
    try:
        return service.get_metrics_history(website_id, limit=limit)
    except WebsiteNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@app.get(
    "/api/v1/websites/{website_id}/stats",
    response_model=WebsiteStatsResponse,
    tags=["Monitoring"],
)
async def get_website_stats(
    website_id: int,
    limit: int = Query(100, ge=1, le=1000, description="Sample size of checks to aggregate"),
) -> Any:
    """Retrieve aggregated uptime percentage, error rate, and response latency statistics."""
    try:
        site = service.get_website(website_id)
        stats = get_aggregate_stats(website_id, limit=limit, db_path=service.db_path)
        return {
            "website_id": website_id,
            "url": site["url"],
            **stats,
        }
    except WebsiteNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
