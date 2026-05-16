"""
Async SQLite database setup and CRUD operations for user registration.
Uses SQLAlchemy async with aiosqlite.
Table name: tester_registrations (matches deployed version).
"""

import os
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Column, Integer, String, DateTime, Text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base

logger = logging.getLogger(__name__)

Base = declarative_base()


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

    _engine = create_async_engine(database_url, echo=False)
    _session_factory = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)

    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    logger.info("Database initialized successfully.")


async def close_database() -> None:
    """Close the database engine."""
    global _engine
    if _engine:
        await _engine.dispose()
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
