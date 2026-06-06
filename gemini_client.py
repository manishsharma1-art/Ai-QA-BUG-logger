"""
LLM integration for bug report analysis via OpenAI-compatible API.
Uses IndiaMART LLM Gateway (imllm.intermesh.net) with Gemini 2.5 Flash.
Handles text, images, videos (frame extraction), and audio.
"""

import base64
import json
import logging
from typing import Any, Dict, List, NamedTuple, Optional

from openai import OpenAI

from models import (
    BugType,
    EnvironmentType,
    ExtractedBugReport,
    PlatformType,
    PriorityLevel,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# Phase 2 truncation signal types (Theme 3.3)
# ─────────────────────────────────────────────


class Phase2TruncatedError(Exception):
    """
    Raised by _clean_json_response when the LLM response is missing closing
    tokens (open braces, open brackets, unterminated string).

    Class is named for historical/Theme-3 reasons but applies to BOTH Phase 1
    and Phase 2 — _clean_json_response is shared. The error message is
    phase-agnostic so logs aren't misleading when this fires from Phase 1.

    Should rarely fire in normal operation given max_tokens=6000 (Theme 3.2).
    Both Phase 1 and Phase 2 callers catch this and fall back appropriately.
    """

    def __init__(self, repair_log: List[str], preview: str):
        self.repair_log = repair_log
        self.preview = preview
        super().__init__(f"LLM response truncated: {repair_log}")


class JsonCleanResult(NamedTuple):
    """Return type of `_clean_json_response` on the success path.

    On detected truncation, the function raises `Phase2TruncatedError` instead
    of returning a result, so `was_truncated` is always False on the result
    path and `repair_log` is always empty.
    """

    cleaned: str  # JSON-parseable text after stripping markdown fences
    was_truncated: bool  # always False on the result path (kept for forward-compat)
    repair_log: List[str]  # always empty on the result path


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

    if (
        report.actual_behavior
        in DEFAULT_STUFFING_MARKERS["actual_behavior_placeholders"]
    ):
        reasons.append("b:actual_behavior_placeholder")

    if (
        report.expected_behavior
        in DEFAULT_STUFFING_MARKERS["expected_behavior_placeholders"]
    ):
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

import re as _re
import time as _time


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
    if (
        "ratelimit" in lname
        or "429" in msg
        or "rate limit" in lmsg
        or "too many" in lmsg
    ):
        return "rate_limit"

    # Server-side gateway failure
    if (
        "internalserver" in lname
        or "badgateway" in lname
        or "serviceunavailable" in lname
    ):
        return "server_error"
    if _re.search(r"\b50[0234]\b", msg):
        return "server_error"
    if "internal server error" in lmsg or "service unavailable" in lmsg:
        return "server_error"

    # Network / connection
    if "connection" in lname or "timeout" in lname or "apiconnection" in lname:
        return "network_error"
    if (
        "timed out" in lmsg
        or "connection refused" in lmsg
        or "could not connect" in lmsg
    ):
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
        phase,
        outcome,
        duration_ms,
        detail,
        extra_str,
    )
    return outcome


# ─────────────────────────────────────────────
# System Prompt for Bug Analysis
# ─────────────────────────────────────────────

SYSTEM_PROMPT = """You are an expert QA Bug Report Analyst for IndiaMART mobile and web applications.
You MUST respond with valid JSON matching the schema below. No markdown, no explanation, no commentary.

## JSON SCHEMA (all fields required)
{
  "title": "Concise bug title (50-120 chars). Format: [Feature] does not [work] on [Screen].",
  "actual_behavior": "2-3 sentences: (1) what the user was doing, (2) the unexpected outcome that occurred, (3) any visible error text or UI state. Do NOT simply repeat or lowercase the title.",
  "expected_behavior": "The correct outcome from the user's perspective. Do NOT negate actual_behavior by just adding 'should'. For crashes: describe graceful recovery. For wrong values: state the correct value. For broken CTAs: describe what the tap should trigger.",
  "steps_to_reproduce": ["Step 1", "Step 2", "..."],
  "device": "Device model, or 'Desktop', or 'Not specified'",
  "operating_system": "OS name and version, or 'Not specified'",
  "environment": "'LIVE' or 'STAGE'",
  "app_version": "App version string, or 'Not specified'",
  "bug_type": "'UI/UX' or 'Functional/Logical' or 'Network' or 'Content'",
  "priority": "'High' or 'Medium' or 'Low'",
  "logs_or_links": "URL or log reference, or null"
}

## STEPS TO REPRODUCE

### RULE 1 — STEP 1: LOGIN (with exceptions)
Default: Step 1 = "Login as [account]"
  - Tester gave account ID (e.g. "1002520031") → "Login as 1002520031"
  - Tester gave account type (e.g. "paid seller") → "Login as paid seller account"
  - No account info → "Login as seller" (Android) / "Login as buyer" (iOS buyer context)

Exceptions — do NOT use Login as Step 1 when:
  A) Bug is on the login / OTP / onboarding / sign-up screen → Step 1: "Open the app"
  B) Entry point is a push notification → Step 1: "Tap the [feature] push notification"
  C) Entry point is a deep link / intent URL → Step 1: "Open deep link to [destination]"

NEVER invent an account ID. NEVER copy an account ID from a reference example.

### RULE 2 — STEP 2: NAVIGATION (with exceptions)
Default: Step 2 = "Navigate to [exact screen name]"
  - Use the exact screen name the tester mentioned
  - If screen not mentioned → infer ONLY from the feature name in the bug title

Exceptions — skip or fold navigation into Step 1 when:
  A) Bug is on the login / OTP screen → user is already on the target screen, skip this step
  B) Entry was a notification or deep link → navigation was already covered in Step 1

### RULE 3 — MIDDLE STEPS (exact actions only)
Use ONLY what the tester explicitly stated. Use the tester's exact CTA/button names.
Convert preconditions to steps: "where GST is verified" → "Ensure GST is verified for the account".

KNOWN standard flows you may expand (ONLY when the tester explicitly names the action):
  "Purchase Buy Lead" → ["Tap on any BL card in the listing", "Tap 'Contact Buyer Now' CTA", "On the Subscription Plan screen, tap 'Purchase Buy Lead'"]
  "Send message via BMC" → ["Open Buyer Message Centre", "Tap on any conversation thread", "Type and send a message"]
  "Add/upload product" → ["Navigate to My Products", "Tap 'Add Product'"]

For any action NOT in the list above: do NOT expand. Use only the tester's own words.

### RULE 4 — LAST STEP: OBSERVATION
Always: "Observe that [exact issue from tester's brief]"
Copy the tester's exact wording — do not rephrase or summarize.

### RULE 5 — STEP COUNT
Minimum 2 steps. Maximum 8 steps. Never exceed 8.

### RULE 6 — FORBIDDEN PATTERNS
❌ "Open the app" as a middle or generic step (allowed ONLY for login/onboarding bugs per Rule 1A)
❌ "Go to the page" — use the exact screen name
❌ Any account ID the tester did not provide
❌ CTA names not stated by the tester and not in the known flows above
❌ Steps that describe expected behavior ("Verify that X works correctly")

### RULE 7 — WHEN THE BRIEF IS VAGUE
Write only what you know with certainty:
  Step 1: Login as seller
  Step 2: Navigate to [feature name from title]
  Step 3: Observe that [exact issue]
Do NOT add intermediate steps unless the tester described them.

## HOW TO USE THE REFERENCE TEST CASE (when one appears below)
A matching sanity test case may appear in the context below.
It shows the NORMAL WORKING FLOW for the feature being tested.

When a Reference Test Case is present:
  ✅ Use its exact screen names and CTA names for intermediate steps
  ✅ Use its preconditions to determine the correct "Login as [user type]"
  ✅ Use it to fill in steps the tester abbreviated (e.g. "purchased BL" → expand using test case steps)
  ❌ Do NOT copy its expected outcomes into expected_behavior
  ❌ Do NOT add steps from the test case that come AFTER the point where the bug occurred
  The tester's brief tells you WHERE it broke — that is your last step ("Observe that...")

When NO Reference Test Case is present: use Rule 7 (vague brief fallback).

## PRIORITY & ENVIRONMENT
- High: ONLY for app crash, complete login failure, payment fully broken, data loss.
- Medium: Default for almost all bugs.
- Low: Only for purely cosmetic/visual issues with zero functional impact.
- Environment: Default to "STAGE" unless "live", "production", or "prod" is explicitly mentioned.
"""


# ─────────────────────────────────────────────
# Few-shot examples — loaded once at import time (Theme 7 / audit-driven)
# ─────────────────────────────────────────────
# Source: assets/training_examples_fewshot.json (curated by extract_training.py
# from 611 real OpenProject tickets). Each entry is a real ticket — its
# `subject` and `description_raw` are exactly the format we want the LLM to
# match. We render them as INPUT→JSON pairs so the LLM learns:
#   - Title pattern: "[Feature] is not [working] on [screen]"
#   - Step style: "Login as <user_id>" → "Navigate to ..." → "Observe that ..."
#   - Field discipline: device/OS/environment ALWAYS populated, no placeholders
#   - Priority calibration: ~95% Medium, High only for crashes / data loss
# Capped at 5 examples (~3-4K tokens) to bound Phase 1 latency cost.

import json as _json_for_loader
import re as _re_for_loader
from pathlib import Path as _Path


def _synthesize_qa_brief(example: dict) -> str:
    """
    Real tickets only have output (subject + description). To make the
    few-shot teach 'how to transform messy QA brief → structured JSON',
    we synthesize the kind of compact brief a QA tester would actually type.
    Pattern: subject (title-ish) + minimal device hint, like real /webhook
    inputs we see in production logs.
    """
    subject = (example.get("subject") or "").strip()
    desc = example.get("description_raw") or ""

    # Extract device/OS from the test environment block if present.
    dev = ""
    m = _re_for_loader.search(
        r"\*\*Device:?\*\*[:\s]*([A-Za-z0-9 ]+?)(?:\n|$|\*)",
        desc,
    )
    if m:
        dev = m.group(1).strip()
    os_ver = ""
    m = _re_for_loader.search(
        r"\*\*Operating System:?\*\*[:\s]*([A-Za-z0-9 .]+?)(?:\n|$|\*)",
        desc,
    )
    if m:
        os_ver = m.group(1).strip()

    parts = [subject]
    hint_bits: list[str] = []
    if dev:
        hint_bits.append(dev)
    if os_ver:
        hint_bits.append(os_ver)
    if hint_bits:
        parts.append(" ".join(hint_bits))

    return ". ".join(p for p in parts if p)


def _format_example(example: dict) -> str:
    """Render one example as INPUT→JSON pair for the few-shot block."""
    qa_brief = _synthesize_qa_brief(example)
    desc = example.get("description_raw") or ""

    def _normalise(s: str) -> str:
        """Decode common HTML entities and strip non-breaking-space artifacts
        from the source data so the prompt is clean text."""
        if not s:
            return s
        try:
            import html as _html

            s = _html.unescape(s)
        except Exception:
            pass
        # Strip mojibake/non-breaking artifacts (â\xa0, ┬á, NBSP)
        s = s.replace("\u00a0", " ").replace("\u2002", " ").replace("\u2003", " ")
        s = s.replace("┬á", " ").replace("â\xa0", " ")
        # Collapse runs of whitespace
        s = _re_for_loader.sub(r"[ \t]+", " ", s).strip()
        return s

    # Pull actual_behavior, expected_behavior, steps_to_reproduce from the
    # description_raw markdown so we can reconstruct the JSON the LLM
    # SHOULD produce for this brief.
    def _section(name: str) -> str:
        m = _re_for_loader.search(
            rf"###\s*\*+\s*{name}\s*[:\*]*\s*\n+(.*?)(?=\n###|\Z)",
            desc,
            flags=_re_for_loader.DOTALL | _re_for_loader.IGNORECASE,
        )
        if not m:
            return ""
        body = m.group(1).strip()
        # Strip leading ** wrapping that some entries have
        body = body.strip("*").strip()
        return _normalise(body)

    actual = _section("Actual Behavior") or _normalise(
        example.get("subject", "Not specified")
    )
    expected = _section("Expected Behavior") or "See actual behavior"
    steps_raw = _section("Steps to reproduce")
    # Steps are numbered like "1.  text" — split on numbered lines
    steps = []
    for line in steps_raw.splitlines():
        line = line.strip()
        m = _re_for_loader.match(r"^\d+\.\s*(.+)$", line)
        if m:
            steps.append(_normalise(m.group(1).strip()))
    if not steps:
        steps = ["See description for reproduction steps"]

    # Device + OS extracted earlier
    dev_match = _re_for_loader.search(
        r"\*\*Device:?\*\*[:\s]*([A-Za-z0-9 ]+?)(?:\n|$|\*)",
        desc,
    )
    os_match = _re_for_loader.search(
        r"\*\*Operating System:?\*\*[:\s]*([A-Za-z0-9 .]+?)(?:\n|$|\*)",
        desc,
    )

    output = {
        "title": _normalise((example.get("subject") or ""))[:120],
        "actual_behavior": actual[:400],
        "expected_behavior": expected[:400],
        "steps_to_reproduce": steps[:8],
        "device": (dev_match.group(1).strip() if dev_match else "Not specified"),
        "operating_system": (
            os_match.group(1).strip() if os_match else "Not specified"
        ),
        "environment": (example.get("environment") or "STAGE").upper(),
        "app_version": "Not specified",
        "bug_type": example.get("bug_type") or "Functional/Logical",
        "priority": example.get("priority") or "Medium",
        "logs_or_links": None,
    }
    return (
        f"INPUT (QA brief):\n{qa_brief}\n\n"
        f"OUTPUT (JSON):\n{_json_for_loader.dumps(output, ensure_ascii=False, indent=2)}"
    )


def _load_few_shot_block(max_examples: int = 50) -> str:
    """Load curated few-shot examples and render as a prompt block.

    Returns the formatted block (or empty string if the file is missing /
    corrupt / empty). Never raises. Loaded once at module import time.

    Sources, in priority order:
      1. assets/training_examples.json — full 600-entry curated set
      2. assets/training_examples_fewshot.json — fallback 13-entry set
    """
    candidate_paths = [
        _Path(__file__).parent / "assets" / "training_examples.json",
        _Path(__file__).parent / "assets" / "training_examples_fewshot.json",
    ]
    try:
        path = next((p for p in candidate_paths if p.exists()), None)
        if path is None:
            return ""
        raw = path.read_text(encoding="utf-8-sig")
        examples = _json_for_loader.loads(raw)
        if not isinstance(examples, list) or not examples:
            return ""
        # Filter 1: must have all required fields
        valid = [
            e
            for e in examples
            if e.get("bug_type") and e.get("priority") and e.get("subject")
        ]
        if not valid:
            return ""

        # Filter 2: skip entries with corrupted/noisy content that would teach
        # the LLM bad patterns.
        def _is_quality_example(e: dict) -> bool:
            desc = e.get("description_raw") or ""
            # Skip entries where actual_behavior is just an image attachment URL
            if "<img" in desc or "op-uc-image" in desc:
                return False
            # Skip entries with unfilled template placeholder steps
            dl = desc.lower()
            if any(
                p in dl for p in ("go to page x", "click on button y", "select foo")
            ):
                return False
            # Skip entries with no steps section at all
            if "steps to reproduce" not in dl:
                return False
            return True

        valid = [e for e in valid if _is_quality_example(e)]
        if not valid:
            return ""

        # Pick the first N — extract_training.py already de-duplicated by
        # (project, bug_type, priority) for diversity.
        chosen = valid[:max_examples]
        rendered = [_format_example(e) for e in chosen]
        block = (
            "\n\n## REFERENCE EXAMPLES (real tickets — match this style and discipline)\n\n"
            + "\n\n---\n\n".join(rendered)
        )
        logger.info(
            "Few-shot loaded: %d examples from %s (%d chars)",
            len(chosen),
            path.name,
            len(block),
        )
        return block
    except Exception as e:
        # Never block startup on a malformed examples file.
        logger.warning("Few-shot load failed (%s) — proceeding without examples", e)
        return ""


# Static fallback: 10 diverse examples keep style-anchoring with ~2.5K tokens
# instead of 50 examples (~12K tokens). RAG handles quality retrieval when warm;
# this fallback is only hit on cold start or when the RAG index is unavailable.
_FEW_SHOT_BLOCK = _load_few_shot_block(max_examples=10)
SYSTEM_PROMPT_BASE = SYSTEM_PROMPT
SYSTEM_PROMPT = SYSTEM_PROMPT_BASE + _FEW_SHOT_BLOCK


# ─────────────────────────────────────────────
# Phase 2 — Media Enrichment Prompt
# ─────────────────────────────────────────────
# Template uses str.format() with `initial_json` and `original_brief` substitutions.
# Literal JSON braces are escaped as `{{` and `}}`.
# See design Theme 3.1 for the rationale: all 11 fields MANDATORY, "Not specified"
# fallbacks, no nulls, no empty arrays, no "See attached media for reproduction steps".

PHASE2_PROMPT_TEMPLATE = """\
CONTENT SCREENING (quick check):
If ALL attached images are natural photographs (people, animals, outdoor scenes, food, selfies)
with NO software UI visible anywhere → respond exactly:
  {{"is_valid": false, "reason": "Not a software screenshot"}}
Otherwise proceed with the full bug analysis below.

## TWO-SOURCE TRUTH MODEL
You are a senior QA engineer reviewing a screen recording of a mobile app bug.
The tester sent a text brief AND attached a video or screenshot.
Combine BOTH to produce the most accurate possible bug ticket.

CONFLICT RULE: VIDEO wins for steps_to_reproduce. BRIEF wins for everything else.

TESTER BRIEF (text) owns:
  → account ID (if stated), device, OS, environment, priority
  → title, actual_behavior, expected_behavior

VIDEO / SCREENSHOT owns:
  → steps_to_reproduce (read frames sequentially like a story)
  → exact screen names visible in headers/title bars
  → exact CTA/button text visible in frames
  → error messages / toasts visible in the last frame

## PHASE 1 ANALYSIS (already done from the text brief)
{initial_json}

TESTER'S ORIGINAL BRIEF (verbatim):
{original_brief}

## HOW TO READ THE VIDEO FRAMES
Frames are in CHRONOLOGICAL ORDER. Read them like a silent film.

FRAME 1 — "What screen is the user starting from?" → "Navigate to [screen name in frame 1]"
FRAMES 2 to N-1 — "What did the user just do?" → one step per visible user action
  → Look for: taps, highlighted buttons, new screens, popups, error dialogs
  → Skip frames where nothing changed
LAST FRAME — "What went wrong?" → "Observe that [exact issue / error text visible]"

## STEP CONSTRUCTION FROM VIDEO
Step 1 — Login: Use account ID from brief if given; else "Login as seller" (Android) / "Login as buyer" (iOS)
Step 2 — Navigate to [exact screen name from frame 1]
Middle steps — "Tap on [exact button text] CTA" (one per visible user action)
Last step — "Observe that [exact issue from last frame]"

ANTI-HALLUCINATION:
  ❌ Do NOT write steps for things not visible in any frame
  ❌ Do NOT copy Phase 1 steps if the video shows a different flow
  ✅ Video evidence always overrides Phase 1 for steps

## ACTUAL AND EXPECTED BEHAVIOR (from video evidence)
actual_behavior: Update if the video reveals more detail than the brief.
  Format: (1) what the user did, (2) the unexpected outcome seen in the video, (3) exact error text if any toast/dialog is visible.
expected_behavior: What the feature should do. Refine from Phase 1 if video makes the failure clearer.
  Do NOT just negate actual_behavior. Describe the correct outcome.

## OUTPUT
Respond with exactly this JSON shape, no markdown:
{{
  "is_valid": true,
  "title": "...",
  "actual_behavior": "2-3 sentences: what user did + unexpected outcome + error text seen",
  "expected_behavior": "Correct outcome (not a negation of actual). Describe graceful behavior.",
  "steps_to_reproduce": ["Login as ...", "Navigate to ...", "Tap on ...", "Observe that ..."],
  "device": "from brief or 'Not specified'",
  "operating_system": "from brief or 'Not specified'",
  "environment": "{initial_environment}",
  "app_version": "from brief or 'Not specified'",
  "bug_type": "{initial_bug_type}",
  "priority": "{initial_priority}",
  "logs_or_links": null
}}
"""


def _render_examples_block(examples: list) -> str:
    rendered = [_format_example(e) for e in examples]
    block = (
        "\n\n## REFERENCE EXAMPLES (real tickets — match this style and discipline)\n\n"
        + "\n\n---\n\n".join(rendered)
    )
    return block


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

    def _build_fewshot_block(
        self,
        *,
        query: str,
        project_id: Optional[int],
        phase: str,
    ) -> tuple[str, dict]:
        # ────────────────────────────────────────────────────────────────────────────────
        # Layer A — TestLink reference test case (domain knowledge: how feature WORKS)
        # Retrieves the single most similar sanity test case for the given brief.
        # Placed FIRST in the block so the LLM reads it before the style examples.
        # ────────────────────────────────────────────────────────────────────────────────
        testlink_block = ""
        tl_meta: dict = {"testlink": "unavailable"}
        try:
            from testlink_retriever import get_testlink_retriever

            tl_ret = get_testlink_retriever()
            if tl_ret is not None and tl_ret.is_ready():
                tc = tl_ret.retrieve(query=query)
                if tc:
                    testlink_block = tl_ret.format_for_prompt(tc)
                    tl_meta = {
                        "testlink": "matched",
                        "tc_id": tc["tc_id"],
                        "tc_name": tc["name"][:60],
                        "score": round(tc["score"], 3),
                    }
                    logger.info(
                        "TESTLINK_CONTEXT tc_id=%s score=%.2f name=%r",
                        tc["tc_id"],
                        tc["score"],
                        tc["name"][:60],
                    )
                else:
                    tl_meta = {"testlink": "no_match"}
        except Exception as _tl_err:
            logger.debug("TestLink retriever skipped: %s", _tl_err)

        # ────────────────────────────────────────────────────────────────────────────────
        # Layer B — Bug corpus RAG examples (style + format reference)
        # Top-5 semantically similar past bug tickets showing the expected output format.
        # ────────────────────────────────────────────────────────────────────────────────
        from bug_retriever import get_retriever

        retriever = get_retriever()
        examples = []
        outcome = "index_unavailable"
        if retriever is not None:
            try:
                import os

                top_k = int(os.environ.get("RAG_TOPK", "5"))
                examples = retriever.retrieve(
                    query=query,
                    k=top_k,
                    project_filter=project_id,
                    phase=phase,
                )
                outcome = (
                    getattr(retriever, "_last_retrieve_outcome", "ok")
                    if examples
                    else "empty_corpus"
                )
            except Exception as e:
                logger.warning("RAG_RETRIEVE unexpected raise: %s", e)
                examples = []
                outcome = "embed_error"

        # Determine bug_block and source without overwriting outcome
        # (outcome preserves the retriever's diagnostic: index_unavailable,
        # embed_error, ok, etc. — tests depend on this being unchanged)
        if examples:
            bug_block = _render_examples_block(examples)
            bug_source = "retrieved"
        elif _FEW_SHOT_BLOCK:
            bug_block = _FEW_SHOT_BLOCK
            bug_source = "static"
        else:
            bug_block = ""
            bug_source = "empty"

        combined = testlink_block + bug_block
        return combined, {
            "count": len(examples) if examples else (10 if _FEW_SHOT_BLOCK else 0),
            "outcome": outcome,
            "source": bug_source,
            **tl_meta,
        }

    async def analyze_text_brief(
        self, text: str, project_id: Optional[int] = None
    ) -> ExtractedBugReport:
        """
        Phase 1: Fast text-only analysis of the QA brief.
        Single attempt, no retries (must complete within 25s webhook deadline).
        Typical response: 3-5 seconds.
        """
        import asyncio

        fewshot_block, rag_meta = self._build_fewshot_block(
            query=text, project_id=project_id, phase="phase1"
        )
        system_prompt = SYSTEM_PROMPT_BASE + fewshot_block
        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": f"Analyze the following bug report and extract structured bug data as JSON.\n\nQA Tester's Report:\n{text}",
            },
        ]

        try:
            loop = asyncio.get_running_loop()

            start_ts = _time.time()
            response = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: self.client.chat.completions.create(
                        model=self.model,
                        messages=messages,
                        response_format={"type": "json_object"},
                        temperature=0.2,
                        # 1500 tokens = increased ceiling for Phase 1 JSON output to completely
                        # prevent any truncation risk, giving a huge safety margin.
                        max_tokens=1500,
                        timeout=20.0,
                    ),
                ),
                timeout=22.0,
            )

            response_text = response.choices[0].message.content
            _log_llm_call(
                "phase1",
                start_ts,
                response_chars=len(response_text or ""),
                extra={
                    "rag_examples": rag_meta["count"],
                    "rag_outcome": rag_meta["outcome"],
                    "rag_source": rag_meta["source"],
                },
            )
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
        project_id: Optional[int] = None,
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

        # Build prompt from template.
        # Inject Phase 1 field values so the output template carries them forward
        # rather than defaulting to hardcoded "STAGE" / "Functional/Logical" / "Medium".
        initial_json = initial_report.model_dump_json(indent=2)
        context_prompt = PHASE2_PROMPT_TEMPLATE.format(
            initial_json=initial_json,
            original_brief=text,
            initial_environment=initial_report.environment.value,
            initial_bug_type=initial_report.bug_type.value,
            initial_priority=initial_report.priority.value,
        )
        content_parts.append({"type": "text", "text": context_prompt})

        # Add all media items
        frame_count = 0
        for item in media_items:
            mime_type = item["mime_type"]
            data = item["data"]

            if mime_type.startswith("image/"):
                b64_data = base64.b64encode(data).decode("utf-8")
                content_parts.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime_type};base64,{b64_data}"},
                    }
                )
                frame_count += 1
                logger.info(f"Added image to Phase 2: {mime_type}, {len(data)} bytes")

            elif mime_type.startswith("video/"):
                frames = self._extract_video_frames(data, mime_type)
                for frame in frames:
                    b64_frame = base64.b64encode(frame["data"]).decode("utf-8")
                    content_parts.append(
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{frame['mime_type']};base64,{b64_frame}"
                            },
                        }
                    )
                frame_count += len(frames)
                if frames:
                    content_parts.append(
                        {
                            "type": "text",
                            "text": (
                                f"[Above are {len(frames)} frames extracted at 1fps from a "
                                f"{len(data) / 1024 / 1024:.1f}MB video. Analyze them sequentially "
                                f"to trace the bug reproduction flow step by step.]"
                            ),
                        }
                    )
                logger.info(f"Added {len(frames)} video frames to Phase 2")

            elif mime_type.startswith("audio/"):
                b64_data = base64.b64encode(data).decode("utf-8")
                content_parts.append(
                    {
                        "type": "input_audio",
                        "input_audio": {
                            "data": b64_data,
                            "format": mime_type.split("/")[-1],
                        },
                    }
                )
                logger.info(f"Added audio to Phase 2: {mime_type}, {len(data)} bytes")
            else:
                logger.warning(f"Unsupported media type: {mime_type}")

        logger.info(
            f"Phase 2: Sending {frame_count} visual frames to LLM for detailed analysis"
        )

        fewshot_block, rag_meta = self._build_fewshot_block(
            query=text, project_id=project_id, phase="phase1"
        )
        system_prompt = SYSTEM_PROMPT_BASE + fewshot_block
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": content_parts},
        ]

        import asyncio

        # ── Single attempt, no retries (Theme 3.2) ──
        try:
            loop = asyncio.get_running_loop()
            start_ts = _time.time()
            response = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: self.client.chat.completions.create(
                        model=self.model,
                        messages=messages,
                        response_format={"type": "json_object"},
                        temperature=0.2,
                        # 2000 tokens = safe ceiling for Phase 2 JSON output.
                        # Phase 2 enriches from video frames — steps can be longer,
                        # actual_behavior may include exact error text from frames.
                        # 2000 gives a 4-5× safety margin over observed max (~400 tokens).
                        max_tokens=2000,
                        timeout=45.0,
                    ),
                ),
                timeout=50.0,
            )
            _log_llm_call(
                "phase2",
                start_ts,
                response_chars=len(response.choices[0].message.content or ""),
                extra={
                    "frames": frame_count,
                    "rag_examples": rag_meta["count"],
                    "rag_outcome": rag_meta["outcome"],
                    "rag_source": rag_meta["source"],
                },
            )
        except asyncio.TimeoutError:
            _log_llm_call(
                "phase2",
                start_ts,
                exc=TimeoutError("phase2 wait_for 50s"),
                extra={
                    "frames": frame_count,
                    "rag_examples": rag_meta["count"],
                    "rag_outcome": rag_meta["outcome"],
                    "rag_source": rag_meta["source"],
                },
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
                logger.info(
                    "Detected rejection intent in malformed JSON — extracting reason"
                )
                import re as _re

                reason_match = _re.search(r'"reason"\s*:\s*"([^"]+)"', raw)
                reason = (
                    reason_match.group(1)
                    if reason_match
                    else "The attached image does not appear to be an app screenshot or bug recording."
                )
                return {"is_valid": False, "reason": reason}
            # Fall back to Phase 1 on unparseable JSON
            return initial_report

        # Check if media was rejected by inline screening
        if "is_valid" in result_json and not result_json["is_valid"]:
            return (
                result_json  # Return dictionary to be processed by caller as rejection
            )

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
                detections,
                preview,
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
            import os
            import tempfile

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
                    logger.warning(
                        "Video has 0 frames or unknown FPS, skipping extraction"
                    )
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
                    int(i * total_frames / num_frames) for i in range(num_frames)
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
                        frames.append(
                            {
                                "data": buffer.tobytes(),
                                "mime_type": "image/jpeg",
                            }
                        )

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
            loop = asyncio.get_running_loop()
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
            outcome = _log_llm_call(
                "smoke", start_ts, exc=TimeoutError(f"smoke {timeout_s}s")
            )
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
            loop = asyncio.get_running_loop()
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
                "bucket_picker",
                start_ts,
                response_chars=len(answer),
                extra={"answer": repr(answer[:60])},
            )
        except Exception as e:
            _log_llm_call("bucket_picker", start_ts, exc=e)
            return None

        # Strip trailing punctuation first, THEN enclosing quotes.
        # Order matters: '"Desktop Login".' → rstrip('.') → '"Desktop Login"' → strip('"') → 'Desktop Login'
        answer = answer.strip().rstrip(".,;").strip('"').strip("'")
        if not answer or answer.upper() == "NONE":
            return None

        # Case-insensitive exact match against candidates (the LLM may
        # change case e.g. lowercase "android" → canonical "Android")
        for c in candidates:
            if c.lower() == answer.lower():
                return c

        # No confident match — don't guess
        return None
