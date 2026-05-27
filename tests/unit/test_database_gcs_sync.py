"""
Tests for GCS sync observability in database.py — Theme 2.
Covers: GcsSyncStatus model, typed exception ladder, structured log lines,
_last_gcs_sync state updates for both download and upload.
"""
import logging
import os
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone
from database import (
    _download_db_from_gcs,
    _upload_db_to_gcs,
    get_last_gcs_sync,
    GcsSyncStatus,
    LOCAL_DB_PATH,
)


class TestGcsSyncStatus:
    """Test the GcsSyncStatus Pydantic model."""

    def test_basic_creation(self):
        status = GcsSyncStatus(
            op="download",
            started_at=datetime.now(timezone.utc),
            finished_at=datetime.now(timezone.utc),
            duration_ms=100,
            outcome="ok",
            bytes=1024,
            detail="test",
        )
        assert status.outcome == "ok"
        assert status.bytes == 1024

    def test_negative_duration_clamped(self):
        status = GcsSyncStatus(
            op="upload",
            started_at=datetime.now(timezone.utc),
            finished_at=datetime.now(timezone.utc),
            duration_ms=-5,
            outcome="ok",
        )
        assert status.duration_ms == 0

    def test_detail_truncation(self):
        long_detail = "x" * 600
        status = GcsSyncStatus(
            op="download",
            started_at=datetime.now(timezone.utc),
            finished_at=datetime.now(timezone.utc),
            duration_ms=0,
            outcome="ok",
            detail=long_detail,
        )
        assert len(status.detail) <= 500

    def test_to_log_string_format(self):
        status = GcsSyncStatus(
            op="download",
            started_at=datetime.now(timezone.utc),
            finished_at=datetime.now(timezone.utc),
            duration_ms=42,
            outcome="ok",
            bytes=512,
            detail="restored",
        )
        log_str = status.to_log_string()
        assert "GCS_SYNC" in log_str
        assert "op=download" in log_str
        assert "outcome=ok" in log_str
        assert "duration_ms=42" in log_str
        assert "bytes=512" in log_str


# ─────────────────────────────────────────────
# Download — parametrized over 8 outcomes
# ─────────────────────────────────────────────

@pytest.mark.parametrize("scenario, mock_setup, expected_outcome", [
    (
        "import_error",
        {"import_raises": ImportError("no module")},
        "import_error",
    ),
    (
        "ok_blob_exists",
        {"blob_exists": True, "file_size": 1024},
        "ok",
    ),
    (
        "skipped_no_blob",
        {"blob_exists": False},
        "skipped",
    ),
])
def test_download_db_outcomes(scenario, mock_setup, expected_outcome, caplog, tmp_path):
    """Test _download_db_from_gcs produces correct outcome for each scenario."""
    import database

    # Save and restore module state
    original_path = database.LOCAL_DB_PATH
    database.LOCAL_DB_PATH = str(tmp_path / "qa_bugbot.db")

    try:
        if "import_raises" in mock_setup:
            with patch.dict("sys.modules", {"google.cloud": None, "google.cloud.storage": None}):
                with caplog.at_level(logging.INFO, logger="qa_bugbot.database"):
                    status = _download_db_from_gcs()
        else:
            mock_storage = MagicMock()
            mock_blob = MagicMock()
            mock_blob.exists.return_value = mock_setup.get("blob_exists", False)
            if mock_setup.get("blob_exists"):
                def fake_download(path):
                    with open(path, "wb") as f:
                        f.write(b"x" * mock_setup.get("file_size", 100))
                mock_blob.download_to_filename.side_effect = fake_download
            mock_bucket = MagicMock()
            mock_bucket.blob.return_value = mock_blob
            mock_storage.Client.return_value.bucket.return_value = mock_bucket

            mock_auth = MagicMock()
            mock_auth.DefaultCredentialsError = type("DefaultCredentialsError", (Exception,), {})
            mock_gax = MagicMock()
            mock_gax.Forbidden = type("Forbidden", (Exception,), {})
            mock_gax.NotFound = type("NotFound", (Exception,), {})
            
            mock_cloud = MagicMock()
            mock_cloud.storage = mock_storage

            with patch.dict("sys.modules", {
                "google.cloud": mock_cloud,
                "google.cloud.storage": mock_storage,
                "google.api_core": MagicMock(),
                "google.api_core.exceptions": mock_gax,
                "google.auth": mock_auth,
                "google.auth.exceptions": mock_auth,
            }):
                with caplog.at_level(logging.INFO, logger="qa_bugbot.database"):
                    status = _download_db_from_gcs()

        assert status.outcome == expected_outcome, f"Scenario {scenario}: got {status.outcome}"
        assert status.op == "download"
        assert status.duration_ms >= 0
        # Check structured log line was emitted
        assert any("GCS_SYNC" in rec.message for rec in caplog.records), \
            f"Missing GCS_SYNC log for {scenario}"
        # Check _last_gcs_sync was updated
        assert get_last_gcs_sync() is not None
    finally:
        database.LOCAL_DB_PATH = original_path


# ─────────────────────────────────────────────
# Upload — key outcomes
# ─────────────────────────────────────────────

def test_upload_skipped_when_no_local_db(caplog, tmp_path):
    """Upload returns skipped when LOCAL_DB_PATH doesn't exist."""
    import database
    original = database.LOCAL_DB_PATH
    database.LOCAL_DB_PATH = str(tmp_path / "nonexistent.db")
    try:
        with caplog.at_level(logging.INFO, logger="qa_bugbot.database"):
            status = _upload_db_to_gcs()
        assert status.outcome == "skipped"
        assert status.op == "upload"
        assert any("GCS_SYNC" in rec.message for rec in caplog.records)
    finally:
        database.LOCAL_DB_PATH = original


def test_upload_import_error(caplog, tmp_path):
    """Upload returns import_error when google-cloud-storage is not installed."""
    import database
    original = database.LOCAL_DB_PATH
    db_path = str(tmp_path / "qa_bugbot.db")
    with open(db_path, "wb") as f:
        f.write(b"test data")
    database.LOCAL_DB_PATH = db_path
    try:
        with patch.dict("sys.modules", {"google.cloud": None, "google.cloud.storage": None}):
            with caplog.at_level(logging.INFO, logger="qa_bugbot.database"):
                status = _upload_db_to_gcs()
        assert status.outcome == "import_error"
        assert any("GCS_SYNC" in rec.message for rec in caplog.records)
    finally:
        database.LOCAL_DB_PATH = original
