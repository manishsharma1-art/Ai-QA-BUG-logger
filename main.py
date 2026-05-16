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
from database import (
    init_database, close_database, check_database_health,
    get_user_by_chat_id, create_or_update_user,
)
from gemini_client import GeminiClient
from openproject_client import OpenProjectClient
from google_auth import GoogleChatClient
from models import (
    UserRegistrationRequest, UserRegistrationResponse,
    HealthResponse,
)

import collections

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



# ─────────────────────────────────────────────
# App Lifecycle
# ─────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize services on startup, clean up on shutdown."""
    global gemini_client, op_client, chat_client

    logger.info("=" * 60)
    logger.info("QA Bug Logger Bot — Starting up...")
    logger.info("=" * 60)

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
    db_ok = await check_database_health()
    llm_ok = gemini_client is not None

    return HealthResponse(
        status="healthy" if (db_ok and llm_ok) else "degraded",
        database="connected" if db_ok else "disconnected",
        gemini="configured" if llm_ok else "not configured",
        llm_gateway=settings.llm_base_url,
        llm_model=settings.llm_model,
        openproject=settings.openproject_base_url,
        timestamp=datetime.now(timezone.utc).isoformat(),
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
        thread_name = (msg_obj.get("thread") or {}).get("name", "")

        logger.info(f"[Add-on] event={addon_event_type} from {display_name} ({sender_name}): {text[:100]}")

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

    message = event.get("message", {})
    space_name = event.get("space", {}).get("name", "")
    thread_name = message.get("thread", {}).get("name", "")
    attachments = message.get("attachment", [])
    
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

    # ── Phase 1: Text analysis (always runs inline, ~5-10s) ──
    try:
        logger.info(f"Phase 1 INLINE: Analyzing text from {display_name}...")
        initial_report = await asyncio.wait_for(
            gemini_client.analyze_text_brief(text),
            timeout=25.0  # Must fit within webhook response window
        )
        elapsed_p1 = round(time.time() - start_time, 1)
        logger.info(f"✅ Phase 1 complete in {elapsed_p1}s: {initial_report.title}")
    except Exception as e:
        logger.error(f"Phase 1 failed: {e}", exc_info=True)
        return {
            "text": f"❌ **Error analyzing your bug report**\n\n**Error:** {str(e)}\n\nPlease try again."
        }

    # ── If NO media: create ticket right now and return the result ──
    if not attachments:
        try:
            logger.info("No media — creating ticket synchronously...")
            ticket = await op_client.create_work_package(initial_report, user_api_key)
            elapsed = round(time.time() - start_time, 1)
            logger.info(f"✅ Ticket #{ticket['ticket_id']} created in {elapsed}s (text-only)")
            return {
                "text": (
                    f"✅ **Bug created successfully!**\n\n"
                    f"**Ticket:** #{ticket['ticket_id']}\n"
                    f"**Project:** {ticket['project']}\n"
                    f"**Title:** {ticket['title']}\n"
                    f"**Bug Type:** {ticket['bug_type']}\n"
                    f"**Priority:** {ticket['priority']}\n"
                    f"**Platform:** {ticket['platform']}\n\n"
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
            text=text,
            initial_report=initial_report,
            attachments=attachments,
            user_api_key=user_api_key,
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
    space_name: str,
    thread_name: str,
    display_name: str,
    start_time: float,
) -> None:
    """
    Async task: Download media, run Phase 2 enrichment, create ticket, notify user.
    Runs AFTER webhook has already responded with Phase 1 results.
    """
    MAX_ATTACHMENT_SIZE = 20 * 1024 * 1024

    try:
        # ── Download media ──
        media_items = []
        if attachments and chat_client and chat_client.is_available():
            for att in attachments:
                content_type = att.get("contentType", "")
                logger.info(f"Downloading attachment: {content_type}")
                try:
                    data = await chat_client.download_attachment(att)
                    if data:
                        if len(data) > MAX_ATTACHMENT_SIZE:
                            logger.warning(f"Attachment too large ({len(data)} bytes), skipping")
                            continue
                        file_name = att.get("contentName", f"attachment_{int(time.time())}.{content_type.split('/')[-1] if '/' in content_type else 'bin'}")
                        media_items.append({"data": data, "mime_type": content_type, "name": file_name})
                        logger.info(f"Downloaded: {content_type}, {len(data)} bytes")
                    else:
                        logger.warning(f"Failed to download attachment: {content_type}")
                except Exception as dl_err:
                    logger.error(f"Attachment download error: {dl_err}")
        else:
            logger.warning("Chat API not available for attachment download")

        # ── AI Content Screening Gate ──
        if media_items and gemini_client:
            try:
                screening = await asyncio.wait_for(
                    gemini_client.screen_media_content(media_items),
                    timeout=25.0,
                )
                if not screening.get("is_valid", True):
                    reason = screening.get("reason", "The image does not appear to be an app screenshot.")
                    logger.info(f"Content screening REJECTED: {reason}")
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
                else:
                    logger.info(f"Content screening PASSED: {screening.get('reason', 'OK')}")
            except Exception as screen_err:
                logger.error(f"Content screening error: {screen_err}. Allowing through.")

        # ── Phase 2: Enrich with media ──
        bug_report = initial_report  # fallback
        if media_items:
            try:
                logger.info(f"Phase 2: Enriching with {len(media_items)} media items...")
                bug_report = await asyncio.wait_for(
                    gemini_client.enrich_with_media(text, initial_report, media_items),
                    timeout=180.0  # 3 minutes max
                )
                elapsed_p2 = round(time.time() - start_time, 1)
                logger.info(f"✅ Phase 2 complete in {elapsed_p2}s: {bug_report.title}")
            except Exception as p2_err:
                logger.error(f"Phase 2 failed ({p2_err}), using Phase 1 result")
                bug_report = initial_report

        # ── Create ticket ──
        logger.info("Creating OpenProject ticket...")
        ticket = await op_client.create_work_package(bug_report, user_api_key)
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
            f"**Priority:** {ticket['priority']}\n"
            f"**Platform:** {ticket['platform']}\n\n"
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
