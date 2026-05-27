"""
Async SQLite database setup and CRUD operations for user registration.
Uses SQLAlchemy async with aiosqlite.
Table name: tester_registrations (matches deployed version).

PERSISTENCE: DB file is synced to/from Google Cloud Storage (gs://qa-bugbot-data/)
so registrations survive container restarts and new deployments.
"""

import os
import logging
from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, field_validator
from sqlalchemy import Column, Integer, String, DateTime, Text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base

logger = logging.getLogger("qa_bugbot.database")

# GCS bucket for persistent DB storage
GCS_DB_BUCKET = "gs://qa-bugbot-data/qa_bugbot.db"
LOCAL_DB_PATH = "./data/qa_bugbot.db"


# ─────────────────────────────────────────────
# GCS sync status model (Theme 2 — observability)
# ─────────────────────────────────────────────

class GcsSyncStatus(BaseModel):
    """Snapshot of the most recent GCS sync attempt; exposed via /health."""
    op: Literal["download", "upload"]
    started_at: datetime
    finished_at: datetime
    duration_ms: int
    outcome: Literal[
        "ok", "skipped", "import_error", "auth_error",
        "forbidden", "not_found", "network_error", "unknown_error",
    ]
    bytes: int = 0
    detail: str = ""

    @field_validator("duration_ms")
    @classmethod
    def _ms_nonneg(cls, v: int) -> int:
        return max(0, v)

    @field_validator("bytes")
    @classmethod
    def _bytes_nonneg(cls, v: int) -> int:
        return max(0, v)

    @field_validator("detail")
    @classmethod
    def _truncate_detail(cls, v: str) -> str:
        if v and len(v) > 500:
            return v[:497] + "..."
        return v

    def to_log_string(self) -> str:
        """Serialize to the structured log line format used by /logs."""
        # Escape any embedded double-quotes in detail
        safe_detail = self.detail.replace('"', '\\"')
        return (
            f"GCS_SYNC op={self.op} outcome={self.outcome} "
            f"duration_ms={self.duration_ms} bytes={self.bytes} "
            f'detail="{safe_detail}"'
        )


# Module-level state — most recent GCS sync attempt snapshot.
# Set by _download_db_from_gcs() and _upload_db_to_gcs() (Theme 2 / tasks 5.3, 5.4).
# Surfaced through /health.last_gcs_sync (task 8.2).
_last_gcs_sync: Optional[GcsSyncStatus] = None


# Registration-loss safeguard (added after QA-audit feedback):
# Uploads are only safe if the most recent download succeeded (outcome=ok)
# or proved the bucket was genuinely empty (outcome=skipped). On any error
# outcome (auth_error, forbidden, network_error, unknown_error, import_error)
# the local DB is presumed to be a freshly-created empty stand-in and uploading
# it would WIPE THE PRODUCTION REGISTRATIONS in GCS.
#
# Set to True only after a successful or skipped download.
_uploads_safe: bool = False


def _safe_upload_db_to_gcs() -> GcsSyncStatus:
    """
    Guarded wrapper around _upload_db_to_gcs.

    If the last download failed (i.e. we have no proof the local DB was
    restored from GCS), refuse to upload. This protects existing
    registrations from being clobbered by a fresh empty DB after a transient
    download failure on cold start.

    Returns a synthetic GcsSyncStatus with outcome='skipped' and a
    descriptive detail when the upload is suppressed; otherwise delegates
    to _upload_db_to_gcs.
    """
    global _last_gcs_sync
    if not _uploads_safe:
        started_at = datetime.now(timezone.utc)
        finished_at = started_at
        status = GcsSyncStatus(
            op="upload",
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=0,
            outcome="skipped",
            bytes=0,
            detail=(
                "upload suppressed: previous download did not succeed "
                "(refusing to overwrite GCS with possibly-empty local DB)"
            ),
        )
        logger.warning(status.to_log_string())
        _last_gcs_sync = status
        return status
    return _upload_db_to_gcs()


def get_last_gcs_sync() -> Optional[GcsSyncStatus]:
    """Return the most recent GcsSyncStatus snapshot (or None if no sync attempted yet)."""
    return _last_gcs_sync


Base = declarative_base()


def _download_db_from_gcs() -> GcsSyncStatus:
    """
    Pull qa_bugbot.db from gs://qa-bugbot-data/.

    Preconditions:
      - LOCAL_DB_PATH parent directory is writable (created by caller if missing).
      - Either ADC is configured (Cloud Run injects this) or GOOGLE_APPLICATION_CREDENTIALS
        points to a valid service-account JSON.

    Postconditions:
      - On 'ok'    : LOCAL_DB_PATH exists and is a valid SQLite file.
      - On 'skipped': blob does not exist in GCS; LOCAL_DB_PATH is left untouched
                      (fresh start is allowed).
      - On any error outcome: LOCAL_DB_PATH may not exist. Caller MUST tolerate this
                              and let SQLAlchemy create a fresh DB.
      - Always returns a GcsSyncStatus and updates module-level _last_gcs_sync.
      - Always emits exactly one structured log line of the form:
          GCS_SYNC op=download outcome=<outcome> duration_ms=<n> bytes=<n> detail="..."

    Never re-raises.
    """
    global _last_gcs_sync
    started_at = datetime.now(timezone.utc)
    outcome: str = "unknown_error"
    detail: str = ""
    blob_size: int = 0

    # Step 1: Try to import the GCS library (separate try so ImportError gets its own outcome)
    try:
        from google.cloud import storage  # type: ignore[import-untyped]
    except ImportError as e:
        outcome = "import_error"
        detail = f"google-cloud-storage not importable: {e}"
        finished_at = datetime.now(timezone.utc)
        duration_ms = int((finished_at - started_at).total_seconds() * 1000)
        status = GcsSyncStatus(
            op="download", started_at=started_at, finished_at=finished_at,
            duration_ms=duration_ms, outcome=outcome, bytes=blob_size, detail=detail,
        )
        logger.info(status.to_log_string())
        _last_gcs_sync = status
        return status

    # Step 2: Try to do the actual download
    try:
        # Lazy import of typed exception classes
        try:
            from google.api_core import exceptions as gax  # type: ignore[import-untyped]
        except ImportError:
            gax = None
        try:
            from google.auth import exceptions as gauth  # type: ignore[import-untyped]
        except ImportError:
            gauth = None

        client = storage.Client()
        bucket = client.bucket("qa-bugbot-data")
        blob = bucket.blob("qa_bugbot.db")

        if not blob.exists():
            outcome = "skipped"
            detail = "no existing DB in GCS — starting fresh"
        else:
            os.makedirs(os.path.dirname(LOCAL_DB_PATH), exist_ok=True)
            blob.download_to_filename(LOCAL_DB_PATH)
            outcome = "ok"
            blob_size = os.path.getsize(LOCAL_DB_PATH)
            detail = "restored from GCS"
    except Exception as e:
        cls_name = type(e).__name__
        # Typed-exception classification
        if 'gauth' in dir() and gauth is not None and isinstance(e, gauth.DefaultCredentialsError):
            outcome = "auth_error"
            detail = f"no ADC available: {e}"
        elif 'gax' in dir() and gax is not None and isinstance(e, gax.Forbidden):
            outcome = "forbidden"
            detail = f"service account lacks objectAdmin: {e}"
        elif 'gax' in dir() and gax is not None and isinstance(e, gax.NotFound):
            outcome = "not_found"
            detail = f"bucket or blob missing: {e}"
        elif isinstance(e, (TimeoutError, ConnectionError, OSError)):
            outcome = "network_error"
            detail = f"{cls_name}: {e}"
        else:
            outcome = "unknown_error"
            detail = f"{cls_name}: {e}"

    # Step 3: Finalize
    finished_at = datetime.now(timezone.utc)
    duration_ms = int((finished_at - started_at).total_seconds() * 1000)
    status = GcsSyncStatus(
        op="download",
        started_at=started_at,
        finished_at=finished_at,
        duration_ms=duration_ms,
        outcome=outcome,
        bytes=blob_size,
        detail=detail,
    )
    logger.info(status.to_log_string())
    _last_gcs_sync = status
    return status


def _upload_db_to_gcs() -> GcsSyncStatus:
    """
    Push the local SQLite DB to gs://qa-bugbot-data/qa_bugbot.db.

    Postconditions:
      - On 'ok'    : blob updated with current local DB content.
      - On 'skipped': LOCAL_DB_PATH does not exist (nothing to upload yet).
      - On any error outcome: blob may be stale. Caller MUST tolerate this and
                              expect the next successful upload to recover.
      - Always returns a GcsSyncStatus and updates module-level _last_gcs_sync.
      - Always emits exactly one structured log line of the form:
          GCS_SYNC op=upload outcome=<outcome> duration_ms=<n> bytes=<n> detail="..."

    Never re-raises.
    """
    global _last_gcs_sync
    started_at = datetime.now(timezone.utc)
    outcome: str = "unknown_error"
    detail: str = ""
    file_size: int = 0

    # Skipped path: no local DB → nothing to upload
    if not os.path.exists(LOCAL_DB_PATH):
        outcome = "skipped"
        detail = f"DB file not found at {LOCAL_DB_PATH}"
        finished_at = datetime.now(timezone.utc)
        duration_ms = int((finished_at - started_at).total_seconds() * 1000)
        status = GcsSyncStatus(
            op="upload", started_at=started_at, finished_at=finished_at,
            duration_ms=duration_ms, outcome=outcome, bytes=file_size, detail=detail,
        )
        logger.info(status.to_log_string())
        _last_gcs_sync = status
        return status

    # ImportError path
    try:
        from google.cloud import storage  # type: ignore[import-untyped]
    except ImportError as e:
        outcome = "import_error"
        detail = f"google-cloud-storage not importable: {e}"
        finished_at = datetime.now(timezone.utc)
        duration_ms = int((finished_at - started_at).total_seconds() * 1000)
        status = GcsSyncStatus(
            op="upload", started_at=started_at, finished_at=finished_at,
            duration_ms=duration_ms, outcome=outcome, bytes=file_size, detail=detail,
        )
        logger.info(status.to_log_string())
        _last_gcs_sync = status
        return status

    # Main upload path
    try:
        try:
            from google.api_core import exceptions as gax  # type: ignore[import-untyped]
        except ImportError:
            gax = None
        try:
            from google.auth import exceptions as gauth  # type: ignore[import-untyped]
        except ImportError:
            gauth = None

        client = storage.Client()
        bucket = client.bucket("qa-bugbot-data")
        blob = bucket.blob("qa_bugbot.db")
        blob.upload_from_filename(LOCAL_DB_PATH)
        outcome = "ok"
        file_size = os.path.getsize(LOCAL_DB_PATH)
        detail = "synced to GCS"
    except Exception as e:
        cls_name = type(e).__name__
        if 'gauth' in dir() and gauth is not None and isinstance(e, gauth.DefaultCredentialsError):
            outcome = "auth_error"
            detail = f"no ADC available: {e}"
        elif 'gax' in dir() and gax is not None and isinstance(e, gax.Forbidden):
            outcome = "forbidden"
            detail = f"service account lacks objectAdmin: {e}"
        elif 'gax' in dir() and gax is not None and isinstance(e, gax.NotFound):
            outcome = "not_found"
            detail = f"bucket missing: {e}"
        elif isinstance(e, (TimeoutError, ConnectionError, OSError)):
            outcome = "network_error"
            detail = f"{cls_name}: {e}"
        else:
            outcome = "unknown_error"
            detail = f"{cls_name}: {e}"

    finished_at = datetime.now(timezone.utc)
    duration_ms = int((finished_at - started_at).total_seconds() * 1000)
    status = GcsSyncStatus(
        op="upload",
        started_at=started_at,
        finished_at=finished_at,
        duration_ms=duration_ms,
        outcome=outcome,
        bytes=file_size,
        detail=detail,
    )
    logger.info(status.to_log_string())
    _last_gcs_sync = status
    return status


# ─────────────────────────────────────────────
# SQLAlchemy Table Definition
# ─────────────────────────────────────────────

class TesterRegistration(Base):
    """Registered users table — maps Google Chat users to OpenProject API keys."""
    __tablename__ = "tester_registrations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_user_name = Column(String(255), unique=True, nullable=False, index=True)
    chat_display_name = Column(String(255), nullable=False)
    openproject_api_key = Column(Text, nullable=False)
    openproject_user_id = Column(String(50), nullable=True)
    openproject_user_name = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))


# ─────────────────────────────────────────────
# Database Engine & Session
# ─────────────────────────────────────────────

_engine = None
_session_factory = None


async def init_database(database_url: str) -> None:
    """Initialize the database engine and create tables."""
    global _engine, _session_factory

    # Ensure data directory exists
    if "sqlite" in database_url:
        db_path = database_url.split("///")[-1]
        db_dir = os.path.dirname(db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
        
        # Download DB from GCS (restores registrations from previous deployments)
        download_status = _download_db_from_gcs()
        # Only allow uploads if we proved the local DB is in sync with GCS
        # (either ok = restored from existing blob, or skipped = blob genuinely
        # absent so a fresh DB is the correct starting state).
        global _uploads_safe
        _uploads_safe = download_status.outcome in ("ok", "skipped")
        if not _uploads_safe:
            logger.error(
                "GCS download did not succeed (outcome=%s); UPLOADS DISABLED "
                "to protect existing registrations. Investigate before next deploy.",
                download_status.outcome,
            )

    _engine = create_async_engine(database_url, echo=False)
    _session_factory = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)

    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    logger.info("Database initialized successfully.")


async def close_database() -> None:
    """Close the database engine and sync to GCS."""
    global _engine
    if _engine:
        await _engine.dispose()
        # Sync DB to GCS before shutdown (guarded — won't run if download failed)
        _safe_upload_db_to_gcs()
        logger.info("Database connection closed.")


def get_session() -> AsyncSession:
    """Get a new async database session."""
    if _session_factory is None:
        raise RuntimeError("Database not initialized. Call init_database() first.")
    return _session_factory()


# ─────────────────────────────────────────────
# CRUD Operations
# ─────────────────────────────────────────────

async def get_user_by_chat_id(chat_user_name: str) -> Optional[TesterRegistration]:
    """Fetch a user by their Google Chat user name (resource ID)."""
    from sqlalchemy import select
    async with get_session() as session:
        result = await session.execute(
            select(TesterRegistration).where(
                TesterRegistration.chat_user_name == chat_user_name
            )
        )
        return result.scalar_one_or_none()


async def create_or_update_user(
    chat_user_name: str,
    chat_display_name: str,
    openproject_api_key: str,
    openproject_user_id: Optional[str] = None,
    openproject_user_name: Optional[str] = None,
) -> TesterRegistration:
    """Create a new user or update an existing one."""
    from sqlalchemy import select
    async with get_session() as session:
        result = await session.execute(
            select(TesterRegistration).where(
                TesterRegistration.chat_user_name == chat_user_name
            )
        )
        user = result.scalar_one_or_none()

        if user:
            # Update existing user
            user.chat_display_name = chat_display_name
            user.openproject_api_key = openproject_api_key
            user.openproject_user_id = openproject_user_id
            user.openproject_user_name = openproject_user_name
            user.updated_at = datetime.now(timezone.utc)
            logger.info(f"Updated user: {chat_user_name}")
        else:
            # Create new user
            user = TesterRegistration(
                chat_user_name=chat_user_name,
                chat_display_name=chat_display_name,
                openproject_api_key=openproject_api_key,
                openproject_user_id=openproject_user_id,
                openproject_user_name=openproject_user_name,
            )
            session.add(user)
            logger.info(f"Created new user: {chat_user_name}")

        await session.commit()
        await session.refresh(user)
    
    # Sync to GCS immediately after registration change (guarded — won't run
    # if init_database's download failed, protecting existing GCS data)
    _safe_upload_db_to_gcs()
    
    return user


async def check_database_health() -> bool:
    """Check if the database is accessible."""
    try:
        from sqlalchemy import text
        async with get_session() as session:
            await session.execute(text("SELECT 1"))
        return True
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        return False
