"""Integration tests for FastAPI REST endpoints."""

from pathlib import Path
from unittest.mock import patch
import httpx
import pytest
from fastapi.testclient import TestClient

from api.app import app, service, scheduler
from database.db import init_db
from monitoring.engine import WebsiteCheckResult


@pytest.fixture(autouse=True)
def setup_test_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Configure isolated database and mocked network for API tests."""
    db_file = tmp_path / "api_test.db"
    init_db(db_file)
    service.db_path = db_file
    scheduler.db_path = db_file

    # Mock DNS resolution to public IP
    monkeypatch.setattr(
        "monitoring.security.resolve_and_validate_hostname",
        lambda host: ["93.184.216.34"],
    )
    # Mock probe to return fast synthetic response
    mock_result = WebsiteCheckResult(
        url="https://example.com/",
        timestamp="2026-03-01T12:00:00Z",
        is_up=True,
        status="UP",
        http_status_code=200,
        response_time_ms=42.0,
        ttfb_ms=28.0,
        dns_time_ms=7.0,
        ssl_valid=True,
        ssl_expiry_date="2027-01-01T00:00:00Z",
        ssl_days_remaining=300,
        response_size_bytes=1024,
        redirect_count=0,
        resolved_ip="93.184.216.34",
        error_message=None,
    )
    monkeypatch.setattr(
        "monitoring.engine.check_website_async",
        lambda *args, **kwargs: pytest.importorskip("asyncio").sleep(0, result=mock_result),
    )


@pytest.fixture
def client() -> TestClient:
    """Create test client without background scheduler thread contention."""
    with patch.object(scheduler, "start", return_value=None):
        with TestClient(app) as test_client:
            yield test_client


class TestAPIEndpoints:
    """Validate REST API functionality, validation, and error reporting."""

    def test_health_check(self, client: TestClient) -> None:
        """Verify health check endpoint returns 200."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "version" in data

    def test_register_website_success(self, client: TestClient) -> None:
        """Verify successful website registration with initial check recorded."""
        payload = {
            "url": "https://example.com",
            "name": "Production Example",
            "check_interval": 60,
        }
        response = client.post("/api/v1/websites", json=payload)
        assert response.status_code == 201
        data = response.json()
        assert data["url"] == "https://example.com/"
        assert data["name"] == "Production Example"
        assert data["check_interval"] == 60
        assert data["is_active"] is True
        assert data["latest_check"] is not None
        assert data["latest_check"]["is_up"] is True

    def test_register_website_ssrf_blocked(self, client: TestClient) -> None:
        """Verify registering localhost or private IP returns HTTP 400."""
        payload = {"url": "http://127.0.0.1:8080/admin"}
        response = client.post("/api/v1/websites", json=payload)
        assert response.status_code == 400
        assert "Security Validation Error" in response.json()["detail"]

    def test_duplicate_registration_returns_409(self, client: TestClient) -> None:
        """Verify registering existing URL raises conflict error."""
        payload = {"url": "https://example.com"}
        r1 = client.post("/api/v1/websites", json=payload)
        assert r1.status_code == 201

        r2 = client.post("/api/v1/websites", json=payload)
        assert r2.status_code == 409
        assert "already registered" in r2.json()["detail"]

    def test_list_and_get_websites(self, client: TestClient) -> None:
        """Verify listing and detail retrieval."""
        client.post("/api/v1/websites", json={"url": "https://site-a.com"})
        client.post("/api/v1/websites", json={"url": "https://site-b.com"})

        list_resp = client.get("/api/v1/websites")
        assert list_resp.status_code == 200
        sites = list_resp.json()
        assert len(sites) == 2

        detail_resp = client.get(f"/api/v1/websites/{sites[0]['id']}")
        assert detail_resp.status_code == 200
        detail = detail_resp.json()
        assert detail["id"] == sites[0]["id"]
        assert "stats" in detail

    def test_get_nonexistent_website_returns_404(self, client: TestClient) -> None:
        """Verify 404 for invalid ID."""
        response = client.get("/api/v1/websites/99999")
        assert response.status_code == 404

    def test_trigger_on_demand_check(self, client: TestClient) -> None:
        """Verify manual check trigger endpoint."""
        reg_resp = client.post("/api/v1/websites", json={"url": "https://check-now.com"})
        site_id = reg_resp.json()["id"]

        check_resp = client.post(f"/api/v1/websites/{site_id}/check")
        assert check_resp.status_code == 200
        check_data = check_resp.json()
        assert check_data["status"] == "UP"
        assert check_data["response_time_ms"] > 0

    def test_get_website_metrics_and_stats(self, client: TestClient) -> None:
        """Verify history and aggregate stats endpoints."""
        reg_resp = client.post("/api/v1/websites", json={"url": "https://metrics.com"})
        site_id = reg_resp.json()["id"]

        # Trigger additional check
        client.post(f"/api/v1/websites/{site_id}/check")

        metrics_resp = client.get(f"/api/v1/websites/{site_id}/metrics")
        assert metrics_resp.status_code == 200
        metrics = metrics_resp.json()
        assert len(metrics) >= 2

        stats_resp = client.get(f"/api/v1/websites/{site_id}/stats")
        assert stats_resp.status_code == 200
        stats = stats_resp.json()
        assert stats["total_checks"] >= 2
        assert stats["uptime_percentage"] == 100.0

    def test_delete_website(self, client: TestClient) -> None:
        """Verify website deletion endpoint returns 204."""
        reg_resp = client.post("/api/v1/websites", json={"url": "https://delete-me.com"})
        site_id = reg_resp.json()["id"]

        del_resp = client.delete(f"/api/v1/websites/{site_id}")
        assert del_resp.status_code == 204

        # Confirm deleted
        get_resp = client.get(f"/api/v1/websites/{site_id}")
        assert get_resp.status_code == 404

