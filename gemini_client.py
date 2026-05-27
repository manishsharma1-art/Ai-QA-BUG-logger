"""
LLM integration for bug report analysis via OpenAI-compatible API.
Uses IndiaMART LLM Gateway (imllm.intermesh.net) with Gemini 2.5 Flash.
Handles text, images, videos (frame extraction), and audio.
"""

import base64
import json
import logging
from typing import Optional, List, Dict, Any, NamedTuple

from openai import OpenAI

from models import (
    ExtractedBugReport, BugType, EnvironmentType,
    PriorityLevel, PlatformType,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# Phase 2 truncation signal types (Theme 3.3)
# ─────────────────────────────────────────────


class Phase2TruncatedError(Exception):
    """
    Raised by _clean_json_response when the LLM response is missing closing
    tokens (open braces, open brackets, unterminated string).

    Should NEVER fire in normal operation given max_tokens=6000 (Theme 3.2).
    If it does, it indicates a gateway / prompt regression that ops MUST
    investigate. The caller in enrich_with_media catches this and falls
    back to the Phase 1 result (Theme 3.3).
    """
    def __init__(self, repair_log: List[str], preview: str):
        self.repair_log = repair_log
        self.preview = preview
        super().__init__(f"Phase 2 response truncated: {repair_log}")


class JsonCleanResult(NamedTuple):
    """Return type of `_clean_json_response` on the success path.

    On detected truncation, the function raises `Phase2TruncatedError` instead
    of returning a result, so `was_truncated` is always False on the result
    path and `repair_log` is always empty.
    """
    cleaned: str            # JSON-parseable text after stripping markdown fences
    was_truncated: bool     # always False on the result path (kept for forward-compat)
    repair_log: List[str]   # always empty on the result path


# ─────────────────────────────────────────────
# Default-stuffing detector (Theme 3.4 — defense in depth)
# ─────────────────────────────────────────────
# Constants encode the placeholder strings the LLM is told to never emit.
# If the LLM does emit them, _detect_default_stuffing reports the situation
# so enrich_with_media can fall back to the Phase 1 result.

DEFAULT_STUFFING_MARKERS = {
    "steps_to_reproduce_placeholders": {
        "See attached media for reproduction steps",
        "Review attached media",
    },
    "actual_behavior_placeholders": {
        "See attached media for details.",
    },
    "expected_behavior_placeholders": {
        "Expected normal behavior.",
    },
}


def _detect_default_stuffing(report: ExtractedBugReport) -> tuple[bool, list[str]]:
    """
    Decide whether the report is so default-laden that it would produce a useless ticket.

    Returns:
        (is_stuffed, reasons)

    is_stuffed is True iff at least 2 of the following hold:
        a) steps_to_reproduce equals or is a subset of the placeholder set
        b) actual_behavior is in the placeholder set
        c) expected_behavior is in the placeholder set
        d) device == "Not specified" AND operating_system == "Not specified"
           AND app_version == "Not specified"

    reasons is the list of (a)..(d) labels that fired.
    Pure function; no side effects, no logging.
    """
    reasons: list[str] = []

    steps_set = set(report.steps_to_reproduce or [])
    if steps_set and steps_set.issubset(
        DEFAULT_STUFFING_MARKERS["steps_to_reproduce_placeholders"]
    ):
        reasons.append("a:steps_to_reproduce_placeholder")

    if report.actual_behavior in DEFAULT_STUFFING_MARKERS["actual_behavior_placeholders"]:
        reasons.append("b:actual_behavior_placeholder")

    if report.expected_behavior in DEFAULT_STUFFING_MARKERS["expected_behavior_placeholders"]:
        reasons.append("c:expected_behavior_placeholder")

    if (
        report.device == "Not specified"
        and report.operating_system == "Not specified"
        and report.app_version == "Not specified"
    ):
        reasons.append("d:all_device_fields_blank")

    return (len(reasons) >= 2, reasons)


# ─────────────────────────────────────────────
# LLM_CALL gateway observability (Phase 1 + Phase 2 wrapper)
# ─────────────────────────────────────────────
# Mirrors OP_CALL in openproject_client.py. Five outcomes — every gateway
# call (Phase 1, Phase 2, smoke test, content screen) emits exactly one
# `LLM_CALL phase=… outcome=… duration_ms=…` line so /logs greppable.

import time as _time
import re as _re


class LLMGatewayError(Exception):
    """Categorised gateway error. The .outcome attribute is one of:
    auth_error | rate_limit | server_error | network_error | unknown_error.
    .retry_after_s is populated for rate_limit when the gateway sends one.
    """

    def __init__(self, outcome: str, message: str, retry_after_s: Optional[int] = None):
        self.outcome = outcome
        self.retry_after_s = retry_after_s
        super().__init__(message)


def _classify_gateway_exception(exc: BaseException) -> str:
    """
    Map an arbitrary exception raised by the OpenAI SDK / httpx into one of
    the five LLM_CALL outcomes. Pure function. Best-effort — we use duck
    typing because the openai SDK's exception classes are version-specific.
    """
    name = type(exc).__name__
    lname = name.lower()
    msg = str(exc)
    lmsg = msg.lower()

    # Auth errors first — these are unrecoverable and ops-actionable
    if "authentication" in lname or "permission" in lname:
        return "auth_error"
    if "authentication" in lmsg or "unauthorized" in lmsg or "forbidden" in lmsg:
        return "auth_error"
    if "401" in msg or "403" in msg:
        return "auth_error"
    if "invalid api key" in lmsg or "invalid_api_key" in lmsg:
        return "auth_error"

    # Rate limit
    if "ratelimit" in lname or "429" in msg or "rate limit" in lmsg or "too many" in lmsg:
        return "rate_limit"

    # Server-side gateway failure
    if "internalserver" in lname or "badgateway" in lname or "serviceunavailable" in lname:
        return "server_error"
    if _re.search(r"\b50[0234]\b", msg):
        return "server_error"
    if "internal server error" in lmsg or "service unavailable" in lmsg:
        return "server_error"

    # Network / connection
    if "connection" in lname or "timeout" in lname or "apiconnection" in lname:
        return "network_error"
    if "timed out" in lmsg or "connection refused" in lmsg or "could not connect" in lmsg:
        return "network_error"

    return "unknown_error"


def _log_llm_call(
    phase: str,
    start_ts: float,
    *,
    response_chars: int = 0,
    exc: Optional[BaseException] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Emit a single structured LLM_CALL log line.

    phase: 'phase1' | 'phase2' | 'smoke' | 'screen'
    Returns the outcome string for the caller to use in fall-back decisions.
    """
    duration_ms = int((_time.time() - start_ts) * 1000)
    if exc is None:
        outcome = "ok"
        detail = f"chars={response_chars}"
        level = logging.INFO
    else:
        outcome = _classify_gateway_exception(exc)
        # Truncate detail to keep log lines bounded
        msg = str(exc).replace('"', "'")
        if len(msg) > 200:
            msg = msg[:197] + "..."
        detail = f'{type(exc).__name__}="{msg}"'
        level = logging.WARNING if outcome != "unknown_error" else logging.ERROR

    extra_str = ""
    if extra:
        extra_str = " " + " ".join(f"{k}={v}" for k, v in extra.items())
    logger.log(
        level,
        "LLM_CALL phase=%s outcome=%s duration_ms=%d %s%s",
        phase, outcome, duration_ms, detail, extra_str,
    )
    return outcome


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


# ─────────────────────────────────────────────
# Phase 2 — Media Enrichment Prompt
# ─────────────────────────────────────────────
# Template uses str.format() with `initial_json` and `original_brief` substitutions.
# Literal JSON braces are escaped as `{{` and `}}`.
# See design Theme 3.1 for the rationale: all 11 fields MANDATORY, "Not specified"
# fallbacks, no nulls, no empty arrays, no "See attached media for reproduction steps".

PHASE2_PROMPT_TEMPLATE = """\
CONTENT SCREENING (quick check):
If ALL attached images are natural photographs (people, animals, outdoor, food) with NO software
UI visible → respond exactly:
  {{"is_valid": false, "reason": "Not a software screenshot"}}
Otherwise, proceed with bug analysis below.

You are analyzing screenshots/video frames of a software bug. Respond with valid JSON.

INITIAL TEXT ANALYSIS (from QA tester's brief):
{initial_json}

QA TESTER'S ORIGINAL BRIEF (kept verbatim, including any [Tag] prefix):
{original_brief}

YOUR TASK — Produce a JSON object with ALL 11 fields below. No field may be omitted.
If a value is genuinely unknown, output the literal string "Not specified" for string fields,
or the array ["Not specified"] for steps_to_reproduce. NEVER output an empty array, NEVER
output null for a required field, NEVER output the placeholder
"See attached media for reproduction steps".

MANDATORY FIELDS (in this exact order, all required):
  1.  is_valid              — boolean, must be true here (false is only used by the screening branch above)
  2.  title                 — string, 50-120 chars, "[Element] is not [working] on [screen]"
  3.  actual_behavior       — string, what is wrong in the media (read the UI text)
  4.  expected_behavior     — string, what should happen instead
  5.  steps_to_reproduce    — non-empty array of strings, ONE step per visible action in the
                              frames. If only 2-3 frames are visible, output 2-3 steps. Never
                              pad. Never output the placeholder string above.
  6.  device                — exact device model from status bar / settings / brief, else "Not specified"
  7.  operating_system      — exact OS string, else "Not specified"
  8.  environment           — "STAGE" (default) or "LIVE" (only if tester said live/prod)
  9.  app_version           — visible app version, else "Not specified"
  10. bug_type              — one of "UI/UX","Functional/Logical","Network","Content"
  11. priority              — one of "High","Medium","Low" (default Medium — see PRIORITY rules)

PRIORITY RULES (the LLM has the final say within these rules — they are a floor, not an override):
  - Default to "High" when the brief contains any of: "hangs", "hang", "hanging",
    "crashes", "crash", "crashing", "stuck", "stuck on", "freezes", "frozen",
    "blank screen", "white screen", "black screen", "not responsive", "unresponsive",
    "not responding", "broken", "completely failing", "data loss", "fatal", "severe"
    — UNLESS context clearly indicates the issue is rare/recoverable, in which case
    you may downgrade to "Medium".
  - Default to "Low" when the brief contains any of: "intermittent", "intermittently",
    "sometimes", "occasionally", "rarely", "minor", "cosmetic", "trivial", "nit",
    "slight misalignment", "slightly" — UNLESS the underlying symptom is severe (e.g.
    "intermittent crash on payment" can still be "High" if the impact is bad enough).
  - When BOTH a HIGH and a LOW keyword appear in the same brief (e.g. "intermittent
    crash"), USE YOUR JUDGEMENT based on user impact and frequency. The validator
    will tie-break to "Medium" with an audit log if you don't pick.
  - Otherwise → "Medium" (the safe default).
  - "High" is also still warranted for: app crash dialog visible, full login broken,
    payments fully broken, entire feature unavailable, data loss observed.
  - "Low" is also still warranted for: purely cosmetic issues (alignment, font, spacing).
  - When in doubt, "Medium".

OUTPUT — exactly this JSON shape, no markdown, no commentary:
{{
  "is_valid": true,
  "title": "...",
  "actual_behavior": "...",
  "expected_behavior": "...",
  "steps_to_reproduce": ["...", "..."],
  "device": "...",
  "operating_system": "...",
  "environment": "STAGE",
  "app_version": "...",
  "bug_type": "Functional/Logical",
  "priority": "Medium",
  "logs_or_links": null
}}
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

            start_ts = _time.time()
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
            _log_llm_call("phase1", start_ts, response_chars=len(response_text or ""))
            logger.info(f"Phase 1 LLM response: {response_text[:300]}")

            cleaned = self._clean_json_response(response_text)
            result_json = json.loads(cleaned)
            return ExtractedBugReport(**result_json)

        except asyncio.TimeoutError:
            _log_llm_call("phase1", start_ts, exc=TimeoutError("phase1 wait_for 22s"))
            logger.error("Phase 1 timed out after 22s")
            raise LLMGatewayError("network_error", "Text analysis timed out") from None
        except json.JSONDecodeError as e:
            logger.error(f"Phase 1 JSON parse failed: {e}")
            raise ValueError(f"AI returned invalid response: {e}") from e
        except LLMGatewayError:
            raise
        except Exception as e:
            outcome = _log_llm_call("phase1", start_ts, exc=e)
            logger.error(f"Phase 1 failed (outcome={outcome}): {e}")
            raise LLMGatewayError(outcome, str(e)) from e

    async def enrich_with_media(
        self,
        text: str,
        initial_report: ExtractedBugReport,
        media_items: List[Dict[str, Any]],
    ) -> ExtractedBugReport:
        """
        Phase 2: Enrich bug report using video frames and screenshots.

        Uses PHASE2_PROMPT_TEMPLATE with max_tokens=6000 (Theme 3.2).
        Three fall-back paths — all return initial_report, NO RETRIES:
          1. Phase2TruncatedError → log + return initial_report
          2. asyncio.TimeoutError → log PHASE2_SLOW + return initial_report
          3. Default-stuffing detected → log PHASE2_DEFAULT_STUFFED + return initial_report
        """
        content_parts = []

        # Build prompt from template (Theme 3.1)
        initial_json = initial_report.model_dump_json(indent=2)
        context_prompt = PHASE2_PROMPT_TEMPLATE.format(
            initial_json=initial_json,
            original_brief=text,
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

        import asyncio

        # ── Single attempt, no retries (Theme 3.2) ──
        try:
            loop = asyncio.get_event_loop()
            start_ts = _time.time()
            response = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: self.client.chat.completions.create(
                        model=self.model,
                        messages=messages,
                        response_format={"type": "json_object"},
                        temperature=0.2,
                        max_tokens=6000,       # Theme 3.2: 3× safety multiplier
                        timeout=45.0,          # Theme 3.2: client timeout
                    ),
                ),
                timeout=50.0  # Theme 3.2.1: asyncio.wait_for timeout
            )
            _log_llm_call(
                "phase2", start_ts,
                response_chars=len(response.choices[0].message.content or ""),
                extra={"frames": frame_count},
            )
        except asyncio.TimeoutError:
            _log_llm_call(
                "phase2", start_ts,
                exc=TimeoutError("phase2 wait_for 50s"),
                extra={"frames": frame_count},
            )
            # Fall-back path 2: timeout → return Phase 1 result
            logger.error(
                "PHASE2_SLOW outcome=timeout duration_ms=50000 frames=%d",
                frame_count,
            )
            return initial_report
        except Exception as e:
            _log_llm_call("phase2", start_ts, exc=e, extra={"frames": frame_count})
            logger.error(f"Phase 2 LLM call failed: {e}")
            return initial_report

        response_text = response.choices[0].message.content
        logger.info(f"Phase 2 LLM response: {response_text[:500]}")

        # ── Parse response ──
        try:
            cleaned = self._clean_json_response(response_text)
        except Phase2TruncatedError:
            # Fall-back path 1: truncation → return Phase 1 result
            return initial_report

        try:
            result_json = json.loads(cleaned)
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
                import re as _re
                reason_match = _re.search(r'"reason"\s*:\s*"([^"]+)"', raw)
                reason = reason_match.group(1) if reason_match else "The attached image does not appear to be an app screenshot or bug recording."
                return {"is_valid": False, "reason": reason}
            # Fall back to Phase 1 on unparseable JSON
            return initial_report

        # Check if media was rejected by inline screening
        if "is_valid" in result_json and not result_json["is_valid"]:
            return result_json  # Return dictionary to be processed by caller as rejection

        enriched_report = ExtractedBugReport(**result_json)

        # ── Fall-back path 3: default-stuffing check ──
        is_stuffed, reasons = _detect_default_stuffing(enriched_report)
        if is_stuffed:
            logger.error("PHASE2_DEFAULT_STUFFED reasons=%s", reasons)
            return initial_report

        return enriched_report

    def _clean_json_response(self, response_text: str) -> str:
        """
        Strip markdown fences from an LLM JSON response. Detect truncation and
        raise Phase2TruncatedError instead of silently repairing.

        Theme 3.3: With max_tokens=6000, truncation is unexpected. If we observe
        unbalanced braces/brackets or an unterminated string, that's a load-bearing
        alert — log at ERROR and raise. The caller in enrich_with_media falls back
        to the Phase 1 result.

        Returns: the cleaned JSON string (parseable by json.loads).
        Raises:  Phase2TruncatedError on detected truncation.
        """
        cleaned = (response_text or "").strip()

        # Strip markdown fences
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            cleaned = "\n".join(lines).strip()

        if not cleaned:
            # Empty response is a truncation symptom
            detections = ["empty response"]
            logger.error(
                'PHASE2_TRUNCATED detections=%s preview=""',
                detections,
            )
            raise Phase2TruncatedError(detections, preview="")

        # Detect truncation
        open_braces = cleaned.count("{") - cleaned.count("}")
        open_brackets = cleaned.count("[") - cleaned.count("]")

        # Unterminated-string scan (handles backslash-escapes)
        in_string = False
        escape_next = False
        for ch in cleaned:
            if escape_next:
                escape_next = False
                continue
            if ch == "\\":
                escape_next = True
                continue
            if ch == '"':
                in_string = not in_string

        was_truncated = (open_braces > 0) or (open_brackets > 0) or in_string

        if was_truncated:
            detections: List[str] = []
            if in_string:
                detections.append("unterminated string")
            if open_brackets > 0:
                detections.append(f"open arrays={open_brackets}")
            if open_braces > 0:
                detections.append(f"open objects={open_braces}")
            preview = cleaned[-200:]
            logger.error(
                "PHASE2_TRUNCATED detections=%s preview=%r",
                detections, preview,
            )
            raise Phase2TruncatedError(detections, preview=preview)

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
        """Check if LLM API is accessible. Kept for backwards compatibility."""
        result = await self.smoke_test()
        return result["outcome"] == "ok"

    async def smoke_test(self, timeout_s: float = 8.0) -> Dict[str, Any]:
        """
        One-token health probe of the gateway. Designed to run at startup so
        that an invalid/expired/rotated key is caught BEFORE any user-facing
        webhook is processed.

        Returns a dict with keys:
          outcome: 'ok' | 'auth_error' | 'rate_limit' | 'server_error' |
                   'network_error' | 'unknown_error'
          duration_ms: int
          detail: str (short, log-safe)

        Never raises.
        """
        import asyncio
        start_ts = _time.time()
        try:
            loop = asyncio.get_event_loop()
            response = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: self.client.chat.completions.create(
                        model=self.model,
                        messages=[{"role": "user", "content": "ping"}],
                        max_tokens=1,
                        timeout=timeout_s,
                    ),
                ),
                timeout=timeout_s + 2.0,
            )
            chars = len(response.choices[0].message.content or "")
            _log_llm_call("smoke", start_ts, response_chars=chars)
            return {
                "outcome": "ok",
                "duration_ms": int((_time.time() - start_ts) * 1000),
                "detail": f"chars={chars}",
            }
        except asyncio.TimeoutError as e:
            outcome = _log_llm_call("smoke", start_ts, exc=TimeoutError(f"smoke {timeout_s}s"))
            return {
                "outcome": outcome,
                "duration_ms": int((_time.time() - start_ts) * 1000),
                "detail": "timeout",
            }
        except Exception as e:
            outcome = _log_llm_call("smoke", start_ts, exc=e)
            return {
                "outcome": outcome,
                "duration_ms": int((_time.time() - start_ts) * 1000),
                "detail": f"{type(e).__name__}",
            }

    async def pick_bucket(
        self,
        brief: str,
        candidates: List[str],
        timeout_s: float = 6.0,
    ) -> Optional[str]:
        """
        LLM bucket-picker fallback (audit gap closure).

        Called by main.py ONLY when deterministic routing in bucket_router
        falls through to the default (provenance == "default"), e.g. when
        a QA brief mentions a project name we don't have an alias for.

        Returns the canonical project name (one of `candidates`) or None
        if the LLM can't pick one with confidence. Never raises.

        Cost: one extra ~1-2s gateway call only on the rare default-fallback
        path. Latency is bounded by `timeout_s`. On any gateway failure the
        function returns None so the caller falls back to the deterministic
        Android default.
        """
        import asyncio

        if not brief or not candidates:
            return None

        # Trim candidate list to a sane size for prompt economy
        candidate_block = "\n".join(f"- {c}" for c in candidates[:80])

        prompt = (
            "You are routing a bug report to one of the OpenProject projects "
            "below. Read the brief and pick the SINGLE canonical project name "
            "that best matches the QA tester's intent.\n\n"
            "RULES:\n"
            "- Reply with ONLY the canonical name from the list, exactly as written.\n"
            "- If the brief is too vague to pick confidently, reply with the "
            "single word: NONE\n"
            "- Do NOT invent project names. Do NOT add commentary.\n\n"
            f"PROJECTS:\n{candidate_block}\n\n"
            f"BRIEF:\n{brief}\n\n"
            "ANSWER:"
        )

        start_ts = _time.time()
        try:
            loop = asyncio.get_event_loop()
            response = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: self.client.chat.completions.create(
                        model=self.model,
                        messages=[{"role": "user", "content": prompt}],
                        max_tokens=40,
                        temperature=0.0,
                        timeout=timeout_s,
                    ),
                ),
                timeout=timeout_s + 2.0,
            )
            answer = (response.choices[0].message.content or "").strip()
            _log_llm_call(
                "bucket_picker", start_ts,
                response_chars=len(answer),
                extra={"answer": repr(answer[:60])},
            )
        except Exception as e:
            _log_llm_call("bucket_picker", start_ts, exc=e)
            return None

        # Strip common trailing punctuation/quotes the LLM may add
        answer = answer.strip().strip('"').strip("'").rstrip(".,;")
        if not answer or answer.upper() == "NONE":
            return None

        # Case-insensitive exact match against candidates (the LLM may
        # change case e.g. lowercase "android" → canonical "Android")
        for c in candidates:
            if c.lower() == answer.lower():
                return c

        # Best-effort substring match (e.g. answer "Photo Search IM" → "Photo Search")
        for c in candidates:
            if c.lower() in answer.lower() or answer.lower() in c.lower():
                if len(c) >= 4 and len(answer) >= 4:
                    return c

        # No confident match
        return None
