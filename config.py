"""
Configuration management for QA Bug Logger Bot.
All OpenProject field IDs extracted from live instance at project.intermesh.net.
Environment variables match the deployed Cloud Run service.
"""

import os
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # ── LLM Configuration (OpenAI-compatible gateway) ──
    llm_api_key: str = Field(default="", env="LLM_API_KEY")
    llm_base_url: str = Field(default="https://imllm.intermesh.net/v1", env="LLM_BASE_URL")
    llm_model: str = Field(default="google/gemini-2.5-flash", env="LLM_MODEL")

    # ── OpenProject Configuration ──
    openproject_base_url: str = Field(
        default="https://project.intermesh.net", env="OPENPROJECT_BASE_URL"
    )
    default_openproject_api_key: str = Field(
        default="", env="DEFAULT_OPENPROJECT_API_KEY"
    )
    demo_space_id: str = Field(
        default="", env="DEMO_SPACE_ID"
    )

    # ── Google Chat Configuration ──
    google_service_account_json: str = Field(
        default="service-account.json", env="GOOGLE_SERVICE_ACCOUNT_JSON"
    )

    # ── Database ──
    database_url: str = Field(
        default="sqlite+aiosqlite:///./data/qa_bugbot.db", env="DATABASE_URL"
    )

    # ── Server ──
    port: int = Field(default=8080, env="PORT")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


# ─────────────────────────────────────────────
# OpenProject Field Mappings (from live instance)
# ─────────────────────────────────────────────

# Type ID for Product Bug
OP_TYPE_BUG_ID = 7

# Priority IDs
OP_PRIORITIES = {
    "High": 9,
    "Medium": 8,
    "Low": 7,
}

# Project identifiers (must use integer IDs)
OP_PROJECTS = {
    "Android": 3,
    "iOS": 85,
    "Web": 98,
    "Backend": 5,
}

# customField6 — Bug Type (CustomOption, set via _links)
OP_BUG_TYPES = {
    "UI/UX": 10,
    "Functional/Logical": 11,
    "Network": 12,
    "Content": 13,
    "Process Correction": 14,
    "Transactional": 15,
}

# customField9 — Environment (CustomOption, set via _links)
OP_ENVIRONMENTS = {
    "LIVE": 21,
    "STAGE": 22,
}

# ─────────────────────────────────────────────
# Category IDs per project (for reference only —
# Category is filled manually by QA, not by the bot)
# ─────────────────────────────────────────────

ANDROID_CATEGORIES = {
    "App_Native": 638, "User Login": 690, "Buyer Dashboard": 648,
    "Seller Dashboard": 685, "LeadManager": 663, "Notifications": 676,
    "Payment": 677, "My Products": 674, "My Profile": 675,
    "Deeplinking": 655, "BuyLeads": 651, "Buyer Message Centre": 649,
    "App Communications": 639, "App config": 640, "BizFeed": 644,
    "Sell on Indiamart": 686, "User Onboarding": 691, "XMPP": 692,
    "Search_webview": 1817, "PDP_webview": 1818, "Products_Webview": 1999,
    "BMC_WEBVIEW": 1410, "LMS_Webview": 1811, "BL_Webview": 1810,
    "Webview-Buyer": 2106, "Webview-Export": 2105, "Webview-Lens": 2104,
    "Users_webview": 2000, "Company_webview": 1819, "Impcat_webview": 1820,
}

IOS_CATEGORIES = {
    "App Native": 2107, "Buyer Dashboard": 520, "Deeplinking": 525,
    "Guest User": 2115, "Lead Manager": 529, "Login & On Boarding": 2116,
    "My Products": 539, "My Profile": 540, "Notifications": 541,
    "PBR": 544, "Seller dashboard": 553, "Sell on Indiamart": 554,
    "Web View BMC": 1423, "Webview Buyer": 2108, "Webview Buylead": 2114,
    "Webview Export": 2110, "Webview Lens": 2109, "Webview LMS": 2113,
    "Webview Settings": 2117, "Who Viewed My Catalog": 557,
}


def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
