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
# Anchored bucket-tag regex
# ─────────────────────────────────────────────
# Only match a bracketed tag at the START of the message (after optional
# whitespace). The tag body must begin with a letter and consist of letters,
# digits, spaces, and the punctuation `& / -`, length 2..41 chars total. This
# prevents free-floating brackets like `[step 3]` or `[2024-05-12]` from being
# treated as bucket tags.
BUCKET_TAG_RE = re.compile(
    r'^\s*\[([A-Za-z][A-Za-z0-9 &/\-]{1,40})\]\s*',
    re.UNICODE,
)

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
    # NOTE — known audit gaps (do NOT alias speculatively).
    # These project names appear in QA briefs but have no entry in
    # OP_PROJECTS today, so they fall through to device-detection +
    # Android default. Operator must decide whether each one should be:
    #   1. a new top-level project added to OP_PROJECTS, or
    #   2. an alias mapping to an existing project (which one?).
    # Affected names from the May QA audit:
    #   - Model Product Library
    #   - Msite SOI
    #   - Export
    # See tests/unit/test_qa_audit_routing.py::test_known_config_gaps_documented.
}

# ─────────────────────────────────────────────
# Cross-keyword single words — too generic to single-handedly route a bucket
# ─────────────────────────────────────────────
# These words appear in many bucket aliases AND in many bug descriptions, so
# they get score=1 in the free-text scoring pass instead of the default score=5.
# See _extract_bucket_from_freetext (Theme 4.5).
CROSS_KEYWORD_SINGLE_WORDS = {
    "login", "home", "homepage", "search", "page", "screen",
    "app", "android", "ios", "user", "buyer", "seller",
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
        (project_id, text_for_llm) — project_id is None if no match found (use default).

    The returned text_for_llm is the ORIGINAL `text`, byte-identical, regardless of
    whether a bucket tag matched. The bucket tag is intentionally NOT stripped —
    the LLM needs to see the QA tester's brief verbatim (including any `[Tag]`
    prefix) so that downstream prompts and ticket bodies preserve user intent.
    See design Theme 4 / Requirement 1.9.

    Three-layer routing (Theme 4.6):
      Layer 1: Explicit [Tag] at start (highest priority)
      Layer 2: Free-text bucket extraction (scoring-based)
      Layer 3: Device/OS detection (fallback)
    """
    pid, txt, _ = extract_bucket_with_provenance(text)
    return pid, txt


# Provenance values returned alongside (project_id, text):
#   "tag"           — explicit [Tag] at start matched
#   "freetext"      — free-text scoring or prose phrase matched
#   "device"        — device-name keyword fired (Samsung/iPhone/etc.)
#   "default"       — no signal anywhere; Android default used
# Used by main.py to decide whether to invoke the LLM bucket-picker fallback.
ROUTING_PROVENANCE = ("tag", "freetext", "device", "default")


def extract_bucket_with_provenance(text: str) -> Tuple[Optional[int], str, str]:
    """
    Like extract_bucket_from_message but also returns *how* the routing decision
    was made. The orchestration layer (main.py) uses the provenance to decide
    whether to invoke the LLM bucket-picker fallback.

    Returns:
        (project_id, text_for_llm, provenance) where provenance ∈ ROUTING_PROVENANCE.
    """
    # Layer 1: Explicit [Tag] at start
    tag_match = BUCKET_TAG_RE.match(text)
    if tag_match:
        tag = tag_match.group(1).strip()
        project_id = _resolve_tag(tag)
        if project_id:
            logger.info(f"Bucket routing: [{tag}] → project {project_id}")
            return project_id, text, "tag"
        else:
            logger.warning(f"Bucket routing: [{tag}] — no match found, trying free-text")

    # Layer 2: Free-text bucket extraction (Theme 4.5 + audit prose patterns)
    project_id = _extract_bucket_from_freetext(text)
    if project_id:
        logger.info(f"Bucket routing: free-text match → project {project_id}")
        return project_id, text, "freetext"

    # Layer 3: Device/OS detection — also report whether a real device matched
    project_id, device_matched = _detect_device_platform_with_provenance(text)
    if device_matched:
        logger.info(f"Bucket routing: device-detection → project {project_id}")
        return project_id, text, "device"
    logger.info(f"Bucket routing: no signal, falling back to default → project {project_id}")
    return project_id, text, "default"


def _detect_device_platform_with_provenance(text: str) -> Tuple[int, bool]:
    """Like _detect_device_platform but also reports whether a real device-name
    keyword matched (True) or the Android default was used (False)."""
    text_lower = text.lower()

    for device in IOS_DEVICES:
        if device in text_lower:
            return OP_PROJECTS.get("iOS", 85), True

    for device in ANDROID_DEVICES:
        if device in text_lower:
            return OP_PROJECTS.get("Android", 3), True

    if "ios " in text_lower or "ios:" in text_lower:
        return OP_PROJECTS.get("iOS", 85), True
    if "android " in text_lower or "android:" in text_lower:
        return OP_PROJECTS.get("Android", 3), True

    # No real device signal — Android default
    return OP_PROJECTS.get("Android", 3), False


# Regex for "bucket - X", "bucket: X", "bucket X" shorthand
_BUCKET_SHORTHAND_RE = re.compile(
    r'\bbucket\s*[-:]?\s*([A-Za-z][A-Za-z0-9 &/\-]{1,40})',
    re.IGNORECASE,
)

# Additional prose phrasings used by QA in briefs (audit May 2026):
#   "should raise bug in <name>", "should be opened in <name>",
#   "should create in <name>", "raise bug in <name>",
#   "→ should create in <name>", "→ raise in <name>"
# Pattern allows a leading arrow / hyphen / colon / dash for the "→" form.
_BUCKET_PROSE_RE = re.compile(
    r'(?:->|→|:|\s)\s*'
    r'(?:should\s+(?:be\s+)?(?:raise(?:d)?|open(?:ed)?|create(?:d)?|file(?:d)?)'
    r'|raise(?:d)?|open(?:ed)?|create(?:d)?|file(?:d)?)'
    r'(?:\s+(?:bug|ticket|issue))?'
    r'\s+in\s+'
    r'(?:the\s+)?'
    r'([A-Za-z][A-Za-z0-9 &/\-,.]{1,60}?)'
    r'(?:\s+(?:project|bucket))?'
    r'(?:\s*[\.\n,;]|$)',
    re.IGNORECASE,
)


def _extract_bucket_from_freetext(text: str) -> Optional[int]:
    """
    Free-text bucket extraction layer (Theme 4.5).

    Scans the message for:
      Step A: "bucket - X" / "bucket: X" / "bucket X" shorthand patterns
      Step B: Known bucket names and multi-word aliases (scoring-based)

    Returns the project ID or None if no confident match.
    Pure Python, no LLM call.
    """
    text_lower = text.lower()
    scores: dict = {}  # project_id → cumulative score

    # ── Step A: bucket-shorthand pattern ──
    shorthand_match = _BUCKET_SHORTHAND_RE.search(text_lower)
    if shorthand_match:
        candidate = shorthand_match.group(1).strip()
        project_id = _resolve_tag(candidate)
        if project_id:
            return project_id  # explicit shorthand wins immediately

    # ── Step A2: prose patterns from QA audit ──
    # "should raise bug in <name>", "should be opened in <name>",
    # "should create in <name>", "raise bug in <name>", "→ should create in <name>"
    # All variations explicitly state the destination bucket.
    for prose_match in _BUCKET_PROSE_RE.finditer(text_lower):
        candidate = prose_match.group(1).strip().rstrip(".,;")
        # Strip a trailing common noise word that the regex's lazy match might
        # leave behind (e.g. "Photo Search im bucket" → "Photo Search im").
        candidate = re.sub(r'\s+(project|bucket)$', '', candidate)
        project_id = _resolve_tag(candidate)
        if project_id:
            return project_id  # prose match wins (very high confidence signal)

    # ── Step B: scan for known bucket names and multi-word aliases ──
    # Higher weight = more specific

    # Check canonical project names (multi-word canonical names get weight 10)
    for canonical_name, project_id in OP_PROJECTS.items():
        name_lower = canonical_name.lower()
        # Check for whole-word phrase match using word boundaries
        pattern = r'\b' + re.escape(name_lower) + r'\b'
        if re.search(pattern, text_lower):
            scores[project_id] = scores.get(project_id, 0) + 10

    # Check aliases
    for alias, canonical_name in PROJECT_ALIASES.items():
        if canonical_name not in OP_PROJECTS:
            continue
        project_id = OP_PROJECTS[canonical_name]
        alias_words = alias.split()

        if len(alias_words) >= 2:
            # Multi-word alias — weight 8
            pattern = r'\b' + re.escape(alias) + r'\b'
            if re.search(pattern, text_lower):
                scores[project_id] = scores.get(project_id, 0) + 8
        else:
            # Single-word alias
            if alias in CROSS_KEYWORD_SINGLE_WORDS:
                weight = 1  # generic, ambiguous word
            else:
                weight = 5  # specific single-word alias
            pattern = r'\b' + re.escape(alias) + r'\b'
            if re.search(pattern, text_lower):
                scores[project_id] = scores.get(project_id, 0) + weight

    if not scores:
        return None

    # ── Step C: tie-breaker ──
    max_score = max(scores.values())
    winners = [pid for pid, s in scores.items() if s == max_score]

    if len(winners) > 1 and max_score < 10:
        # Genuinely ambiguous low-confidence match — let device detection decide
        return None

    return winners[0]  # single winner OR multi-word match always wins ties


def _resolve_tag(tag: str) -> Optional[int]:
    """Resolve a tag string to a project ID using exact → alias → substring → fuzzy."""
    tag_lower = tag.lower().strip()
    if len(tag_lower) < 2:
        return None

    # Step 1: Exact match (case-sensitive)
    if tag in OP_PROJECTS:
        return OP_PROJECTS[tag]

    # Step 2: Case-insensitive exact match
    for key, proj_id in OP_PROJECTS.items():
        if key.lower() == tag_lower:
            return proj_id

    # Step 3: Alias exact match
    if tag_lower in PROJECT_ALIASES:
        proj_name = PROJECT_ALIASES[tag_lower]
        if proj_name in OP_PROJECTS:
            return OP_PROJECTS[proj_name]

    # Step 4: Alias-substring match (alias must appear within tag, alias must be ≥3 chars)
    # Sort by length descending so longer aliases match first (fixes Property 3 for typos like 'adesktop lms' vs 'desktop lms' vs 'lms')
    for alias, proj_name in sorted(PROJECT_ALIASES.items(), key=lambda x: len(x[0]), reverse=True):
        if len(alias) >= 3 and alias in tag_lower:
            if proj_name in OP_PROJECTS:
                return OP_PROJECTS[proj_name]

    # Step 5: Fuzzy match, cutoff raised to 0.78
    # Skip for very short tags (< 4 chars): difflib's ratio is too permissive at
    # short lengths (e.g. 'ns' vs 'pns' has ratio 0.8 ≥ 0.78 even though it's a
    # bad match). Property 3 requires that mutated typos never resolve to a
    # *different* project; short tags should hit exact/alias-exact paths or
    # return None rather than fuzzy-matching to spurious aliases.
    if len(tag_lower) < 4:
        return None
    candidates = [n.lower() for n in
                  list(OP_PROJECTS.keys()) + list(PROJECT_ALIASES.keys())]
    matches = get_close_matches(tag_lower, candidates, n=1, cutoff=0.78)
    if matches:
        matched_lower = matches[0]
        for key in OP_PROJECTS:
            if key.lower() == matched_lower:
                logger.info(f"Fuzzy matched [{tag}] → {key}")
                return OP_PROJECTS[key]
        for alias, proj_name in PROJECT_ALIASES.items():
            if alias.lower() == matched_lower and proj_name in OP_PROJECTS:
                logger.info(f"Fuzzy matched [{tag}] → {proj_name} (via alias '{alias}')")
                return OP_PROJECTS[proj_name]

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
