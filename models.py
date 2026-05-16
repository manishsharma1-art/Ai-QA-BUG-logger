"""
Pydantic models for QA Bug Logger Bot.
Includes API request/response models and AI structured output schema.
"""

from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum


# ─────────────────────────────────────────────
# Enums matching OpenProject custom option values
# ─────────────────────────────────────────────

class BugType(str, Enum):
    """Maps to customField6 options in OpenProject."""
    UI_UX = "UI/UX"
    FUNCTIONAL = "Functional/Logical"
    NETWORK = "Network"
    CONTENT = "Content"
    PROCESS_CORRECTION = "Process Correction"
    TRANSACTIONAL = "Transactional"


class EnvironmentType(str, Enum):
    """Maps to customField9 options in OpenProject."""
    LIVE = "LIVE"
    STAGE = "STAGE"


class PriorityLevel(str, Enum):
    """Maps to OpenProject priority IDs."""
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"


class PlatformType(str, Enum):
    """Determines which OpenProject project to use."""
    ANDROID = "Android"
    IOS = "iOS"


# ─────────────────────────────────────────────
# AI Structured Output Schema
# ─────────────────────────────────────────────

class ExtractedBugReport(BaseModel):
    """
    Structured bug report extracted by Gemini AI.
    This schema is used for structured output generation.
    """
    title: str = Field(
        description="Concise, actionable bug title. Include device and OS if available."
    )
    actual_behavior: str = Field(
        description="What actually happens — the bug behavior observed."
    )
    expected_behavior: str = Field(
        description="What should happen instead — the correct behavior."
    )
    steps_to_reproduce: List[str] = Field(
        description="Ordered list of steps to reproduce the bug. Typically 3-7 steps."
    )
    device: str = Field(
        description="Exact device model, e.g. 'Samsung Galaxy S23', 'iPhone 15 Pro', 'Redmi Note 9 Pro Max'. Use 'Not specified' if unknown."
    )
    operating_system: str = Field(
        description="OS and version, e.g. 'Android 14', 'iOS 17.2'. Use 'Not specified' if unknown."
    )
    environment: EnvironmentType = Field(
        description="Test environment where the bug was found."
    )
    app_version: str = Field(
        default="Not specified",
        description="App version if mentioned, e.g. '13.3.7', '5.2.1'."
    )
    bug_type: BugType = Field(
        description="Classification of the bug type."
    )
    priority: PriorityLevel = Field(
        description="Bug priority based on severity and impact."
    )
    platform: PlatformType = Field(
        description="Platform: Android or iOS. Auto-detect from device name or QA brief context."
    )
    logs_or_links: Optional[str] = Field(
        default=None,
        description="Any log links, Firebase Crashlytics URLs, or reference links mentioned."
    )


# ─────────────────────────────────────────────
# API Request/Response Models
# ─────────────────────────────────────────────

class UserRegistrationRequest(BaseModel):
    """Request body for user registration endpoint."""
    chat_user_name: str = Field(description="Google Chat user resource name, e.g. 'users/123456789'")
    chat_display_name: str = Field(description="User's display name in Google Chat")
    openproject_api_key: str = Field(description="OpenProject API token")
    openproject_user_id: Optional[str] = Field(default=None, description="OpenProject user ID (auto-fetched)")
    openproject_user_name: Optional[str] = Field(default=None, description="OpenProject user name (auto-fetched)")


class UserRegistrationResponse(BaseModel):
    """Response for user registration."""
    success: bool
    message: str
    user_name: Optional[str] = None
    user_id: Optional[int] = None


class HealthResponse(BaseModel):
    """Response for health check endpoint."""
    status: str
    database: str
    gemini: str
    llm_gateway: Optional[str] = None
    llm_model: Optional[str] = None
    openproject: Optional[str] = None
    timestamp: str


class TicketCreatedResponse(BaseModel):
    """Details of the created OpenProject ticket."""
    ticket_id: int
    ticket_url: str
    project: str
    title: str
    bug_type: str
    priority: str
    platform: str


# ─────────────────────────────────────────────
# Database Model (for SQLAlchemy mapping)
# ─────────────────────────────────────────────

class UserRecord(BaseModel):
    """Represents a registered user in the database."""
    id: Optional[int] = None
    chat_user_id: str
    chat_display_name: str
    openproject_api_key: str
    openproject_user_id: Optional[str] = None
    openproject_user_name: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True
