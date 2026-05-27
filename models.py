"""
Pydantic models for QA Bug Logger Bot.
Includes API request/response models and AI structured output schema.
"""

from pydantic import BaseModel, Field, field_validator
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
    LMS_WEBVIEW = "LMS Webview"
    MSITE = "Msite"
    DESKTOP_SEARCH = "Desktop Search"
    DESKTOP_PDP = "Desktop PDP"
    DESKTOP_LOGIN = "Desktop Login"
    DESKTOP_HOMEPAGE = "Desktop Homepage"
    DESKTOP_HEADER_FOOTER = "Desktop Header Footer"
    SELLER_DASHBOARD = "Seller Dashboard"
    SELLER_BUYLEADS = "Seller BuyLeads"
    DESKTOP_FCP = "Desktop FCP"
    DESKTOP_DIR = "Desktop DIR"
    BUYER_MYIM = "Buyer MY.IM"
    CLIENTS_TEMPLATES = "Clients Templates"
    WHATSAPP = "WhatsApp"
    WEBERP = "WebERP"
    PAYMENTS = "Payments"
    PHOTO_SEARCH = "Photo Search"
    MERP = "MERP"
    GLADMIN = "GLAdmin"
    CONTACT_CENTER = "Contact Center"
    DESKTOP_LEAD_MANAGER = "Desktop Lead Manager"
    BUYER_MESSAGES = "Buyer Messages"
    INDIC_IM = "Indic IM"


# ─────────────────────────────────────────────
# AI Structured Output Schema
# ─────────────────────────────────────────────

class ExtractedBugReport(BaseModel):
    """
    Structured bug report extracted by Gemini AI.
    This schema is used for structured output generation.
    """
    title: str = Field(
        default="Bug report",
        description="Concise, actionable bug title."
    )
    actual_behavior: str = Field(
        default="See attached media for details.",
        description="What actually happens — the bug behavior observed."
    )
    expected_behavior: str = Field(
        default="Expected normal behavior.",
        description="What should happen instead — the correct behavior."
    )
    steps_to_reproduce: List[str] = Field(
        default=["See attached media for reproduction steps"],
        description="Ordered list of steps to reproduce the bug."
    )
    device: str = Field(
        default="Not specified",
        description="Device model or 'Desktop' or 'Not specified'."
    )
    operating_system: str = Field(
        default="Not specified",
        description="OS and version or 'Not specified'."
    )
    environment: EnvironmentType = Field(
        default=EnvironmentType.STAGE,
        description="Test environment where the bug was found."
    )
    app_version: str = Field(
        default="Not specified",
        description="App version if mentioned."
    )
    bug_type: BugType = Field(
        default=BugType.FUNCTIONAL,
        description="Classification of the bug type."
    )
    priority: PriorityLevel = Field(
        default=PriorityLevel.MEDIUM,
        description="Bug priority based on severity and impact."
    )
    platform: PlatformType = Field(
        default=PlatformType.ANDROID,
        description="Platform bucket — auto-detected by bucket_router, not LLM."
    )
    logs_or_links: Optional[str] = Field(
        default=None,
        description="Any log links, URLs, or reference links."
    )
    category: Optional[str] = Field(
        default=None,
        description="Sub-category within the bucket/platform."
    )

    @field_validator('platform', mode='before')
    @classmethod
    def validate_platform(cls, v):
        if not v or not isinstance(v, str):
            return PlatformType.ANDROID
        v_clean = v.strip()
        v_lower = v_clean.lower()
        
        # Exact match mapping (case-insensitive)
        platform_map = {
            "android": PlatformType.ANDROID,
            "ios": PlatformType.IOS,
            "lms webview": PlatformType.LMS_WEBVIEW,
            "msite": PlatformType.MSITE,
            "desktop search": PlatformType.DESKTOP_SEARCH,
            "desktop pdp": PlatformType.DESKTOP_PDP,
            "desktop login": PlatformType.DESKTOP_LOGIN,
            "desktop homepage": PlatformType.DESKTOP_HOMEPAGE,
            "desktop header footer": PlatformType.DESKTOP_HEADER_FOOTER,
            "seller dashboard": PlatformType.SELLER_DASHBOARD,
            "seller buyleads": PlatformType.SELLER_BUYLEADS,
            "desktop fcp": PlatformType.DESKTOP_FCP,
            "desktop dir": PlatformType.DESKTOP_DIR,
            "buyer my.im": PlatformType.BUYER_MYIM,
            "clients templates": PlatformType.CLIENTS_TEMPLATES,
            "whatsapp": PlatformType.WHATSAPP,
            "weberp": PlatformType.WEBERP,
            "payments": PlatformType.PAYMENTS,
            "photo search": PlatformType.PHOTO_SEARCH,
            "merp": PlatformType.MERP,
            "gladmin": PlatformType.GLADMIN,
            "contact center": PlatformType.CONTACT_CENTER,
            "desktop lead manager": PlatformType.DESKTOP_LEAD_MANAGER,
            "buyer messages": PlatformType.BUYER_MESSAGES,
            "indic im": PlatformType.INDIC_IM,
        }
        
        # Try exact match
        if v_lower in platform_map:
            return platform_map[v_lower]
        
        # Try partial match with extended aliases
        # ORDER MATTERS: more specific aliases must come before generic ones
        alias_map_ordered = [
            # Specific multi-word aliases first (to prevent "lms" from matching before "desktop lms")
            ("desktop lms", PlatformType.DESKTOP_LEAD_MANAGER),
            ("desktop lead manager", PlatformType.DESKTOP_LEAD_MANAGER),
            ("photo search", PlatformType.PHOTO_SEARCH),
            ("image search", PlatformType.PHOTO_SEARCH),
            ("mobile erp", PlatformType.MERP),
            ("mobile site", PlatformType.MSITE),
            ("global admin", PlatformType.GLADMIN),
            ("contact center", PlatformType.CONTACT_CENTER),
            ("regional language", PlatformType.INDIC_IM),
            ("buyer my-messages", PlatformType.BUYER_MESSAGES),
            ("buyer messages", PlatformType.BUYER_MESSAGES),
            ("header & footer", PlatformType.DESKTOP_HEADER_FOOTER),
            ("header footer", PlatformType.DESKTOP_HEADER_FOOTER),
            ("centralized header", PlatformType.DESKTOP_HEADER_FOOTER),
            ("search ui", PlatformType.DESKTOP_SEARCH),
            ("desktop search", PlatformType.DESKTOP_SEARCH),
            ("desktop pdp", PlatformType.DESKTOP_PDP),
            ("product detail page", PlatformType.DESKTOP_PDP),
            ("desktop login", PlatformType.DESKTOP_LOGIN),
            ("desktop homepage", PlatformType.DESKTOP_HOMEPAGE),
            ("seller dashboard", PlatformType.SELLER_DASHBOARD),
            ("seller buyleads", PlatformType.SELLER_BUYLEADS),
            ("seller bl", PlatformType.SELLER_BUYLEADS),
            ("desktop fcp", PlatformType.DESKTOP_FCP),
            ("desktop dir", PlatformType.DESKTOP_DIR),
            ("client template", PlatformType.CLIENTS_TEMPLATES),
            ("buyer my", PlatformType.BUYER_MYIM),
            ("my.im", PlatformType.BUYER_MYIM),
            # Then single-word / shorter aliases
            ("lms", PlatformType.LMS_WEBVIEW),
            ("lead manager", PlatformType.LMS_WEBVIEW),
            ("msite", PlatformType.MSITE),
            ("mobilesitem", PlatformType.MSITE),
            ("m-site", PlatformType.MSITE),
            ("lens", PlatformType.PHOTO_SEARCH),
            ("whatsapp", PlatformType.WHATSAPP),
            ("9696", PlatformType.WHATSAPP),
            ("weberp", PlatformType.WEBERP),
            ("erp", PlatformType.WEBERP),
            ("fcp", PlatformType.DESKTOP_FCP),
            ("mdc", PlatformType.DESKTOP_FCP),
            ("payment", PlatformType.PAYMENTS),
            ("merp", PlatformType.MERP),
            ("nsd", PlatformType.MERP),
            ("gladmin", PlatformType.GLADMIN),
            ("indic", PlatformType.INDIC_IM),
        ]
        
        for key, val in alias_map_ordered:
            if key in v_lower:
                return val
        
        # Try original platform_map partial match
        for key, val in platform_map.items():
            if key in v_lower:
                return val
        
        # Legacy fallback for simple ios/android
        if 'ios' in v_lower or 'iphone' in v_lower:
            return PlatformType.IOS
        
        return PlatformType.ANDROID

    @field_validator('bug_type', mode='before')
    @classmethod
    def validate_bug_type(cls, v):
        if not v or not isinstance(v, str):
            return BugType.FUNCTIONAL
        v_clean = v.strip().lower()
        if 'ui/ux' in v_clean or 'ui' in v_clean or 'ux' in v_clean:
            return BugType.UI_UX
        if 'network' in v_clean:
            return BugType.NETWORK
        if 'content' in v_clean:
            return BugType.CONTENT
        if 'process' in v_clean:
            return BugType.PROCESS_CORRECTION
        if 'transaction' in v_clean:
            return BugType.TRANSACTIONAL
        return BugType.FUNCTIONAL

    @field_validator('priority', mode='before')
    @classmethod
    def validate_priority(cls, v):
        if not v or not isinstance(v, str):
            return PriorityLevel.MEDIUM
        v_clean = v.strip().lower()
        if 'high' in v_clean:
            return PriorityLevel.HIGH
        if 'low' in v_clean:
            return PriorityLevel.LOW
        return PriorityLevel.MEDIUM

    @field_validator('environment', mode='before')
    @classmethod
    def validate_environment(cls, v):
        if not v or not isinstance(v, str):
            return EnvironmentType.STAGE
        v_clean = v.strip().lower()
        if 'live' in v_clean or 'prod' in v_clean:
            return EnvironmentType.LIVE
        return EnvironmentType.STAGE

    @field_validator('steps_to_reproduce', mode='before')
    @classmethod
    def validate_steps(cls, v):
        if not v:
            return ["Review attached media"]
        if isinstance(v, str):
            return [v]
        if isinstance(v, list):
            return [str(item) for item in v if item]
        return ["Review attached media"]


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
