"""
End-to-end registration persistence tests.

These pin the contract that registered users SHALL NOT be re-asked to
register after a deploy. They cover three failure modes:

1. happy-path round-trip: register -> simulated restart with mocked GCS ->
   user is still found (S6 from synthetic webhook scenarios).
2. fail-closed on download error: if _download_db_from_gcs returns an
   error outcome, _safe_upload_db_to_gcs MUST refuse to upload, so a
   fresh-empty local DB cannot wipe production registrations in GCS.
3. genuine empty bucket: outcome=skipped is treated as safe (first deploy
   ever), uploads proceed normally so the first registration is persisted.

Critical: these tests run against a temp SQLite DB, not the workspace one.
"""
from __future__ import annotations

import os
import shutil
import tempfile
from datetime import datetime, timezone
from typing import Tuple
from unittest.mock import MagicMock, patch

import pytest

import database


def _isolated_db(tmp_path) -> str:
    """Set up an isolated SQLite path under tmp_path."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    db_file = data_dir / "qa_bugbot.db"
    return str(db_file)


def _make_blob_with(content: bytes) -> MagicMock:
    """Build a fake GCS blob that returns `content` on download_to_filename."""
    blob = MagicMock()
    blob.exists.return_value = bool(content)

    def download(target_path):
        with open(target_path, "wb") as f:
            f.write(content)
    blob.download_to_filename.side_effect = download
    blob.upload_from_filename.return_value = None
    return blob


def _patch_storage(blob: MagicMock):
    """Return a patch context that replaces google.cloud.storage.Client with a fake."""
    fake_client = MagicMock()
    fake_bucket = MagicMock()
    fake_bucket.blob.return_value = blob
    fake_client.bucket.return_value = fake_bucket

    fake_module = MagicMock()
    fake_module.Client.return_value = fake_client

    return patch.dict("sys.modules", {"google.cloud.storage": fake_module})


@pytest.fixture(autouse=True)
def _reset_module_state(monkeypatch):
    """Reset database module's globals between tests."""
    yield
    database._engine = None
    database._session_factory = None
    database._uploads_safe = False
    database._last_gcs_sync = None


@pytest.mark.asyncio
async def test_S6_registration_survives_simulated_restart(tmp_path, monkeypatch):
    """
    Synthetic webhook scenario S6, properly executed:
    register a user -> upload to mocked GCS -> simulate cold start by
    re-initialising the module against the SAME GCS blob -> user must
    still be retrievable by chat_user_name.
    """
    db_path_a = _isolated_db(tmp_path / "instance_a")
    monkeypatch.setattr(database, "LOCAL_DB_PATH", db_path_a)

    # In-memory simulated bucket: a single bytes object both blobs share
    bucket_state = {"content": b""}

    def _fresh_blob() -> MagicMock:
        blob = MagicMock()
        blob.exists.side_effect = lambda: len(bucket_state["content"]) > 0
        def download(target):
            with open(target, "wb") as f:
                f.write(bucket_state["content"])
        def upload(source):
            with open(source, "rb") as f:
                bucket_state["content"] = f.read()
        blob.download_to_filename.side_effect = download
        blob.upload_from_filename.side_effect = upload
        return blob

    fake_module = MagicMock()
    fake_client = MagicMock()
    fake_bucket = MagicMock()
    fake_bucket.blob.side_effect = lambda *_args, **_kw: _fresh_blob()
    fake_client.bucket.return_value = fake_bucket
    fake_module.Client.return_value = fake_client

    with patch.dict("sys.modules", {"google.cloud.storage": fake_module}):
        # ── INSTANCE A ── empty bucket initially → outcome=skipped → uploads_safe=True
        await database.init_database(f"sqlite+aiosqlite:///{db_path_a}")
        assert database._uploads_safe, (
            "uploads must be safe after outcome=skipped (genuine empty bucket)"
        )
        await database.create_or_update_user(
            chat_user_name="users/123",
            chat_display_name="Alice",
            openproject_api_key="apikey-alice-original",
            openproject_user_id="42",
            openproject_user_name="Alice OP",
        )
        assert len(bucket_state["content"]) > 0, (
            "register must upload SQLite bytes to (mocked) GCS"
        )
        await database.close_database()

        # ── INSTANCE B (cold start) ──
        # Reset module state and use a NEW local path; init must restore from GCS.
        database._engine = None
        database._session_factory = None
        database._uploads_safe = False
        database._last_gcs_sync = None
        db_path_b = _isolated_db(tmp_path / "instance_b")
        monkeypatch.setattr(database, "LOCAL_DB_PATH", db_path_b)

        await database.init_database(f"sqlite+aiosqlite:///{db_path_b}")
        assert database._uploads_safe, (
            "uploads must be safe after outcome=ok (real restore)"
        )
        snap = database.get_last_gcs_sync()
        assert snap is not None and snap.outcome == "ok", (
            f"expected outcome=ok after restore, got {snap and snap.outcome!r}"
        )

        user = await database.get_user_by_chat_id("users/123")
        assert user is not None, "registered user lost after simulated restart"
        assert user.openproject_api_key == "apikey-alice-original"
        await database.close_database()


@pytest.mark.asyncio
async def test_upload_suppressed_when_download_failed(tmp_path, monkeypatch):
    """
    If init_database's download returns an error outcome, _safe_upload_db_to_gcs
    MUST refuse to upload — otherwise a fresh-empty local DB will overwrite the
    real registrations in GCS.
    """
    db_path = _isolated_db(tmp_path)
    monkeypatch.setattr(database, "LOCAL_DB_PATH", db_path)

    # Simulate: GCS library imports cleanly but Client() raises an auth error.
    fake_module = MagicMock()
    fake_module.Client.side_effect = OSError("simulated network blip")

    with patch.dict("sys.modules", {"google.cloud.storage": fake_module}):
        await database.init_database(f"sqlite+aiosqlite:///{db_path}")
        # download outcome should NOT be ok or skipped
        snap = database.get_last_gcs_sync()
        assert snap is not None
        assert snap.outcome not in ("ok", "skipped"), (
            f"test setup: download was supposed to fail, got outcome={snap.outcome!r}"
        )
        assert not database._uploads_safe, (
            "uploads must be locked-out after download error"
        )

        # Register a user — the per-registration upload must be suppressed
        await database.create_or_update_user(
            chat_user_name="users/999",
            chat_display_name="Bob",
            openproject_api_key="apikey-bob",
        )

        last = database.get_last_gcs_sync()
        assert last.op == "upload"
        assert last.outcome == "skipped", (
            f"expected suppressed upload (outcome=skipped), got {last.outcome!r}"
        )
        assert "upload suppressed" in last.detail, (
            f"detail should explain the suppression, got: {last.detail!r}"
        )
        await database.close_database()


@pytest.mark.asyncio
async def test_first_deploy_ever_can_persist(tmp_path, monkeypatch):
    """
    On the very first deploy ever, the GCS bucket has no qa_bugbot.db blob.
    download outcome=skipped MUST still allow uploads, otherwise the first
    user to register would be lost on every subsequent deploy.
    """
    db_path = _isolated_db(tmp_path)
    monkeypatch.setattr(database, "LOCAL_DB_PATH", db_path)

    bucket_state = {"content": b""}

    def _fresh_blob() -> MagicMock:
        blob = MagicMock()
        blob.exists.side_effect = lambda: len(bucket_state["content"]) > 0
        def download(target):
            with open(target, "wb") as f:
                f.write(bucket_state["content"])
        def upload(source):
            with open(source, "rb") as f:
                bucket_state["content"] = f.read()
        blob.download_to_filename.side_effect = download
        blob.upload_from_filename.side_effect = upload
        return blob

    fake_module = MagicMock()
    fake_client = MagicMock()
    fake_bucket = MagicMock()
    fake_bucket.blob.side_effect = lambda *_a, **_k: _fresh_blob()
    fake_client.bucket.return_value = fake_bucket
    fake_module.Client.return_value = fake_client

    with patch.dict("sys.modules", {"google.cloud.storage": fake_module}):
        await database.init_database(f"sqlite+aiosqlite:///{db_path}")
        snap = database.get_last_gcs_sync()
        assert snap is not None and snap.outcome == "skipped", (
            f"expected outcome=skipped on empty bucket, got {snap and snap.outcome!r}"
        )
        assert database._uploads_safe, (
            "uploads must be safe on outcome=skipped (genuine empty bucket)"
        )

        await database.create_or_update_user(
            chat_user_name="users/first",
            chat_display_name="First User",
            openproject_api_key="apikey-first",
        )
        # Upload must have actually written bytes to (mocked) GCS
        assert len(bucket_state["content"]) > 0
        last = database.get_last_gcs_sync()
        assert last.op == "upload" and last.outcome == "ok"
        await database.close_database()
