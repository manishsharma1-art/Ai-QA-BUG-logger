import pytest
import httpx
from datetime import datetime, timezone
from unittest.mock import patch

from database import GcsSyncStatus

@pytest.fixture
def mock_db_health():
    with patch("main.check_database_health", return_value=True) as mock:
        yield mock

@pytest.fixture
def mock_gemini_client():
    with patch("main.gemini_client", True):
        yield

@pytest.mark.asyncio
async def test_health_endpoint_healthy(mock_db_health, mock_gemini_client):
    from main import app
    import main
    main._build_marker = "test-marker-123"
    
    sync_status = GcsSyncStatus(
        op="download",
        started_at=datetime.now(timezone.utc).isoformat(),
        finished_at=datetime.now(timezone.utc).isoformat(),
        duration_ms=100,
        outcome="ok",
        bytes=1024,
        detail="Success"
    )
    
    with patch("database.get_last_gcs_sync", return_value=sync_status):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/health")
            
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "healthy"
            assert data["database"] == "connected"
            assert data["gemini"] == "configured"
            assert data["build_marker"] == "test-marker-123"
            assert data["last_gcs_sync"]["outcome"] == "ok"

@pytest.mark.asyncio
async def test_health_endpoint_degraded_due_to_db(mock_gemini_client):
    from main import app
    import main
    main._build_marker = "test-marker-123"
    
    sync_status = GcsSyncStatus(
        op="download",
        started_at=datetime.now(timezone.utc).isoformat(),
        finished_at=datetime.now(timezone.utc).isoformat(),
        duration_ms=100,
        outcome="ok",
        bytes=1024,
        detail="Success"
    )
    
    with patch("main.check_database_health", return_value=False):
        with patch("database.get_last_gcs_sync", return_value=sync_status):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                response = await client.get("/health")
                
                assert response.status_code == 200
                data = response.json()
                assert data["status"] == "degraded"
                assert data["database"] == "disconnected"

@pytest.mark.asyncio
async def test_health_endpoint_degraded_due_to_gcs_sync(mock_db_health, mock_gemini_client):
    from main import app
    import main
    main._build_marker = "test-marker-123"
    
    sync_status = GcsSyncStatus(
        op="download",
        started_at=datetime.now(timezone.utc).isoformat(),
        finished_at=datetime.now(timezone.utc).isoformat(),
        duration_ms=100,
        outcome="import_error",
        bytes=0,
        detail="No module named google"
    )
    
    with patch("database.get_last_gcs_sync", return_value=sync_status):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/health")
            
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "degraded"
            assert data["last_gcs_sync"]["outcome"] == "import_error"
