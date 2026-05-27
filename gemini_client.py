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

SYSTEM_PROMPT = """You are an expert QA Bug Report Analyst for IndiaMART.
You MUST respond with valid JSON matching the schema below. No markdown, no explanation.

## JSON SCHEMA
{
  "title": "string — Concise bug title (50-120 chars)",
  "actual_behavior": "string — What actually happens",
  "expected_behavior": "string — What should happen",
  "steps_to_reproduce": ["Step 1", "Step 2", "..."],
  "device": "string — Device model or 'Desktop' or 'Not specified'",
  "operating_system": "string — OS version or 'Not specified'",
  "environment": "string — 'LIVE' or 'STAGE'",
  "app_version": "string — App version or 'Not specified'",
  "bug_type": "string — 'UI/UX' or 'Functional/Logical' or 'Network' or 'Content'",
  "priority": "string — 'High' or 'Medium' or 'Low'",
  "logs_or_links": "string or null"
}

## TITLE
- Pattern: "[Feature/Element] is not [working/shown/clickable] on [screen]"
- Be concise and specific. Do NOT include device/OS in title.

## STEPS TO REPRODUCE
- Use the EXACT steps the tester described. Do not rephrase or add steps they didn't mention.
- Start with "Login as [user_id]" if mentioned, or "Go to [page/URL]"
- End with "Observe that [issue]"
- Typically 3-7 steps

## BUG TYPE (83% are Functional/Logical)
- **Functional/Logical** — Features not working, crashes, errors, blank screens, 404s, wrong behavior, CTA not clickable, data not loading
- **UI/UX** — ONLY for visual/layout issues: alignment, overlapping, cropping, font size, spacing, wrong color
- **Network** — API timeout, 500 errors, connectivity failures
- **Content** — Wrong text, missing labels, typos in UI

## PRIORITY (IMPORTANT — 95% should be Medium)
- **High** — ONLY for: app crashes, complete login failure, payment completely broken, entire feature unavailable (nothing loads at all), data loss
- **Medium** — DEFAULT for most bugs: feature partially broken, specific flow not working, UI issues, wrong behavior in specific scenario, CTA not clickable, wrong data shown, element missing
- **Low** — Minor cosmetic: slight misalignment, minor font issue, edge case affecting very few users

CRITICAL: When in doubt, ALWAYS use "Medium". Do NOT use "High" unless the app literally crashes or an entire critical feature is completely unavailable. A single CTA not working = Medium. A page not loading for one user = Medium. A button misaligned = Low.

## ENVIRONMENT
- Default: "STAGE"
- Only use "LIVE" if tester explicitly says "live", "production", or "Live"

## DEVICE/OS
- Extract from tester's text exactly as written
- If "Desktop" or "Windows" mentioned → device = "Desktop"
- If no device mentioned → "Not specified"

## TERMINOLOGY
BL=Buy Lead, LMS=Lead Manager, BMC=Buyer Message Centre, PDP=Product Detail Page, SOI=Sell on IndiaMART, FCP=Free Content Provider, CTA=Call To Action, OTP=One-Time Password, MCAT=Category, Msite=m.indiamart.com

## RULES
- Respond ONLY with valid JSON
- Do NOT invent information. Use "Not specified" for unknown fields.
- PRESERVE the tester's exact wording for actual/expected behavior
- Priority MUST be "Medium" unless crash/complete failure (High) or pure cosmetic (Low)
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
                enriched_result = await self.enrich_with_media(text, initial_report, media_items)
                if isinstance(enriched_result, dict) and not enriched_result.get("is_valid", True):
                    logger.info("PHASE 2 COMPLETE: Media rejected by inline screening")
                    logger.info("═" * 40)
                    return enriched_result
                logger.info(f"PHASE 2 COMPLETE: {enriched_result.title}")
                logger.info("═" * 40)
                return enriched_result
            except Exception as e:
                logger.error(f"PHASE 2 FAILED, using Phase 1 result: {e}")
                return initial_report

        return initial_report

    async def analyze_text_brief(self, text: str) -> ExtractedBugReport:
        """
        Phase 1: Fast text-only analysis of the QA brief.
        Single attempt, no retries (must complete within 25s webhook deadline).
        Typical response: 3-5 seconds.
        """
        import asyncio

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Analyze the following bug report and extract structured bug data as JSON.\n\nQA Tester's Report:\n{text}"},
        ]

        try:
            loop = asyncio.get_event_loop()

            response = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: self.client.chat.completions.create(
                        model=self.model,
                        messages=messages,
                        response_format={"type": "json_object"},
                        temperature=0.2,
                        max_tokens=1000,
                        timeout=20.0,
                    ),
                ),
                timeout=22.0,
            )

            response_text = response.choices[0].message.content
            logger.info(f"Phase 1 LLM response: {response_text[:300]}")

            cleaned = self._clean_json_response(response_text)
            result_json = json.loads(cleaned)
            return ExtractedBugReport(**result_json)

        except asyncio.TimeoutError:
            logger.error("Phase 1 timed out after 22s")
            raise TimeoutError("Text analysis timed out. Please try again.")
        except json.JSONDecodeError as e:
            logger.error(f"Phase 1 JSON parse failed: {e}")
            raise ValueError(f"AI returned invalid response: {e}")
        except Exception as e:
            logger.error(f"Phase 1 failed: {e}")
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
            "CONTENT SCREENING (quick check):\n"
            "If ALL attached images are natural photographs (people, animals, outdoor, food) with NO software UI visible → respond: {\"is_valid\": false, \"reason\": \"Not a software screenshot\"}\n"
            "Otherwise, proceed with bug analysis below.\n\n"
            
            "You are analyzing screenshots/video frames of a software bug. Respond with valid JSON.\n\n"
            
            "INITIAL TEXT ANALYSIS (from QA tester's brief):\n"
            f"```json\n{initial_json}\n```\n\n"
            f"QA TESTER'S ORIGINAL BRIEF:\n{text}\n\n"
            
            "YOUR TASK — Extract accurate bug data from the MEDIA:\n\n"
            
            "## FOR VIDEO FRAMES (sequential screenshots from screen recording):\n"
            "The frames are in CHRONOLOGICAL ORDER. Each frame is a moment in the bug reproduction.\n"
            "1. FRAME 1: Identify the STARTING screen. Read the page title, navigation state, any visible text.\n"
            "2. FRAME 2-N: For each subsequent frame, identify WHAT CHANGED from the previous frame.\n"
            "   - Did user tap a button? Which one? (read the button text)\n"
            "   - Did a new screen load? What screen?\n"
            "   - Did an error appear? What error text?\n"
            "   - Did a popup/dialog open? What does it say?\n"
            "3. FINAL FRAMES: Identify the BUG STATE — what's wrong in the last frame(s).\n"
            "4. Convert frame transitions into steps_to_reproduce. Each visible action = one step.\n"
            "   ONLY describe actions you can ACTUALLY SEE in frame transitions. Do NOT invent steps.\n\n"
            
            "## FOR SCREENSHOTS (1-3 static images):\n"
            "1. READ all visible text in the image (OCR): page titles, button labels, error messages, URLs in address bar.\n"
            "2. IDENTIFY the screen/page name from header or navigation.\n"
            "3. IDENTIFY what's wrong (the bug) — what looks broken, misaligned, missing, or incorrect.\n"
            "4. If multiple screenshots: describe the flow from image 1 → 2 → 3.\n"
            "5. For desktop screenshots: READ THE URL from the browser address bar.\n\n"
            
            "## DEVICE/OS EXTRACTION:\n"
            "- Mobile: Check the STATUS BAR (top of screen) for time format, icons, signal bars.\n"
            "- Look for device model in Settings screenshots or About screen.\n"
            "- If tester mentioned device/OS in their text, use that.\n\n"
            
            "## OUTPUT JSON (include is_valid: true):\n"
            "{\n"
            '  "is_valid": true,\n'
            '  "title": "Concise bug title based on what you see",\n'
            '  "actual_behavior": "What you observe is wrong in the media",\n'
            '  "expected_behavior": "What should happen instead",\n'
            '  "steps_to_reproduce": ["Step 1 from frame analysis", "Step 2", ...],\n'
            '  "device": "From text or status bar or Not specified",\n'
            '  "operating_system": "From text or UI or Not specified",\n'
            '  "environment": "STAGE or LIVE",\n'
            '  "app_version": "If visible in UI or Not specified",\n'
            '  "bug_type": "UI/UX or Functional/Logical",\n'
            '  "priority": "Medium (default) or High (only if crash/complete failure)",\n'
            '  "logs_or_links": "Any URLs visible in screenshots or null"\n'
            "}\n\n"
            
            "CRITICAL RULES:\n"
            "- steps_to_reproduce must come from what you SEE in frames. Do NOT invent navigation steps.\n"
            "- If you can only see 2 screens, return only 2-3 steps. Do NOT pad with assumed steps.\n"
            "- Use EXACT text visible in UI elements (button names, menu items, error messages).\n"
            "- Priority: Medium unless you see a crash dialog or blank/error screen.\n"
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
            from openai import AuthenticationError, APIConnectionError
            loop = asyncio.get_event_loop()

            # Retry logic for transient gateway auth errors
            max_retries = 2
            for attempt in range(1, max_retries + 1):
                try:
                    # Extended timeout: frames can take time for LLM to analyze
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
                    break  # Success — exit retry loop
                except (AuthenticationError, APIConnectionError) as e:
                    logger.warning(f"Phase 2 transient LLM error (attempt {attempt}/{max_retries}): {e}")
                    if attempt < max_retries:
                        await asyncio.sleep(3)
                        continue
                    else:
                        raise

            response_text = response.choices[0].message.content
            logger.info(f"Phase 2 LLM response: {response_text[:500]}")

            cleaned = self._clean_json_response(response_text)
            result_json = json.loads(cleaned)
            
            # Check if media was rejected by inline screening
            if "is_valid" in result_json and not result_json["is_valid"]:
                return result_json  # Return dictionary to be processed by caller as rejection
                
            return ExtractedBugReport(**result_json)

        except asyncio.TimeoutError:
            logger.error("Phase 2 media analysis timed out after 210s")
            raise TimeoutError("Video analysis timed out. Falling back to text analysis.")
        except json.JSONDecodeError as e:
            logger.error(f"Phase 2 JSON parse failed: {e}")
            # Safety net: if JSON is broken but the AI was clearly trying to reject,
            # extract the rejection gracefully instead of crashing
            try:
                raw = response_text
            except NameError:
                raw = ""
            if raw and "is_valid" in raw.lower() and "false" in raw.lower():
                logger.info("Detected rejection intent in malformed JSON — extracting reason")
                import re
                reason_match = re.search(r'"reason"\s*:\s*"([^"]+)"', raw)
                reason = reason_match.group(1) if reason_match else "The attached image does not appear to be an app screenshot or bug recording."
                return {"is_valid": False, "reason": reason}
            raise ValueError(f"AI returned invalid JSON from media analysis: {e}")
        except Exception as e:
            logger.error(f"Phase 2 media analysis failed: {e}")
            raise

    def _clean_json_response(self, response_text: str) -> str:
        """Clean LLM response to extract valid JSON (strip markdown fences, repair truncation)."""
        cleaned = response_text.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            cleaned = "\n".join(lines)
        
        # Attempt to repair truncated JSON (common issue with LLM gateway)
        cleaned = cleaned.strip()
        if cleaned and not cleaned.endswith("}"):
            # JSON was truncated — try to close it
            # Count open braces/brackets
            open_braces = cleaned.count("{") - cleaned.count("}")
            open_brackets = cleaned.count("[") - cleaned.count("]")
            
            # If we're inside a string (unterminated), close it
            # Find last quote state
            in_string = False
            escape_next = False
            for ch in cleaned:
                if escape_next:
                    escape_next = False
                    continue
                if ch == '\\':
                    escape_next = True
                    continue
                if ch == '"':
                    in_string = not in_string
            
            if in_string:
                cleaned += '"'  # Close the unterminated string
            
            # Close any open arrays
            for _ in range(open_brackets):
                cleaned += "]"
            
            # Close any open objects
            for _ in range(open_braces):
                cleaned += "}"
            
            logger.warning(f"JSON repair applied: closed {open_braces} braces, {open_brackets} brackets, in_string={in_string}")
        
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

                # Extract max 20 frames (as a robust compromise to prevent missing crucial moments while saving time)
                duration_sec = total_frames / fps
                num_frames = min(int(duration_sec), 20)
                num_frames = max(num_frames, 1)  # At least 1 frame

                logger.info(
                    f"Video: {duration_sec:.1f}s @ {fps:.0f}fps, "
                    f"extracting {num_frames} frames (max 20 optimized limit)"
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

    async def screen_media_content(self, media_items: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Pre-screen media to determine if it is a valid app/product screenshot or video.
        Returns {"is_valid": bool, "reason": str}.
        Rejects selfies, people photos, non-product images, memes, etc.
        """
        SCREENING_PROMPT = (
            "You are a content screening gate for a QA Bug Reporting bot at IndiaMART.\n"
            "Your ONLY job is to determine if the attached image(s) are VALID for a bug report.\n\n"
            "VALID content (return is_valid=true):\n"
            "- Mobile app screenshots (any app screen, popup, dialog, error)\n"
            "- Web application screenshots (browser pages, dashboards, forms)\n"
            "- Screen recordings / video frames showing app UI\n"
            "- Console logs, error messages, terminal output\n"
            "- Developer tools / network tabs / API responses\n\n"
            "INVALID content (return is_valid=false):\n"
            "- Photos of people, selfies, group photos\n"
            "- Photos of animals, nature, landscapes\n"
            "- Memes, jokes, stickers, GIFs\n"
            "- Food photos, random objects\n"
            "- Documents/PDFs that are NOT related to software testing\n"
            "- Blank or completely black/white images\n\n"
            "Respond with ONLY valid JSON:\n"
            '{"is_valid": true/false, "reason": "brief explanation"}'
        )

        content_parts = [{"type": "text", "text": "Screen this media. Is it a valid app/product screenshot for a QA bug report?"}]

        # Add first image or first frame of video for screening
        for item in media_items[:1]:  # Only screen the first item for speed
            mime_type = item["mime_type"]
            data = item["data"]

            if mime_type.startswith("image/"):
                b64_data = base64.b64encode(data).decode("utf-8")
                content_parts.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime_type};base64,{b64_data}"},
                })
            elif mime_type.startswith("video/"):
                frames = self._extract_video_frames(data, mime_type)
                if frames:
                    # Just screen the first frame
                    b64_frame = base64.b64encode(frames[0]["data"]).decode("utf-8")
                    content_parts.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:{frames[0]['mime_type']};base64,{b64_frame}"},
                    })
                else:
                    return {"is_valid": True, "reason": "Could not extract video frames for screening, allowing through."}
            else:
                # Audio or unsupported — allow through
                return {"is_valid": True, "reason": "Non-visual media, skipping screen."}

        messages = [
            {"role": "system", "content": SCREENING_PROMPT},
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
                        temperature=0.1,
                        max_tokens=200,
                        timeout=15.0,
                    ),
                ),
                timeout=20.0,
            )
            response_text = response.choices[0].message.content
            logger.info(f"Content screening result: {response_text}")
            cleaned = self._clean_json_response(response_text)
            result = json.loads(cleaned)
            return {"is_valid": result.get("is_valid", True), "reason": result.get("reason", "")}
        except Exception as e:
            logger.error(f"Content screening failed: {e}. Allowing through.")
            return {"is_valid": True, "reason": f"Screening failed ({e}), allowing through."}

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
