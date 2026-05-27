"""
Bucket routing — determines which OpenProject project receives the ticket.
Uses Python regex + fuzzy matching. NO LLM involved.

Flow:
1. Extract [Tag] from message text via regex
2. Try exact match against OP_PROJECTS
3. Try alias/keyword match
4. Try fuzzy match (handles typos)
5. If no tag: detect device (Android/iOS) from text
6. Default: Android
"""

import re
import logging
from difflib import get_close_matches
from typing import Tuple, Optional

from config import OP_PROJECTS

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# All known project names + aliases
# ─────────────────────────────────────────────

# Maps lowercase alias → exact OP_PROJECTS key
PROJECT_ALIASES = {
    # Android
    "android": "Android",
    # iOS
    "ios": "iOS",
    "iphone": "iOS",
    "ios native": "iOS",
    # LMS Webview
    "lms webview": "LMS Webview",
    "lms": "LMS Webview",
    "lead manager webview": "LMS Webview",
    "app webview lead manager": "LMS Webview",
    # Msite
    "msite": "Msite",
    "mobile site": "Msite",
    "m-site": "Msite",
    "mobilesitem": "Msite",
    "mobilesite_m": "Msite",
    # Desktop Search
    "desktop search": "Desktop Search",
    "desktop search ui": "Desktop Search",
    "search ui": "Desktop Search",
    # Desktop PDP
    "desktop pdp": "Desktop PDP",
    "product detail page": "Desktop PDP",
    # Desktop Login
    "desktop login": "Desktop Login",
    "desktop identification": "Desktop Login",
    "login verification": "Desktop Login",
    # Desktop Homepage
    "desktop homepage": "Desktop Homepage",
    "indiamart homepage": "Desktop Homepage",
    "homepage": "Desktop Homepage",
    # Desktop Header Footer
    "desktop header footer": "Desktop Header Footer",
    "header footer": "Desktop Header Footer",
    "header & footer": "Desktop Header Footer",
    "centralized header": "Desktop Header Footer",
    "centralized header & footer": "Desktop Header Footer",
    "centralized header and footer": "Desktop Header Footer",
    # Seller Dashboard
    "seller dashboard": "Seller Dashboard",
    "seller tools": "Seller Dashboard",
    # Seller BuyLeads
    "seller buyleads": "Seller BuyLeads",
    "seller buy leads": "Seller BuyLeads",
    "seller latest buy leads": "Seller BuyLeads",
    "seller bl": "Seller BuyLeads",
    # Desktop FCP
    "desktop fcp": "Desktop FCP",
    "fcp": "Desktop FCP",
    "fcp/mdc": "Desktop FCP",
    "mdc": "Desktop FCP",
    # Desktop DIR
    "desktop dir": "Desktop DIR",
    "dir": "Desktop DIR",
    # Buyer MY.IM
    "buyer my.im": "Buyer MY.IM",
    "buyer my": "Buyer MY.IM",
    "buyermy": "Buyer MY.IM",
    "buyermy im": "Buyer MY.IM",
    # Clients Templates
    "clients templates": "Clients Templates",
    "client templates": "Clients Templates",
    "mobile template": "Clients Templates",
    # WhatsApp
    "whatsapp": "WhatsApp",
    "whatsapp-9696": "WhatsApp",
    # WebERP
    "weberp": "WebERP",
    "weberp - core": "WebERP",
    "web erp": "WebERP",
    # Payments
    "payments": "Payments",
    "online payments": "Payments",
    # Photo Search
    "photo search": "Photo Search",
    "photo search im": "Photo Search",
    "lens": "Photo Search",
    "image search": "Photo Search",
    # MERP
    "merp": "MERP",
    "mobile erp": "MERP",
    # GLAdmin
    "gladmin": "GLAdmin",
    "gladmingen": "GLAdmin",
    "global admin": "GLAdmin",
    # Contact Center
    "contact center": "Contact Center",
    "contact center 9696": "Contact Center",
    # Desktop Lead Manager
    "desktop lead manager": "Desktop Lead Manager",
    "desktop lms": "Desktop Lead Manager",
    # Buyer Messages
    "buyer messages": "Buyer Messages",
    "buyer my-messages": "Buyer Messages",
    # Indic IM
    "indic im": "Indic IM",
    "indic": "Indic IM",
    # Additional projects QA uses (from audit)
    "product approval & ai audit": "Product Approval & AI Audit",
    "product approval": "Product Approval & AI Audit",
    "ai audit": "Product Approval & AI Audit",
    "bl and enquiry forms": "BL and Enquiry forms",
    "bl and enquiry form": "BL and Enquiry forms",
    "enquiry forms": "BL and Enquiry forms",
    "google product ads": "Google Product Ads",
    "catalog ai auditor": "Catalog AI Auditor",
    "graph search": "Graph Search",
    "pns": "PNS",
    "big buyer": "Big Buyer",
    "tender": "Tender",
    "indiamart affiliate": "IndiaMART Affiliate",
}

# Android device keywords
ANDROID_DEVICES = [
    "samsung", "iqoo", "realme", "motorola", "moto", "poco",
    "redmi", "xiaomi", "oneplus", "vivo", "oppo", "nothing",
    "google pixel", "pixel", "nokia", "tecno", "infinix", "mi ",
]

# iOS device keywords
IOS_DEVICES = ["iphone", "ipad", "apple"]


def extract_bucket_from_message(text: str) -> Tuple[Optional[int], str]:
    """
    Extract the target project ID from the message text.
    
    Returns:
        (project_id, cleaned_text) — project_id is None if no match found (use default)
        cleaned_text has the [tag] stripped out
    """
    # Step 1: Extract [Tag] from message
    tag_match = re.search(r'\[([^\]]+)\]', text)
    
    if tag_match:
        tag = tag_match.group(1).strip()
        cleaned_text = text[:tag_match.start()] + text[tag_match.end():]
        cleaned_text = cleaned_text.strip()
        
        project_id = _resolve_tag(tag)
        if project_id:
            logger.info(f"Bucket routing: [{tag}] → project {project_id}")
            return project_id, cleaned_text
        else:
            logger.warning(f"Bucket routing: [{tag}] — no match found, using device detection")
            # Tag didn't match, still use cleaned text but fall through to device detection
            return _detect_device_platform(cleaned_text), cleaned_text
    
    # No tag found — detect from device/OS
    project_id = _detect_device_platform(text)
    logger.info(f"Bucket routing: no tag, device detection → project {project_id}")
    return project_id, text


def _resolve_tag(tag: str) -> Optional[int]:
    """Resolve a tag string to a project ID using exact → alias → fuzzy matching."""
    tag_lower = tag.lower().strip()
    
    # Step 1: Exact match in OP_PROJECTS
    if tag in OP_PROJECTS:
        return OP_PROJECTS[tag]
    
    # Step 2: Case-insensitive exact match
    for key, proj_id in OP_PROJECTS.items():
        if key.lower() == tag_lower:
            return proj_id
    
    # Step 3: Alias match
    if tag_lower in PROJECT_ALIASES:
        project_name = PROJECT_ALIASES[tag_lower]
        if project_name in OP_PROJECTS:
            return OP_PROJECTS[project_name]
    
    # Step 4: Partial alias match (tag contains alias or alias contains tag)
    for alias, project_name in PROJECT_ALIASES.items():
        if alias in tag_lower or tag_lower in alias:
            if project_name in OP_PROJECTS:
                return OP_PROJECTS[project_name]
    
    # Step 5: Fuzzy match against all project names
    all_names = list(OP_PROJECTS.keys()) + list(PROJECT_ALIASES.keys())
    matches = get_close_matches(tag_lower, [n.lower() for n in all_names], n=1, cutoff=0.6)
    if matches:
        matched_lower = matches[0]
        # Find the original key
        for key in OP_PROJECTS:
            if key.lower() == matched_lower:
                logger.info(f"Fuzzy matched [{tag}] → {key}")
                return OP_PROJECTS[key]
        for alias, project_name in PROJECT_ALIASES.items():
            if alias.lower() == matched_lower and project_name in OP_PROJECTS:
                logger.info(f"Fuzzy matched [{tag}] → {project_name} (via alias '{alias}')")
                return OP_PROJECTS[project_name]
    
    return None


def _detect_device_platform(text: str) -> int:
    """Detect Android/iOS from device names in text. Default: Android."""
    text_lower = text.lower()
    
    # Check iOS first (more specific)
    for device in IOS_DEVICES:
        if device in text_lower:
            return OP_PROJECTS.get("iOS", 85)
    
    # Check Android devices
    for device in ANDROID_DEVICES:
        if device in text_lower:
            return OP_PROJECTS.get("Android", 3)
    
    # Check OS mentions
    if "ios " in text_lower or "ios:" in text_lower:
        return OP_PROJECTS.get("iOS", 85)
    if "android " in text_lower or "android:" in text_lower:
        return OP_PROJECTS.get("Android", 3)
    
    # Default
    return OP_PROJECTS.get("Android", 3)
