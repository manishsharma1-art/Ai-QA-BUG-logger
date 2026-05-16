"""
LLM integration for bug report analysis via OpenAI-compatible API.
Uses IndiaMART LLM Gateway (imllm.intermesh.net) with Gemini 2.5 Flash.
Handles text, images, videos (frame extraction), and audio.
"""

import base64
import json
import logging
from typing import Optional, List, Dict, Any

from openai import OpenAI

from models import (
    ExtractedBugReport, BugType, EnvironmentType,
    PriorityLevel, PlatformType,
)

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# System Prompt for Bug Analysis
# ─────────────────────────────────────────────

SYSTEM_PROMPT = """You are an expert QA Bug Report Analyst for IndiaMART mobile applications (Android and iOS).
You have been trained on 611 real bug reports from the IndiaMART QA team.
You MUST respond with valid JSON matching the schema defined below.

## YOUR TASK
Analyze the provided input (text, screenshots, videos, voice notes) and extract a complete, well-formatted bug report following the exact patterns used by the IndiaMART QA team.

## INPUT SOURCES
- **Text description** from the QA tester
- **Screenshots** — perform OCR and visual analysis to identify UI issues, error messages, device info
- **Videos** — analyze video frames to understand the bug reproduction flow, detect device/OS from UI elements
- **Voice notes** — transcribe and extract bug context

## REQUIRED JSON OUTPUT SCHEMA
{
  "title": "string — Concise, actionable bug title",
  "actual_behavior": "string — What actually happens (the bug behavior observed)",
  "expected_behavior": "string — What should happen instead (the correct behavior)",
  "steps_to_reproduce": ["string — Step 1", "string — Step 2", "..."],
  "device": "string — Device model. Use 'Not specified' if unknown",
  "operating_system": "string — OS and version. Use 'Not specified' if unknown",
  "environment": "string — Must be exactly 'LIVE' or 'STAGE'",
  "app_version": "string — App version if mentioned. Default 'Not specified'",
  "bug_type": "string — Must be exactly one of: 'UI/UX', 'Functional/Logical', 'Network', 'Content', 'Process Correction', 'Transactional'",
  "priority": "string — Must be exactly one of: 'High', 'Medium', 'Low'",
  "platform": "string — Must be exactly 'Android' or 'iOS'",
  "logs_or_links": "string or null — Any log links, Firebase Crashlytics URLs, etc."
}

## TITLE PATTERNS (learned from 611 real bugs)
Titles should be descriptive and follow these patterns:
- "User is unable to [action] on [screen/feature]"
- "Blank screen is shown when [action]"
- "[Feature/Element] is not working/shown/clickable on [screen]"
- "App is crashed when [action]"
- "Getting [error/issue] when [action]"
- "404 error is shown when [navigating/clicking]"
- "[Element] CTA is not [clickable/shown/working] on [screen]"
- Average title length: ~100 characters (range: 27-245)
- Do NOT include device/OS in title unless explicitly mentioned in the report

## ACTUAL BEHAVIOR
- State exactly what goes wrong, matching the tester's description
- Be direct: "App crashes when...", "Blank screen is shown...", "User is unable to..."
- Include additional context like "Replicating Every Time" or "Replicating on both LMS desktop and App" if mentioned

## EXPECTED BEHAVIOR
- State the correct behavior using "should" phrasing
- Pattern: "[Feature] should [correct behavior]"
- Keep concise and mirror the actual behavior description

## STEPS TO REPRODUCE (typical: 3-9 steps, avg 7)
- Start with "Login as [user_id]" or "Login as [user_type]"
- Include specific account IDs when mentioned (e.g., "Login as 1002520031", "Login as 9292006108")
- Include navigation: "Navigate to [screen]", "Open [page]"
- Include actions: "Click on [CTA/button]", "Tap on [element]"
- End with observation: "Observe that [issue]" or "Check [result]"
- Include test server connection if mentioned: "Connect app to test server"

## DEVICE NAMES (from real data)
Common devices used by the QA team:
- Android: iqoo z6, Realme 10 pro plus, IQOO Z9 5g, Motorola g32, Samsung S23, Samsung S23 Ultra, Samsung M21, Realme gt 2, Realme narzo 20 pro
- iOS: Iphone 13, iPhone 13, iphone 16 pro, Iphone 17 pro max
- Use the device name exactly as provided by the tester
- "Desktop/Mobile" is also valid when testing webview features

## OS FORMATS (from real data)
- Android: "Android 15", "android 14", "Android 13", "Android 12", "Android 16"
- iOS: "IOS 26.2", "ios 26", "IOS 18.7", "iOS 26.2"
- Use the format provided by the tester; normalize to "Android XX" or "iOS XX.X"

## ENVIRONMENT
- STAGE (99%+ of bugs are tested on Stage) — default if not explicitly stated
- LIVE — only if explicitly mentioned as "live", "production", or "live environment"

## BUG TYPE CLASSIFICATION (distribution from 611 real bugs)
- **Functional/Logical** (83%) — Most bugs: features not working, wrong behavior, crashes, errors, missing functionality, blank screens, 404 errors, API errors
- **UI/UX** (15%) — Visual/layout issues: alignment problems, trimmed CTAs, missing icons, font issues, UI not updating in real time
- **Network** (<1%) — API failures, timeout, connectivity issues, 500 errors
- **Content** (<1%) — Wrong text, missing labels
- **Process Correction** (<1%) — Workflow/process issues
- **Transactional** (<1%) — Payment/order transaction failures

Key classification rules:
- App crashes → Functional/Logical (NOT UI/UX)
- Blank screen → Functional/Logical
- 404 error → Functional/Logical
- Button not clickable → Functional/Logical (unless it's purely visual)
- CTA not shown → Functional/Logical
- UI alignment issue → UI/UX
- Element trimmed/cut off → UI/UX
- Payment options not working → Functional/Logical (NOT Transactional, unless money/order is involved)

## PRIORITY CLASSIFICATION (from real data: 95% Medium, 5% High)
- **High** — App crashes, login failures, complete feature unavailable (no data loading), payment broken, notifications not received, critical CTAs missing
- **Medium** — Features partially broken, specific flow issues, UI problems, wrong behavior in specific scenarios, specific account issues
- **Low** — Minor cosmetic issues, edge cases, non-critical improvements
- When in doubt, use **Medium** (most common in production data)

## PLATFORM DETECTION
Device → Platform mapping:
- iqoo, IQOO, Realme, realme, Samsung, samsung, Motorola, motorola, Moto, moto, Poco, poco, Redmi, redmi, Xiaomi, OnePlus, Vivo, Oppo, Nothing → **Android**
- iPhone, iphone, Iphone, IPphone, iPad → **iOS**
- "Desktop/Mobile" → infer from project context or QA brief
- If the message mentions "Android" or "iOS" project explicitly, use that

## INDIAMART-SPECIFIC TERMINOLOGY
- BL = Buy Lead (a lead/inquiry from a buyer)
- LMS = Lead Management System (messaging system between buyer and seller)
- BMC = Buyer Message Centre
- PDP = Product Detail Page
- SOI = Sell on IndiaMART (seller onboarding journey)
- CSL = Customer Service Log
- GST = Goods and Services Tax (Indian tax ID verification)
- NPS = Net Promoter Score (feedback popup)
- MDC = Mini Dynamic Catalogue
- CTA = Call To Action (any clickable button or link)
- OTP = One-Time Password
- VPN = Virtual Private Network
- BizFeed = Business Feed (activity feed)
- Webview = Web-based pages rendered inside the native app
- XMPP = Messaging protocol (for real-time messages)
- Tender = A type of Buy Lead
- EMPFCP = Employee Free Content Provider (account type)
- Blocker popup = A popup that blocks user from proceeding (e.g., GST verification)
- Context menu = 3-dot menu in top-right corner
- APK = Android Package (app file)
- IPA = iOS App file
- GLid = Global Lead ID (account identifier)
- T1/S1 build = Test/Stage build version

## REAL BUG EXAMPLES (from production data)

### Example 1 — Functional/Logical, Medium, Android
Input: "Blocker pop-up is not coming on the tender listing when a tender is consumed through gmail deeplinking. Device: IQOO Z9 5g, OS: Android 15"
Output:
{
  "title": "Blocker pop-up is not coming on the tender listing when an tender is consumed through gmail deeplinking.",
  "actual_behavior": "Blocker pop-up is not coming on the tender listing when an tender is consumed through gmail deeplinking.",
  "expected_behavior": "Blocker pop-up should come on the tender listing when an tender is consumed through gmail deeplinking.",
  "steps_to_reproduce": ["Login as 1204501254 whose gst is not verified and pan is not provided", "Navigate to tender mailer.", "Consume any tender.", "Observe that the blocker pop-up is not coming."],
  "device": "IQOO Z9 5g",
  "operating_system": "Android 15",
  "environment": "STAGE",
  "app_version": "Not specified",
  "bug_type": "Functional/Logical",
  "priority": "Medium",
  "platform": "Android",
  "logs_or_links": null
}

### Example 2 — UI/UX, Medium, iOS
Input: "The UI alignment issue in the post-call popup on Buyer Pages. Device: Iphone 13, OS: IOS 26.2"
Output:
{
  "title": "The UI alignment issue in the post-call popup on Buyer Pages.",
  "actual_behavior": "On the Buyer pages, a UI issue is observed in the Post-Call popup displayed after a call is attempted or completed.",
  "expected_behavior": "The Post-Call popup on Buyer pages should render correctly with proper alignment, spacing, and there should be no half-trimmed CTAs",
  "steps_to_reproduce": ["Login from the Buyer", "Open the Buyer pages (Search, PDP, Company and Impcat)", "Initiate a call to a seller from the Buyer page.", "End the call and observe the Post-Call popup that appears on the screen.", "The post call pop up seems trimmed on the No CTA"],
  "device": "Iphone 13",
  "operating_system": "IOS 26.2",
  "environment": "STAGE",
  "app_version": "Not specified",
  "bug_type": "UI/UX",
  "priority": "Medium",
  "platform": "iOS",
  "logs_or_links": null
}

### Example 3 — Functional/Logical, High, Android (Crash)
Input: "App crashes when clicking WhatsApp CTA on Edit Product screen"
Output:
{
  "title": "App crashes when clicking WhatsApp CTA on Edit Product screen",
  "actual_behavior": "App crashes when clicking WhatsApp CTA on Edit Product screen",
  "expected_behavior": "When clicking WhatsApp CTA on Edit Product screen user should be able to share product on whatsapp.",
  "steps_to_reproduce": ["Login as seller", "Navigate to My Products", "Open edit product page for any product", "Click on WhatsApp CTA", "Observe app crash"],
  "device": "Not specified",
  "operating_system": "Not specified",
  "environment": "STAGE",
  "app_version": "Not specified",
  "bug_type": "Functional/Logical",
  "priority": "High",
  "platform": "Android",
  "logs_or_links": null
}

### Example 4 — Functional/Logical, High, Android (Login)
Input: "Auto fetch of OTP is not working on the login OTP screen."
Output:
{
  "title": "Auto fetch of OTP is not working on the login OTP screen.",
  "actual_behavior": "Auto fetch of OTP is not working on the login OTP screen.",
  "expected_behavior": "OTP should be auto fetched on the login screen.",
  "steps_to_reproduce": ["Login as user (9292006108)", "Click on next", "Lands on OTP screen", "Observe that OTP is not auto-fetched"],
  "device": "Not specified",
  "operating_system": "Not specified",
  "environment": "STAGE",
  "app_version": "Not specified",
  "bug_type": "Functional/Logical",
  "priority": "High",
  "platform": "Android",
  "logs_or_links": null
}

### Example 5 — Functional/Logical, Medium, iOS
Input: "The Logout, Logout from All Devices, and Disable Account Options Not Clickable in Context Menu on Settings Webview. Device: Iphone 13, OS: IOS 26.2"
Output:
{
  "title": "The Logout, Logout from All Devices, and Disable Account Options Not Clickable in Context Menu on Settings Webview.",
  "actual_behavior": "The Logout, Logout from All Devices, and Disable Account Options are not clickable in the context menu on Settings Webview.",
  "expected_behavior": "Each option should be fully clickable and responsive. Selecting any option should trigger the respective action.",
  "steps_to_reproduce": ["Login from any seller/buyer account", "Navigate to Settings page in the app", "Open the context menu (3-dot menu)", "Try clicking on Logout, Logout from All Devices, or Disable Account", "Observe that none of the options respond to tap"],
  "device": "Iphone 13",
  "operating_system": "IOS 26.2",
  "environment": "STAGE",
  "app_version": "Not specified",
  "bug_type": "Functional/Logical",
  "priority": "High",
  "platform": "iOS",
  "logs_or_links": null
}

## CRITICAL RULES
- Respond ONLY with valid JSON — no markdown, no code fences, no explanation.
- All string values in the JSON must be properly escaped.
- Follow the schema exactly. Do not add extra fields.
- Match the writing style and tone of the real IndiaMART QA team examples above.
- When information is missing, use "Not specified" — do NOT invent device names or OS versions.
- Default environment to "STAGE" unless explicitly stated otherwise.
- Default priority to "Medium" unless clear indicators for High (crash, login, payment, data loss) or Low (minor cosmetic).
"""


class GeminiClient:
    """
    LLM client for bug analysis via OpenAI-compatible API.
    Uses IndiaMART LLM Gateway with Gemini 2.5 Flash.
    """

    def __init__(self, api_key: str, base_url: str, model: str):
        """Initialize the OpenAI-compatible LLM client."""
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = model
        logger.info(f"LLM client initialized: model={model}, base_url={base_url}")

    async def analyze_bug_report(
        self,
        text: str,
        media_items: Optional[List[Dict[str, Any]]] = None,
    ) -> ExtractedBugReport:
        """
        Two-phase bug report analysis:
        Phase 1: Analyze QA text brief (fast, ~5-10s)
        Phase 2: Enrich with media evidence (if media exists, ~30-120s for video)

        If Phase 2 fails, falls back to Phase 1 result so a ticket is always created.
        """
        # Phase 1: Text-only analysis (always runs first)
        logger.info("═" * 40)
        logger.info("PHASE 1: Analyzing QA text brief...")
        initial_report = await self.analyze_text_brief(text)
        logger.info(f"PHASE 1 COMPLETE: {initial_report.title}")
        logger.info("═" * 40)

        # Phase 2: Media enrichment (only if media exists)
        if media_items:
            logger.info("═" * 40)
            logger.info(f"PHASE 2: Enriching with {len(media_items)} media items...")
            try:
                enriched_report = await self.enrich_with_media(text, initial_report, media_items)
                logger.info(f"PHASE 2 COMPLETE: {enriched_report.title}")
                logger.info("═" * 40)
                return enriched_report
            except Exception as e:
                logger.error(f"PHASE 2 FAILED, using Phase 1 result: {e}")
                return initial_report

        return initial_report

    async def analyze_text_brief(self, text: str) -> ExtractedBugReport:
        """
        Phase 1: Fast text-only analysis of the QA brief.
        Completes in ~5-10 seconds with no media processing.
        """
        content_parts = [
            {"type": "text", "text": (
                "Analyze the following bug report TEXT and extract structured bug data as JSON.\n\n"
                f"QA Tester's Report:\n{text}"
            )}
        ]

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": content_parts},
        ]

        try:
            import asyncio
            loop = asyncio.get_event_loop()

            response = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: self.client.chat.completions.create(
                        model=self.model,
                        messages=messages,
                        response_format={"type": "json_object"},
                        temperature=0.2,
                        max_tokens=2000,
                        timeout=30.0,
                    ),
                ),
                timeout=45.0,
            )

            response_text = response.choices[0].message.content
            logger.info(f"Phase 1 LLM response: {response_text[:300]}")

            cleaned = self._clean_json_response(response_text)
            result_json = json.loads(cleaned)
            return ExtractedBugReport(**result_json)

        except asyncio.TimeoutError:
            logger.error("Phase 1 text analysis timed out after 45s")
            raise TimeoutError("Text analysis timed out. Please try again.")
        except json.JSONDecodeError as e:
            logger.error(f"Phase 1 JSON parse failed: {e}")
            raise ValueError(f"AI returned invalid JSON: {e}")
        except Exception as e:
            logger.error(f"Phase 1 analysis failed: {e}")
            raise

    async def enrich_with_media(
        self,
        text: str,
        initial_report: ExtractedBugReport,
        media_items: List[Dict[str, Any]],
    ) -> ExtractedBugReport:
        """
        Phase 2: Enrich bug report using video frames and screenshots.

        Sends the Phase 1 text analysis + all media to the LLM so it can:
        - Verify and correct the text-based analysis against visual evidence
        - Extract device/OS info from status bars
        - Improve steps_to_reproduce from the sequential video flow
        - Detect additional UI details not mentioned in the text
        """
        content_parts = []

        # Provide Phase 1 context so LLM knows what to look for
        initial_json = initial_report.model_dump_json(indent=2)
        context_prompt = (
            "You previously analyzed a bug report text and produced this initial analysis:\n"
            f"```json\n{initial_json}\n```\n\n"
            f"Original QA Brief:\n{text}\n\n"
            "Now analyze the attached media (video frames / screenshots) to:\n"
            "1. Watch frames SEQUENTIALLY — they show the bug reproduction steps in order\n"
            "2. VERIFY and CORRECT the initial analysis based on visual evidence\n"
            "3. EXTRACT device model, OS version, app version from status bars or UI\n"
            "4. IMPROVE steps_to_reproduce with specific details visible in the frames\n"
            "5. UPDATE title and descriptions if the media reveals more specific details\n\n"
            "Respond with the COMPLETE updated bug report JSON following the exact same schema.\n"
        )
        content_parts.append({"type": "text", "text": context_prompt})

        # Add all media items
        frame_count = 0
        for item in media_items:
            mime_type = item["mime_type"]
            data = item["data"]

            if mime_type.startswith("image/"):
                b64_data = base64.b64encode(data).decode("utf-8")
                content_parts.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime_type};base64,{b64_data}"},
                })
                frame_count += 1
                logger.info(f"Added image to Phase 2: {mime_type}, {len(data)} bytes")

            elif mime_type.startswith("video/"):
                frames = self._extract_video_frames(data, mime_type)
                for frame in frames:
                    b64_frame = base64.b64encode(frame["data"]).decode("utf-8")
                    content_parts.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:{frame['mime_type']};base64,{b64_frame}"},
                    })
                frame_count += len(frames)
                if frames:
                    content_parts.append({
                        "type": "text",
                        "text": (
                            f"[Above are {len(frames)} frames extracted at 1fps from a "
                            f"{len(data)/1024/1024:.1f}MB video. Analyze them sequentially "
                            f"to trace the bug reproduction flow step by step.]"
                        ),
                    })
                logger.info(f"Added {len(frames)} video frames to Phase 2")

            elif mime_type.startswith("audio/"):
                b64_data = base64.b64encode(data).decode("utf-8")
                content_parts.append({
                    "type": "input_audio",
                    "input_audio": {
                        "data": b64_data,
                        "format": mime_type.split("/")[-1],
                    },
                })
                logger.info(f"Added audio to Phase 2: {mime_type}, {len(data)} bytes")
            else:
                logger.warning(f"Unsupported media type: {mime_type}")

        logger.info(f"Phase 2: Sending {frame_count} visual frames to LLM for detailed analysis")

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": content_parts},
        ]

        try:
            import asyncio
            loop = asyncio.get_event_loop()

            # Extended timeout: 120 frames can take time for LLM to analyze
            response = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: self.client.chat.completions.create(
                        model=self.model,
                        messages=messages,
                        response_format={"type": "json_object"},
                        temperature=0.2,
                        max_tokens=2000,
                        timeout=180.0,  # 3 min client timeout for video
                    ),
                ),
                timeout=210.0  # 3.5 min overall timeout
            )

            response_text = response.choices[0].message.content
            logger.info(f"Phase 2 LLM response: {response_text[:500]}")

            cleaned = self._clean_json_response(response_text)
            result_json = json.loads(cleaned)
            return ExtractedBugReport(**result_json)

        except asyncio.TimeoutError:
            logger.error("Phase 2 media analysis timed out after 210s")
            raise TimeoutError("Video analysis timed out. Falling back to text analysis.")
        except json.JSONDecodeError as e:
            logger.error(f"Phase 2 JSON parse failed: {e}")
            raise ValueError(f"AI returned invalid JSON from media analysis: {e}")
        except Exception as e:
            logger.error(f"Phase 2 media analysis failed: {e}")
            raise

    def _clean_json_response(self, response_text: str) -> str:
        """Clean LLM response to extract valid JSON (strip markdown fences, etc.)."""
        cleaned = response_text.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            cleaned = "\n".join(lines)
        return cleaned

    def _extract_video_frames(
        self, video_data: bytes, mime_type: str
    ) -> List[Dict[str, Any]]:
        """
        Extract frames from a video at 2 frames per second for detailed analysis.
        Max 120 frames (covers up to 60s of video).
        Each frame is resized to 480px width and 50% JPEG quality for fast transfer.
        """
        frames = []

        try:
            import tempfile
            import os

            # Write video to temp file
            ext = {
                "video/mp4": ".mp4",
                "video/quicktime": ".mov",
                "video/webm": ".webm",
                "video/3gpp": ".3gp",
            }.get(mime_type, ".mp4")

            with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
                tmp.write(video_data)
                tmp_path = tmp.name

            try:
                # Try using cv2 (opencv) if available
                import cv2

                cap = cv2.VideoCapture(tmp_path)
                total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                fps = cap.get(cv2.CAP_PROP_FPS)

                if total_frames <= 0 or fps <= 0:
                    logger.warning("Video has 0 frames or unknown FPS, skipping extraction")
                    return frames

                # Extract 1 frame per second, max 30 frames
                # 30 frames is enough for LLM to see every step of a bug reproduction
                # More than ~30 images causes LLM gateway payload issues
                duration_sec = total_frames / fps
                num_frames = min(int(duration_sec), 30)
                num_frames = max(num_frames, 1)  # At least 1 frame

                logger.info(
                    f"Video: {duration_sec:.1f}s @ {fps:.0f}fps, "
                    f"extracting {num_frames} frames (1fps, max 30)"
                )

                # Extract evenly spaced frames
                frame_indices = [
                    int(i * total_frames / num_frames)
                    for i in range(num_frames)
                ]

                for idx in frame_indices:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
                    ret, frame = cap.read()
                    if ret:
                        # Resize to 480px width to keep payload manageable
                        height, width = frame.shape[:2]
                        if width > 480:
                            scale = 480 / width
                            new_width = 480
                            new_height = int(height * scale)
                            frame = cv2.resize(frame, (new_width, new_height))

                        # 50% JPEG quality — small but readable for LLM
                        _, buffer = cv2.imencode(
                            ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 50]
                        )
                        frames.append({
                            "data": buffer.tobytes(),
                            "mime_type": "image/jpeg",
                        })

                cap.release()
                logger.info(f"Extracted {len(frames)} frames from video using OpenCV")

            except ImportError:
                logger.warning(
                    "OpenCV not available. Video will be described from text only. "
                    "Install opencv-python-headless for video frame extraction."
                )
            finally:
                os.unlink(tmp_path)

        except Exception as e:
            logger.error(f"Video frame extraction failed: {e}")

        return frames

    async def check_health(self) -> bool:
        """Check if LLM API is accessible."""
        try:
            import asyncio
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self.client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": "Reply with: OK"}],
                    max_tokens=10,
                ),
            )
            return bool(response.choices[0].message.content)
        except Exception as e:
            logger.error(f"LLM health check failed: {e}")
            return False
