"""
QA Bug Logger Bot — Main FastAPI Application.

Receives bug reports via Google Chat webhook, analyzes with Gemini 2.5 Flash
(via IndiaMART LLM Gateway), and creates formatted tickets in OpenProject.

Deployed at: https://qa-bug-bot-542857204182.us-central1.run.app
"""

import asyncio
import logging
import re
import time
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List

from fastapi import FastAPI, Request, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from config import get_settings
from env_validator import validate_env_vars, read_build_marker
from bucket_router import (
    extract_bucket_from_message,
    extract_bucket_with_provenance,
)
from database import (
    init_database, close_database, check_database_health,
    get_user_by_chat_id, create_or_update_user,
)
from gemini_client import GeminiClient
from openproject_client import OpenProjectClient
from google_auth import GoogleChatClient
from models import (
    UserRegistrationRequest, UserRegistrationResponse,
    HealthResponse, ExtractedBugReport
)

import collections
from pydantic import ValidationError

# ─────────────────────────────────────────────
# Logging Setup
# ─────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("qa_bugbot")

# In-memory log capture for debugging without GCP console access
_log_capture = collections.deque(maxlen=200)

class MemoryLogHandler(logging.Handler):
    def emit(self, record):
        _log_capture.append(self.format(record))

memory_handler = MemoryLogHandler()
memory_handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-7s | %(message)s"))
logger.addHandler(memory_handler)


# ─────────────────────────────────────────────
# Global Clients (initialized at startup)
# ─────────────────────────────────────────────

settings = get_settings()
gemini_client: Optional[GeminiClient] = None
op_client: Optional[OpenProjectClient] = None
chat_client: Optional[GoogleChatClient] = None

# Deduplication cache (prevents duplicate tickets from webhook retries)
# Stores message_id -> timestamp, evicts after 5 minutes
_processed_messages: OrderedDict = OrderedDict()
DEDUP_TTL_SECONDS = 300

# Strong references for asyncio tasks to prevent garbage collection
_active_background_tasks = set()

# Build marker captured at startup (Theme 1.4 / Requirement 5.11)
# Surfaced through /health.build_marker by task 8.2
_build_marker: str = ""

# LLM gateway smoke test result captured at startup. Populated by lifespan
# after gemini_client is constructed. Used by /health to surface
# `gemini=ok|auth_error|rate_limit|server_error|network_error|unknown_error`
# instead of the prior boolean `configured/not configured`. None means
# "smoke test never ran" (e.g. LLM_API_KEY was empty).
_llm_smoke_result: Optional[Dict[str, Any]] = None



# ─────────────────────────────────────────────
# App Lifecycle
# ─────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize services on startup, clean up on shutdown."""
    global gemini_client, op_client, chat_client, _build_marker

    logger.info("=" * 60)
    logger.info("QA Bug Logger Bot — Starting up...")
    logger.info("=" * 60)

    # Theme 1.4 / Theme 1.2 — emit BUILD_MARKER and run env validator BEFORE DB init.
    _build_marker = read_build_marker()
    logger.info("BUILD_MARKER: %s", _build_marker)
    validate_env_vars(settings)  # logs ENV_VALIDATION:* warnings, never raises

    # Initialize database
    await init_database(settings.database_url)
    logger.info("✅ Database initialized")

    # Initialize LLM client (OpenAI-compatible gateway)
    if settings.llm_api_key:
        gemini_client = GeminiClient(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            model=settings.llm_model,
        )
        logger.info(f"✅ LLM client initialized: {settings.llm_model} @ {settings.llm_base_url}")

        # Gateway smoke test — catches an invalid/rotated key BEFORE traffic
        # hits a webhook. Result stored in module-level _llm_smoke_result and
        # surfaced via /health.gemini.
        global _llm_smoke_result
        try:
            _llm_smoke_result = await gemini_client.smoke_test()
            if _llm_smoke_result["outcome"] == "ok":
                logger.info(
                    "✅ LLM gateway smoke test passed (%dms)",
                    _llm_smoke_result["duration_ms"],
                )
            else:
                logger.error(
                    "⚠️ LLM gateway smoke test FAILED: outcome=%s detail=%s — "
                    "/health will report degraded",
                    _llm_smoke_result["outcome"],
                    _llm_smoke_result["detail"],
                )
        except Exception as e:
            # Defensive: smoke_test promises not to raise, but we don't want a
            # bug here to take down the lifespan and prevent the service from
            # serving /health.
            logger.error("LLM smoke test exploded: %s", e, exc_info=True)
            _llm_smoke_result = {
                "outcome": "unknown_error",
                "duration_ms": 0,
                "detail": f"smoke_test raised: {type(e).__name__}",
            }
    else:
        logger.warning("⚠️ LLM_API_KEY not set — AI analysis unavailable")

    # Initialize OpenProject client
    op_client = OpenProjectClient(base_url=settings.openproject_base_url)
    logger.info("✅ OpenProject client initialized")

    # Initialize Google Chat client (lazy — won't crash if service account missing)
    chat_client = GoogleChatClient(
        service_account_path=settings.google_service_account_json,
    )
    logger.info("✅ Google Chat client configured")

    try:
        from bug_retriever import init_retriever
        init_retriever()
    except ImportError:
        logger.warning("bug_retriever module not importable — RAG disabled")
    except Exception as e:
        logger.error("RAG init unexpected failure: %s", e, exc_info=True)


    logger.info("🚀 Bot is ready!")
    logger.info("=" * 60)

    yield  # App is running

    # Shutdown
    logger.info("Shutting down...")
    await close_database()
    logger.info("Shutdown complete.")


# ─────────────────────────────────────────────
# FastAPI App
# ─────────────────────────────────────────────

app = FastAPI(
    title="QA Bug Logger Bot",
    description="AI-powered bug reporting from Google Chat to OpenProject",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─────────────────────────────────────────────
# Health Check
# ─────────────────────────────────────────────

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Check health of all services."""
    from database import get_last_gcs_sync

    db_ok = await check_database_health()
    # llm_ok is now driven by the startup smoke test outcome, not just whether
    # gemini_client was constructed. A wrong/rotated key produces gemini=auth_error
    # rather than the misleading gemini=configured the deployed code returns.
    llm_outcome: str
    if gemini_client is None:
        llm_outcome = "not_configured"
    elif _llm_smoke_result is None:
        # Should not happen after lifespan completes, but be defensive.
        llm_outcome = "unknown"
    else:
        llm_outcome = _llm_smoke_result["outcome"]
    llm_ok = llm_outcome == "ok"

    # Populate last_gcs_sync snapshot (Theme 2.3 / task 8.2)
    gcs_sync = get_last_gcs_sync()
    gcs_sync_dict = gcs_sync.model_dump(mode="json") if gcs_sync else None

    # Degraded rule: if last GCS sync outcome is not ok or skipped, report degraded
    gcs_ok = gcs_sync is None or gcs_sync.outcome in ("ok", "skipped")
    is_healthy = db_ok and llm_ok and gcs_ok

    return HealthResponse(
        status="healthy" if is_healthy else "degraded",
        database="connected" if db_ok else "disconnected",
        gemini=llm_outcome,
        llm_gateway=settings.llm_base_url,
        llm_model=settings.llm_model,
        openproject=settings.openproject_base_url,
        timestamp=datetime.now(timezone.utc).isoformat(),
        last_gcs_sync=gcs_sync_dict,
        build_marker=_build_marker or None,
    )

@app.get("/logs")
async def get_logs():
    """Return recent logs for debugging."""
    return {"logs": list(_log_capture)}


# ─────────────────────────────────────────────
# User Registration (REST API)
# ─────────────────────────────────────────────

@app.post("/register", response_model=UserRegistrationResponse)
async def register_user(request: UserRegistrationRequest):
    """Register a user via REST API (alternative to /register command)."""
    # Verify the API key with OpenProject
    user_info = await op_client.verify_api_key(request.openproject_api_key)
    if not user_info:
        raise HTTPException(status_code=400, detail="Invalid OpenProject API key")

    # Save to database
    user = await create_or_update_user(
        chat_user_name=request.chat_user_name,
        chat_display_name=request.chat_display_name,
        openproject_api_key=request.openproject_api_key,
        openproject_user_id=str(user_info["id"]),
        openproject_user_name=user_info["name"],
    )

    return UserRegistrationResponse(
        success=True,
        message="Registration successful",
        user_name=user_info["name"],
        user_id=user_info["id"],
    )


# ─────────────────────────────────────────────
# Google Chat Webhook
# ─────────────────────────────────────────────

@app.post("/webhook")
async def webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Handle Google Chat webhook events.
    Supports both:
    - Standard Google Chat App format  {type, message, space}
    - Google Workspace Add-on format   {commonEventObject, chat: {messagePayload, user, space}}
    """
    event = await request.json()
    logger.info(f"Webhook raw keys: {list(event.keys())}")

    # ── Detect Google Workspace Add-on format ──
    addon_chat = event.get("chat", {})
    common = event.get("commonEventObject", {})

    if addon_chat or common:
        # ── Parse Add-on format ──
        addon_event_type = addon_chat.get("type", "MESSAGE")
        msg_payload = addon_chat.get("messagePayload", {}) or {}
        msg_obj = msg_payload.get("message", {}) or {}

        chat_user = addon_chat.get("user", {}) or {}
        sender_name = (
            chat_user.get("name") or 
            msg_obj.get("sender", {}).get("name") or 
            "users/unknown"
        )
        display_name = (
            chat_user.get("displayName") or 
            msg_obj.get("sender", {}).get("displayName") or 
            common.get("userLocale", "User")
        )
        # argumentText is on message object (confirmed from real Google Chat payload)
        text = (
            msg_obj.get("argumentText")
            or msg_obj.get("text")
            or ""
        ).strip()
        attachments = msg_obj.get("attachment", [])
        message_name = msg_obj.get("name", f"addon-msg-{int(time.time())}")
        # space is inside messagePayload (confirmed from real payload)
        space_obj = msg_payload.get("space") or msg_obj.get("space") or {}
        space_name = space_obj.get("name", "")
        space_type = space_obj.get("type", "")
        thread_name = (msg_obj.get("thread") or {}).get("name", "")

        def _addon_response(resp: dict) -> dict:
            return {
                "hostAppDataAction": {
                    "chatDataAction": {
                        "createMessageAction": {
                            "message": resp
                        }
                    }
                }
            }

        logger.info(f"[Add-on] event={addon_event_type} from {display_name} ({sender_name}): {text[:100]}")

        welcome_text = (
            "\U0001f44b **Hi! I'm the AI Bug Logger Bot.**\n\n"
            "I automatically create OpenProject tickets from your bug reports.\n\n"
            "**Quick Start:**\n"
            "1. Register: `/register <your_openproject_api_key>`\n"
            "2. Report a bug: Just send a message with text, screenshots, or videos!\n\n"
            "Type `/help` for more info."
        )

        if addon_event_type == "ADDED_TO_SPACE":
            return _addon_response({"text": welcome_text})

        if addon_event_type not in ("MESSAGE", "UNFURL"):
            return {}

        if _is_duplicate(message_name):
            logger.info(f"Duplicate add-on message ignored: {message_name}")
            return {}

        # Rebuild synthetic event for bug processing
        synthetic_event = {
            "type": "MESSAGE",
            "message": {
                "name": message_name,
                "text": text,
                "sender": {"name": sender_name, "displayName": display_name},
                "attachment": attachments,
                "thread": {"name": thread_name},
            },
            "space": {"name": space_name},
        }

        clean_text = text.lower().strip()
        if clean_text in ["hi", "hello", "hey", "help", "bot", "/help"]:
            return _addon_response(_get_help_response())
        if clean_text.startswith("/register"):
            res = await _handle_register(text, sender_name, display_name)
            return _addon_response(res)
        if clean_text.startswith("/status"):
            res = await _handle_status(sender_name, display_name)
            return _addon_response(res)
        res = await _handle_bug_report(synthetic_event, text, sender_name, display_name, background_tasks)
        return _addon_response(res)

    # ── Standard Google Chat App format ──

    event_type = event.get("type", "")
    logger.info(f"Webhook event received: type={event_type}")

    # ── Bot added to space ──
    if event_type == "ADDED_TO_SPACE":
        return {
            "text": (
                "\U0001f44b **Hi! I'm the AI Bug Logger Bot.**\n\n"
                "I automatically create OpenProject tickets from your bug reports.\n\n"
                "**Quick Start:**\n"
                "1. Register: `/register <your_openproject_api_key>`\n"
                "2. Report a bug: Just send a message with text, screenshots, or videos!\n\n"
                "Type `/help` for more info."
            )
        }

    # ── Only process MESSAGE events ──
    if event_type != "MESSAGE":
        return {}

    message = event.get("message", {})
    sender = message.get("sender", {})
    sender_name = sender.get("name", "")         # e.g. "users/123456789"
    display_name = sender.get("displayName", "User")
    message_name = message.get("name", "")
    
    space = event.get("space", {})
    space_type = space.get("type", "")

    # Get message text (strip bot mentions)
    text = (message.get("text") or "").strip()
    # Remove @mention of the bot (Google Chat includes it in text for spaces)
    if text.startswith("@"):
        parts = text.split(" ", 1)
        text = parts[1].strip() if len(parts) > 1 else ""

    logger.info(f"Message from {display_name} ({sender_name}): {text[:100]}")

    # ── Deduplication ──
    if _is_duplicate(message_name):
        logger.info(f"Duplicate message ignored: {message_name}")
        return {}

    clean_text = text.lower().strip()
    
    # ── Command: /help or Greetings ──
    if clean_text in ["hi", "hello", "hey", "help", "bot", "/help"]:
        return _get_help_response()

    # ── Command: /register ──
    if clean_text.startswith("/register"):
        return await _handle_register(text, sender_name, display_name)

    # ── Command: /status ──
    if clean_text.startswith("/status"):
        return await _handle_status(sender_name, display_name)

    # ── Bug Report ──
    return await _handle_bug_report(event, text, sender_name, display_name, background_tasks)


# ─────────────────────────────────────────────
# Command Handlers
# ─────────────────────────────────────────────

def _get_help_response() -> Dict[str, str]:
    """Return help message."""
    return {
        "text": (
            "🤖 **AI Bug Logger Bot — Help**\n\n"
            "**Commands:**\n"
            "• `/register <api_key>` — Register with your OpenProject API key\n"
            "• `/status` — Check your registration status\n"
            "• `/help` — Show this help message\n\n"
            "**How to Report Bugs:**\n"
            "1. Make sure you're registered (use `/register`)\n"
            "2. Send a message describing the bug\n"
            "3. Attach screenshots, videos, or voice notes\n"
            "4. Bot will automatically create a ticket in OpenProject\n\n"
            "**Supported Formats:**\n"
            "• 📝 Text descriptions\n"
            "• 📸 Screenshots (PNG, JPG)\n"
            "• 🎥 Videos (MP4, MOV)\n"
            "• 🎤 Voice notes\n\n"
            "**Example:**\n"
            "```\n"
            "Login button not working.\n"
            "Device: Samsung Galaxy S23\n"
            "OS: Android 14\n"
            "[Attach screenshot]\n"
            "```\n\n"
            "**Get API Key:**\n"
            "https://project.intermesh.net/my/account → Access tokens"
        )
    }


async def _handle_register(
    text: str, sender_name: str, display_name: str
) -> Dict[str, str]:
    """Handle /register command."""
    # Extract API key from command
    parts = text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        return {
            "text": (
                "⚠️ **Usage:** `/register <your_openproject_api_key>`\n\n"
                "**How to get your API key:**\n"
                "1. Go to https://project.intermesh.net/my/account\n"
                "2. Click on **Access tokens**\n"
                "3. Create a new API token\n"
                "4. Copy the token and use it here"
            )
        }

    api_key = parts[1].strip()

    # Verify with OpenProject
    user_info = await op_client.verify_api_key(api_key)
    if not user_info:
        return {
            "text": (
                "❌ **Registration failed!**\n\n"
                "The API key could not be verified with OpenProject.\n"
                "Please check your key and try again.\n\n"
                "**Get your key at:** https://project.intermesh.net/my/account → Access tokens"
            )
        }

    # Save to database
    await create_or_update_user(
        chat_user_name=sender_name,
        chat_display_name=display_name,
        openproject_api_key=api_key,
        openproject_user_id=str(user_info["id"]),
        openproject_user_name=user_info["name"],
    )

    return {
        "text": (
            "✅ **Registration successful!**\n\n"
            "**Your Details:**\n"
            f"• **Name:** {user_info['name']}\n"
            f"• **OpenProject ID:** {user_info['id']}\n"
            f"• **Google Chat:** {display_name}\n"
            "• **Registered:** Yes ✅\n\n"
            "🎉 You can now start reporting bugs!\n"
            "Just send a message with text, screenshots, or videos."
        )
    }


async def _handle_status(sender_name: str, display_name: str) -> Dict[str, str]:
    """Handle /status command."""
    user = await get_user_by_chat_id(sender_name)

    if user:
        return {
            "text": (
                "✅ **Registration Status: Active**\n\n"
                "**Your Details:**\n"
                f"• **Name:** {user.openproject_user_name or display_name}\n"
                f"• **OpenProject ID:** {user.openproject_user_id or 'N/A'}\n"
                "• **Registered:** Yes ✅\n\n"
                "You can start reporting bugs!"
            )
        }
    else:
        return {
            "text": (
                "❌ **Registration Status: Not Registered**\n\n"
                "You need to register before reporting bugs.\n"
                "Use: `/register <your_openproject_api_key>`\n\n"
                "**Get your key at:** https://project.intermesh.net/my/account → Access tokens"
            )
        }


# ─────────────────────────────────────────────
# Content-based Rejection Detection
# ─────────────────────────────────────────────

# Phrases that indicate the AI recognized the input as NOT a valid bug report,
# even though it returned a full ExtractedBugReport instead of {"is_valid": false}.
_REJECTION_PHRASES = [
    "irrelevant input", "no bug report", "not a bug", "not a valid bug",
    "not a software", "not an app", "no bug found", "no issue found",
    "does not contain", "do not contain", "outdoor scene", "not related to",
    "not a screenshot", "not an app screenshot", "natural photograph",
    "camera photo", "real-world", "no actionable bug", "cannot identify a bug",
    "no software bug", "not related to any software", "unrelated to",
    "not a product screenshot", "random object", "not a screen recording",
]

def _is_rejection_report(report) -> tuple:
    """
    Check if an ExtractedBugReport's content actually indicates the AI
    is rejecting the input (not a real bug), even though it returned
    a full report structure instead of {"is_valid": false}.
    
    Returns (is_rejected: bool, reason: str)
    """
    fields_to_check = [
        getattr(report, 'title', ''),
        getattr(report, 'actual_behavior', ''),
    ]
    for field in fields_to_check:
        field_lower = field.lower() if field else ''
        for phrase in _REJECTION_PHRASES:
            if phrase in field_lower:
                logger.info(f"Rejection detected in report field: '{phrase}' found in '{field[:100]}'")
                return True, field
    return False, ""


# ─────────────────────────────────────────────
# Bug Report Processing
# ─────────────────────────────────────────────

async def _handle_bug_report(
    event: Dict,
    text: str,
    sender_name: str,
    display_name: str,
    background_tasks: BackgroundTasks,
) -> Dict[str, str]:
    """
    Handle bug report processing.

    Strategy:
    - Text-only: Do EVERYTHING inline (Phase 1 + ticket creation) and return result directly.
    - With media: Do Phase 1 inline, fire asyncio.Task for Phase 2 + ticket, return ack now.
    """
    # ── Extract message/space context up front so registration & demo-space
    # fallback logic can reference them safely. (Bug fix: previously
    # space_name was used before assignment.)
    message = event.get("message", {})
    space_name = event.get("space", {}).get("name", "")
    thread_name = message.get("thread", {}).get("name", "")
    attachments = message.get("attachment", [])

    # Check if user is registered, otherwise fallback to space default
    user = await get_user_by_chat_id(sender_name)
    user_api_key = None

    if user:
        user_api_key = user.openproject_api_key
    elif settings.default_openproject_api_key and settings.demo_space_id and settings.demo_space_id in space_name:
        user_api_key = settings.default_openproject_api_key
        logger.info(f"User {display_name} not registered. Falling back to DEFAULT_OPENPROJECT_API_KEY in Demo Space.")
    else:
        return {
            "text": (
                "⚠️ **You are not registered.**\n\n"
                "Please register first with:\n"
                "`/register <your_openproject_api_key>`\n\n"
                "**Get your key at:** https://project.intermesh.net/my/account → Access tokens"
            )
        }

    # Check if LLM is available
    if not gemini_client:
        return {
            "text": "❌ AI service is not configured. Please contact the administrator."
        }
    
    # ── Validate Bug Report Checkpoints ──
    
    # Check 1: Reject link-only messages (URLs with no real description)
    url_pattern = re.compile(r'https?://\S+')
    text_without_urls = url_pattern.sub('', text).strip()
    if text_without_urls and len(text_without_urls) < 15 and not attachments:
        return {
            "text": (
                "⚠️ **Just a link is not enough to raise a bug.**\n\n"
                "Please provide a detailed description along with the link, such as:\n"
                "- What were you doing?\n"
                "- What went wrong?\n"
                "- What was the expected behavior?\n\n"
                "_Example: 'On clicking this link, user gets a 404 error instead of the product page. "
                "Device: Samsung S23, OS: Android 15'_"
            )
        }
    
    # Check 2: Short text with no media
    if len(text.strip()) < 20 and not attachments:
        return {
            "text": (
                "⚠️ **Invalid Bug Report**\n\n"
                "To raise a ticket, you must provide:\n"
                "1. A detailed description (at least 20 characters) with steps, **OR**\n"
                "2. A video or screenshot attachment."
            )
        }
    
    # Check 3: Media-only with no meaningful text — ask for context
    if attachments and len(text.strip()) < 10:
        return {
            "text": (
                "⚠️ **Please provide a brief description along with your media.**\n\n"
                "I can see you've attached media, but I need some context to raise an accurate bug ticket.\n\n"
                "Please resend with a short description, for example:\n"
                "_'Login screen crashes after entering OTP. Device: Samsung S23, OS: Android 15'_\n\n"
                "This helps me correctly identify the **project**, **priority**, and **bug type**."
            )
        }

    start_time = time.time()

    # ── Bucket Routing (Python — no LLM by default) ──
    target_project_id, text_for_llm, routing_provenance = extract_bucket_with_provenance(text)
    logger.info(
        f"Bucket routing: project_id={target_project_id}, "
        f"provenance={routing_provenance}, text_for_llm='{text_for_llm[:80]}'"
    )

    # If deterministic routing fell through to the Android default with no
    # signal anywhere, fall back to a one-shot LLM bucket picker. This catches
    # cases where QA mentions a project by a name we don't have an alias for
    # (audit May 2026 — Model Product Library, Msite SOI, Export, etc.).
    if routing_provenance == "default" and gemini_client is not None and len(text.strip()) >= 20:
        from config import OP_PROJECTS as _OP_PROJECTS
        try:
            picked = await asyncio.wait_for(
                gemini_client.pick_bucket(text, list(_OP_PROJECTS.keys()), timeout_s=6.0),
                timeout=8.0,
            )
        except (asyncio.TimeoutError, Exception) as _e:
            picked = None
            logger.warning("LLM bucket picker fallback failed: %s", _e)
        if picked and picked in _OP_PROJECTS:
            target_project_id = _OP_PROJECTS[picked]
            routing_provenance = "llm_fallback"
            logger.info(
                "Bucket routing: LLM picker → project %s (%d)",
                picked, target_project_id,
            )

    # ── Phase 1: Text analysis (always runs inline, ~5-10s) ──
    try:
        logger.info(f"Phase 1 INLINE: Analyzing text from {display_name}...")
        initial_report = await asyncio.wait_for(
            gemini_client.analyze_text_brief(text_for_llm, project_id=target_project_id),
            timeout=25.0  # Must fit within webhook response window
        )
        elapsed_p1 = round(time.time() - start_time, 1)
        logger.info(f"✅ Phase 1 complete in {elapsed_p1}s: {initial_report.title}")
    except ValidationError as ve:
        logger.error(f"Phase 1 Pydantic validation failed: {ve}", exc_info=True)
        if attachments:
            logger.info("Phase 1 validation failed, but media is present. Using QA text as fallback.")
            initial_report = ExtractedBugReport(
                title=text_for_llm[:120] if len(text_for_llm) > 20 else "Bug reported with media attachment",
                actual_behavior=text_for_llm,
                expected_behavior="Expected behavior not specified. See attached media.",
                steps_to_reproduce=["See attached media for reproduction steps"],
                device="Not specified",
                operating_system="Not specified",
                environment="STAGE",
                app_version="Not specified",
                bug_type="Functional/Logical",
                priority="Medium",
                platform="Android",
                logs_or_links=None
            )
        else:
            return {
                "text": (
                    "❌ **AI Analysis Validation Error**\n\n"
                    "The AI could not properly map the bug fields (like priority or platform) for your description.\n\n"
                    "**Tip:** Try describing the issue with clearer details, or attach a screenshot/video of the bug!"
                )
            }
    except Exception as e:
        logger.error(f"Phase 1 failed: {e}", exc_info=True)
        if attachments:
            logger.info("Phase 1 failed, but media is present. Using QA text as fallback.")
            initial_report = ExtractedBugReport(
                title=text_for_llm[:120] if len(text_for_llm) > 20 else "Bug reported with media attachment",
                actual_behavior=text_for_llm,
                expected_behavior="Expected behavior not specified. See attached media.",
                steps_to_reproduce=["See attached media for reproduction steps"],
                device="Not specified",
                operating_system="Not specified",
                environment="STAGE",
                app_version="Not specified",
                bug_type="Functional/Logical",
                priority="Medium",
                platform="Android",
                logs_or_links=None
            )
        else:
            # Categorise the failure for the user. We never leak raw exception
            # text — that's how SDK internals end up in chat. Map LLMGatewayError
            # outcomes to friendly messages; everything else is the generic case.
            from gemini_client import LLMGatewayError
            if isinstance(e, LLMGatewayError):
                outcome = e.outcome
            else:
                outcome = "unknown_error"
            messages_by_outcome = {
                "auth_error": (
                    "❌ **AI service authentication failed.**\n\n"
                    "The bot's API key has been rejected by the gateway. "
                    "An operator has been alerted (look for `LLM_CALL outcome=auth_error` in /logs). "
                    "Please retry in a few minutes."
                ),
                "rate_limit": (
                    "⏳ **AI service is rate-limited.**\n\n"
                    "Too many requests are queued. Please retry in 30-60 seconds."
                ),
                "server_error": (
                    "🛠️ **AI service is temporarily unavailable.**\n\n"
                    "The gateway returned a 5xx error. Please retry in a few minutes, "
                    "or attach a screenshot/video so I can still raise a ticket."
                ),
                "network_error": (
                    "🌐 **Could not reach AI service.**\n\n"
                    "There was a network issue. Please retry shortly."
                ),
                "unknown_error": (
                    "❌ **Could not analyze your bug report.**\n\n"
                    "Please retry, or attach a screenshot/video so I can raise a ticket "
                    "even if AI analysis is degraded."
                ),
            }
            return {"text": messages_by_outcome.get(outcome, messages_by_outcome["unknown_error"])}

    # ── Check if Phase 1 itself detected irrelevant/non-bug input ──
    is_rejected, rejection_reason = _is_rejection_report(initial_report)
    if is_rejected and not attachments:
        # Text-only and the AI says it's not a bug — reject immediately
        logger.info(f"Phase 1 rejection detected (text-only): {rejection_reason[:100]}")
        return {
            "text": (
                "⚠️ **Not a valid bug report**\n\n"
                "Your message does not appear to describe a software bug.\n\n"
                "**To report a bug, please include:**\n"
                "• A description of what went wrong in the app\n"
                "• Steps to reproduce the issue\n"
                "• Device and OS details (if applicable)\n\n"
                "_Example: 'Login screen crashes after entering OTP. Device: Samsung S23, OS: Android 15'_"
            )
        }

    # ── If NO media: create ticket right now and return the result ──
    if not attachments:
        try:
            logger.info("No media — creating ticket synchronously...")
            ticket = await op_client.create_work_package(initial_report, user_api_key, project_id=target_project_id)
            elapsed = round(time.time() - start_time, 1)
            logger.info(f"✅ Ticket #{ticket['ticket_id']} created in {elapsed}s (text-only)")
            
            return {
                "text": (
                    f"✅ **Bug created successfully!**\n\n"
                    f"**Ticket:** #{ticket['ticket_id']}\n"
                    f"**Project:** {ticket['project']}\n"
                    f"**Title:** {ticket['title']}\n"
                    f"**Bug Type:** {ticket['bug_type']}\n"
                    f"**Priority:** {ticket['priority']}\n\n"
                    f"🔗 **View Ticket:** {ticket['ticket_url']}\n\n"
                    f"⏱️ _Processed in {elapsed}s_"
                )
            }
        except Exception as e:
            logger.error(f"Ticket creation failed: {e}", exc_info=True)
            return {
                "text": f"❌ **Error creating ticket**\n\n**Error:** {str(e)}\n\nPlease try again."
            }

    # ── If HAS media: fire async task for Phase 2 + ticket, return ack now ──
    logger.info(f"Media detected ({len(attachments)} attachments) — launching async task for Phase 2")
    task = asyncio.create_task(
        _process_media_and_create_ticket(
            text=text_for_llm,
            initial_report=initial_report,
            attachments=attachments,
            user_api_key=user_api_key,
            project_id=target_project_id,
            space_name=space_name,
            thread_name=thread_name,
            display_name=display_name,
            start_time=start_time,
        )
    )
    # Prevent the task from being garbage collected mid-execution
    _active_background_tasks.add(task)
    task.add_done_callback(_active_background_tasks.discard)


    return {
        "text": (
            f"🔄 **Processing your bug report, {display_name}...**\n"
            f"📝 Text analysis done: *{initial_report.title}*\n"
            f"📎 Now analyzing {len(attachments)} media attachment(s)...\n"
            f"_You'll receive the ticket link when processing is complete._"
        )
    }


async def _process_media_and_create_ticket(
    text: str,
    initial_report,
    attachments: List[Dict],
    user_api_key: str,
    project_id: int,
    space_name: str,
    thread_name: str,
    display_name: str,
    start_time: float,
) -> None:
    """
    Async task: Download media, run Phase 2 enrichment, create ticket, notify user.
    Runs AFTER webhook has already responded with Phase 1 results.
    """
    MAX_ATTACHMENT_SIZE = 100 * 1024 * 1024  # Increased to 100MB to support videos

    try:
        # ── Download media ──
        media_items = []
        if attachments and chat_client and chat_client.is_available():
            logger.info(f"Found {len(attachments)} attachments in the payload.")
            for idx, att in enumerate(attachments):
                content_type = att.get("contentType", "")
                logger.info(f"Downloading attachment {idx + 1}/{len(attachments)}: {content_type}")
                try:
                    data = await chat_client.download_attachment(att)
                    if data:
                        if len(data) > MAX_ATTACHMENT_SIZE:
                            logger.warning(f"Attachment {idx + 1} too large ({len(data)/1024/1024:.1f} MB), skipping")
                            continue
                        
                        # Ensure filename is unique even if contentName is missing or duplicate
                        fallback_name = f"attachment_{int(time.time())}_{idx}.{content_type.split('/')[-1] if '/' in content_type else 'bin'}"
                        file_name = att.get("contentName") or fallback_name
                        
                        # Add an index prefix if the name already exists in the list to prevent OpenProject collisions
                        existing_names = [m["name"] for m in media_items]
                        if file_name in existing_names:
                            file_name = f"{idx}_{file_name}"

                        media_items.append({"data": data, "mime_type": content_type, "name": file_name})
                        logger.info(f"Downloaded {idx + 1}: {content_type}, {len(data)} bytes, name: {file_name}")
                    else:
                        logger.warning(f"Failed to download attachment {idx + 1}: {content_type}")
                except Exception as dl_err:
                    logger.error(f"Attachment {idx + 1} download error: {dl_err}")
        else:
            logger.warning("Chat API not available or no attachments present")

        # ── Phase 2: Enrich with media & screening ──
        bug_report = initial_report  # fallback
        if media_items:
            try:
                logger.info(f"Phase 2: Enriching with {len(media_items)} media items...")
                enrichment_result = await asyncio.wait_for(
                    gemini_client.enrich_with_media(text, initial_report, media_items, project_id=project_id),
                    timeout=180.0  # 3 minutes max
                )

                # Check if it was rejected during inline screening
                if isinstance(enrichment_result, dict) and not enrichment_result.get("is_valid", True):
                    reason = enrichment_result.get("reason", "The image does not appear to be an app screenshot.")
                    logger.info(f"Content screening REJECTED in Phase 2: {reason}")
                    reject_msg = (
                        f"❌ **Media Rejected: Not a valid bug screenshot/recording**\n\n"
                        f"**Reason:** {reason}\n\n"
                        f"Please send only:\n"
                        f"• App screenshots showing the bug\n"
                        f"• Screen recordings of the bug reproduction\n"
                        f"• Console logs or error messages\n\n"
                        f"_Photos of people, selfies, or non-product images cannot be used for bug reports._"
                    )
                    if chat_client and chat_client.is_available():
                        await asyncio.wait_for(
                            chat_client.send_message(
                                space_name=space_name, text=reject_msg, thread_name=thread_name,
                            ),
                            timeout=10.0,
                        )
                    return  # Stop processing — do NOT create a ticket

                bug_report = enrichment_result
                elapsed_p2 = round(time.time() - start_time, 1)
                logger.info(f"✅ Phase 2 complete in {elapsed_p2}s: {bug_report.title}")

                # Check if Phase 2 embedded rejection text inside the bug report fields
                is_rejected, rejection_reason = _is_rejection_report(bug_report)
                if is_rejected:
                    logger.info(f"Phase 2 content-based rejection detected: {rejection_reason[:100]}")
                    reject_msg = (
                        f"❌ **Media Rejected: Not a valid bug screenshot/recording**\n\n"
                        f"**Reason:** {rejection_reason[:300]}\n\n"
                        f"Please send only:\n"
                        f"• App screenshots showing the bug\n"
                        f"• Screen recordings of the bug reproduction\n"
                        f"• Console logs or error messages\n\n"
                        f"_Photos of people, outdoor scenes, or non-product images cannot be used for bug reports._"
                    )
                    if chat_client and chat_client.is_available():
                        await asyncio.wait_for(
                            chat_client.send_message(
                                space_name=space_name, text=reject_msg, thread_name=thread_name,
                            ),
                            timeout=10.0,
                        )
                    return  # Stop processing — do NOT create a ticket

            except Exception as p2_err:
                logger.error(f"Phase 2 failed ({p2_err}), using Phase 1 result")
                bug_report = initial_report

        # ── Final safety check: ensure the report is genuinely a bug before creating ticket ──
        final_rejected, final_reason = _is_rejection_report(bug_report)
        if final_rejected:
            logger.info(f"Final rejection safety check caught non-bug report: {final_reason[:100]}")
            reject_msg = (
                f"❌ **Not a valid bug report**\n\n"
                f"**Reason:** {final_reason[:300]}\n\n"
                f"Please send only:\n"
                f"• App screenshots showing actual software bugs\n"
                f"• Screen recordings of bug reproduction steps\n"
                f"• A text description of the software issue\n\n"
                f"_Photos of real-world objects, outdoor scenes, or irrelevant text cannot be used for bug reports._"
            )
            if chat_client and chat_client.is_available():
                await asyncio.wait_for(
                    chat_client.send_message(
                        space_name=space_name, text=reject_msg, thread_name=thread_name,
                    ),
                    timeout=10.0,
                )
            return  # Stop — do NOT create a ticket

        # ── Placeholder guard: Don't create ticket if both phases produced no useful content ──
        _PLACEHOLDER_TITLES = [
            "Bug reported — details pending media analysis",
            "Bug reported via media",
            "Bug reported with media attachment",
        ]
        if bug_report.title in _PLACEHOLDER_TITLES:
            logger.warning(f"Both Phase 1 and Phase 2 failed — placeholder report detected, NOT creating ticket")
            fail_msg = (
                "❌ **Could not process your bug report**\n\n"
                "The AI was unable to analyze your text and media. This can happen when:\n"
                "• The server is temporarily overloaded\n\n"
                "**Please try again.** If the issue persists, try without video attachment."
            )
            if chat_client and chat_client.is_available():
                await asyncio.wait_for(
                    chat_client.send_message(
                        space_name=space_name, text=fail_msg, thread_name=thread_name,
                    ),
                    timeout=10.0,
                )
            return  # Stop — do NOT create garbage ticket

        # ── Create ticket ──
        logger.info("Creating OpenProject ticket...")
        ticket = await op_client.create_work_package(bug_report, user_api_key, project_id=project_id)
        elapsed = round(time.time() - start_time, 1)
        logger.info(f"✅ Ticket #{ticket['ticket_id']} created in {elapsed}s")

        # ── Attach files to ticket ──
        if media_items and ticket.get("ticket_id"):
            for item in media_items:
                await op_client.attach_file_to_work_package(
                    ticket_id=ticket["ticket_id"],
                    file_data=item["data"],
                    file_name=item["name"],
                    content_type=item["mime_type"],
                    api_key=user_api_key
                )

        # ── Notify user ──
        success_msg = (
            f"✅ **Bug created successfully!**\n\n"
            f"**Ticket:** #{ticket['ticket_id']}\n"
            f"**Project:** {ticket['project']}\n"
            f"**Title:** {ticket['title']}\n"
            f"**Bug Type:** {ticket['bug_type']}\n"
            f"**Priority:** {ticket['priority']}\n\n"
            f"🔗 **View Ticket:** {ticket['ticket_url']}\n\n"
            f"⏱️ _Processed in {elapsed}s_"
        )
        if chat_client and chat_client.is_available():
            await asyncio.wait_for(
                chat_client.send_message(
                    space_name=space_name,
                    text=success_msg,
                    thread_name=thread_name,
                ),
                timeout=15.0,
            )
            logger.info(f"Success notification sent for ticket #{ticket['ticket_id']}")
        else:
            logger.warning(f"Chat API unavailable — cannot notify. Ticket #{ticket['ticket_id']} was created.")

    except Exception as e:
        elapsed = round(time.time() - start_time, 1)
        logger.error(f"Media processing failed after {elapsed}s: {e}", exc_info=True)

        error_msg = (
            f"❌ **Error processing media for your bug report**\n\n"
            f"**Error:** {str(e)}\n\n"
            f"Please try again without media, or contact the administrator."
        )
        try:
            if chat_client and chat_client.is_available():
                await asyncio.wait_for(
                    chat_client.send_message(
                        space_name=space_name, text=error_msg, thread_name=thread_name,
                    ),
                    timeout=10.0,
                )
        except Exception as send_err:
            logger.error(f"Failed to send error notification: {send_err}")






# ─────────────────────────────────────────────
# Deduplication
# ─────────────────────────────────────────────

def _is_duplicate(message_id: str) -> bool:
    """Check and record a message ID for deduplication."""
    if not message_id:
        return False

    now = time.time()

    # Evict old entries
    while _processed_messages:
        oldest_key, oldest_time = next(iter(_processed_messages.items()))
        if now - oldest_time > DEDUP_TTL_SECONDS:
            _processed_messages.pop(oldest_key)
        else:
            break

    # Check if already processed
    if message_id in _processed_messages:
        return True

    # Record this message
    _processed_messages[message_id] = now
    return False


# ─────────────────────────────────────────────
# Entry Point
# ─────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=settings.port,
        reload=False,
        log_level="info",
    )
