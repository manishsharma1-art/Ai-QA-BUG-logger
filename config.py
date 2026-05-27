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

# ─────────────────────────────────────────────
# Multi-Bucket Project Mapping
# Maps bucket slug → project identifier (used in API href)
# ─────────────────────────────────────────────

OP_PROJECTS = {
    # ── Mobile App ──
    "Android": 3,                               # slug: android
    "iOS": 85,                                  # slug: iosnative

    # ── App Webview ──
    "LMS Webview": 476,                         # slug: app-webview-lead-manager

    # ── Mobile Site ──
    "Msite": 71,                                # slug: mobilem

    # ── Desktop Website ──
    "Desktop Search": 47,                       # slug: searchui
    "Desktop PDP": 55,                          # slug: proddetail
    "Desktop Login": 62,                        # slug: userident
    "Desktop Homepage": 50,                     # slug: homepg
    "Desktop Header Footer": 44,                # slug: headfoot
    "Seller Dashboard": 84,                     # slug: sellertool
    "Seller BuyLeads": 83,                      # slug: sellerbl
    "Desktop FCP": 54,                          # slug: fcp
    "Desktop DIR": 58,                          # slug: dir
    "Buyer MY.IM": 64,                          # slug: buyermyim
    "Clients Templates": 53,                    # slug: clientstem

    # ── Communication ──
    "WhatsApp": 431,                            # slug: whatsapp-9696

    # ── Internal Tools ──
    "WebERP": 77,                               # slug: weberp
    "Payments": 61,                             # slug: payments

    # ── Photo/Visual Search ──
    "Photo Search": 461,                        # slug: photo-search-im

    # ── Internal Tools (additional) ──
    "MERP": 76,                                 # slug: merp
    "GLAdmin": 66,                              # slug: gladmingen
    "Contact Center": 32,                       # slug: contactcen

    # ── Desktop (additional) ──
    "Desktop Lead Manager": 70,                 # slug: ide
    "Buyer Messages": 393,                      # slug: buyer-my-msg
    "Indic IM": 434,                            # slug: indic-im

    # ── Projects from QA audit ──
    "Product Approval & AI Audit": 470,         # slug: audit-im
    "BL and Enquiry forms": 57,                 # slug: pbrenqform
    "Google Product Ads": 458,                  # slug: google-product-ads
    "Catalog AI Auditor": 477,                  # slug: catalog-ai-auditor
    "Graph Search": 386,                        # slug: gs
    "PNS": 33,                                  # slug: pns
    "Big Buyer": 38,                            # slug: bigbuyer
    "Tender": 79,                               # slug: tender
    "IndiaMART Affiliate": 435,                 # slug: indiamart-affiliate-program
}

# ─────────────────────────────────────────────
# Bucket Category Mapping
# Maps (bucket, sub-category) → category ID in OpenProject
# ─────────────────────────────────────────────

OP_BUCKET_CATEGORIES = {
    # ── Android categories ──
    "Android": {
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
        "SOI_Webview": 2155,
    },
    # ── iOS categories ──
    "iOS": {
        "App Native": 2107, "Buyer Dashboard": 520, "Deeplinking": 525,
        "Guest User": 2115, "Lead Manager": 529, "Login & On Boarding": 2116,
        "My Products": 539, "My Profile": 540, "Notifications": 541,
        "PBR": 544, "Seller dashboard": 553, "Sell on Indiamart": 554,
        "Web View BMC": 1423, "Webview Buyer": 2108, "Webview Buylead": 2114,
        "Webview Export": 2110, "Webview Lens": 2109, "Webview LMS": 2113,
        "Webview Settings": 2117, "Who Viewed My Catalog": 557,
    },
    # ── LMS Webview categories ──
    "LMS Webview": {
        "Android": 2147, "IOS": 2148,
    },
    # ── MobileSite_M categories ──
    "Msite": {
        "Product Detail": 629, "Company Pages": 604, "Home Page": 610,
        "Search": 632, "Search Webview": 2127, "Header/Footer": 609,
        "LogIn/OTP": 614, "Messages": 619, "Foreign": 1664,
        "BuyLead": 1567, "Tenders": 1603, "Seller Tools": 612,
        "Hamburger Menu": 617, "MCAT": 616, "MCAT Webview": 2126,
        "Call": 601, "Enquiry": 602, "All M-Site": 598,
        "Ratings & Reviews": 1466, "Webview": 1462, "Whatsapp": 1627,
        "PDP Webview": 2124, "Company Webview": 2128, "Forms Webview": 2129,
    },
    # ── Desktop Search categories ──
    "Desktop Search": {
        "Search Page UI": 259, "Search Bar": 257, "Filters": 252,
        "Related MCAT": 255, "Not Found (4xx)": 254,
    },
    # ── Desktop PDP categories ──
    "Desktop PDP": {
        "PDP Tasks Desktop": 1159, "Conversion": 1026,
        "Rating and Review": 1684, "SEO": 1025, "Technical": 1683,
    },
    # ── Desktop Login categories ──
    "Desktop Login": {
        "User Login/Auto Login": 1578, "Verification": 1579,
        "Identification": 374,
    },
    # ── Desktop Homepage categories ──
    "Desktop Homepage": {
        "Buyer Dashboard": 283, "Supplier Dashboard": 289,
        "Categories & User Personalization Sections(identified)": 284,
        "DIR - Home & Static Pages": 286, "Others": 288,
    },
    # ── Seller Dashboard categories ──
    "Seller Dashboard": {
        "Seller Dashboard": 1498, "Seller Products": 410,
        "Seller Profile": 1499, "Seller Settings": 1503,
        "Seller Buyer Tools": 1502, "Seller Login": 1510,
        "Seller Photos & Docs": 411, "Seller Invoices": 1501,
        "Online Sales": 1509,
    },
    # ── Photo Search categories ──
    "Photo Search": {
        "Backend (API)": 2068, "Front end Tech": 2067,
        "KnowDis <> IM Lens": 2131, "Product": 2069,
    },
    # ── Seller BuyLeads categories ──
    "Seller BuyLeads": {
        "BuyLead Display": 984, "BuyLead Search": 983,
        "Tenders": 985, "UI/UX": 986, "Others": 987,
        "Know Your Buyer": 1215,
    },
    # ── Buyer MY.IM categories ──
    "Buyer MY.IM": {
        "Buyer MY": 1615, "Business Requirement": 1807,
        "Adhoc Requirement": 1471, "Ratings & Reviews": 1663,
        "User Login/Auto Login": 1472, "Settings/Change Password": 408,
    },
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


def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
