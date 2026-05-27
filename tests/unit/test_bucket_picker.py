"""
Tests for the LLM bucket-picker fallback (audit gap closure).

Pins the contract:
- pick_bucket returns one of the candidate names (case-canonicalised) on success.
- Returns None on "NONE" answer, gateway error, or unrecognised answer.
- Never raises. Latency bounded by timeout_s.
- Bucket prose phrasings ("should raise bug in X") route deterministically
  without invoking the LLM.
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from gemini_client import GeminiClient
from bucket_router import (
    extract_bucket_with_provenance,
    _BUCKET_PROSE_RE,
)
from config import OP_PROJECTS


def _make_client_with_text(text: str) -> GeminiClient:
    """Construct a GeminiClient with .client.chat.completions.create stubbed
    to return the given text."""
    client = GeminiClient.__new__(GeminiClient)
    client.client = MagicMock()
    client.model = "test-model"
    fake_resp = MagicMock()
    fake_resp.choices = [MagicMock()]
    fake_resp.choices[0].message.content = text
    client.client.chat.completions.create = MagicMock(return_value=fake_resp)
    return client


def _make_client_that_raises(exc: Exception) -> GeminiClient:
    client = GeminiClient.__new__(GeminiClient)
    client.client = MagicMock()
    client.model = "test-model"
    client.client.chat.completions.create = MagicMock(side_effect=exc)
    return client


# ─── pick_bucket happy path ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_pick_bucket_returns_canonical_when_llm_picks_exact_name():
    client = _make_client_with_text("Desktop Lead Manager")
    result = await client.pick_bucket(
        brief="Chat conversation crashes when buyer types reply on Desktop",
        candidates=list(OP_PROJECTS.keys()),
        timeout_s=2.0,
    )
    assert result == "Desktop Lead Manager"


@pytest.mark.asyncio
async def test_pick_bucket_canonicalises_case():
    """LLM may answer in lowercase — picker must return canonical form."""
    client = _make_client_with_text("photo search")
    result = await client.pick_bucket(
        brief="Image search is broken",
        candidates=list(OP_PROJECTS.keys()),
        timeout_s=2.0,
    )
    assert result == "Photo Search"


@pytest.mark.asyncio
async def test_pick_bucket_strips_quotes_and_trailing_punct():
    """LLM sometimes wraps the answer in quotes or appends a period."""
    client = _make_client_with_text('"Desktop Login".')
    result = await client.pick_bucket(
        brief="OTP failure on desktop login flow",
        candidates=list(OP_PROJECTS.keys()),
        timeout_s=2.0,
    )
    assert result == "Desktop Login"


# ─── pick_bucket negative paths ────────────────────────────────────────

@pytest.mark.asyncio
async def test_pick_bucket_returns_none_on_NONE_answer():
    client = _make_client_with_text("NONE")
    result = await client.pick_bucket(
        brief="something vague",
        candidates=list(OP_PROJECTS.keys()),
        timeout_s=2.0,
    )
    assert result is None


@pytest.mark.asyncio
async def test_pick_bucket_returns_none_on_gateway_error():
    """Auth error / 5xx / timeout — picker must swallow and return None so
    main.py falls back to the deterministic Android default rather than
    crashing the webhook."""
    client = _make_client_that_raises(Exception("HTTP 401 Unauthorized"))
    result = await client.pick_bucket(
        brief="Bug brief",
        candidates=list(OP_PROJECTS.keys()),
        timeout_s=2.0,
    )
    assert result is None


@pytest.mark.asyncio
async def test_pick_bucket_returns_none_for_unrecognised_answer():
    """LLM hallucinates a project that isn't in the candidate list."""
    client = _make_client_with_text("Some Made Up Project")
    result = await client.pick_bucket(
        brief="x",
        candidates=list(OP_PROJECTS.keys()),
        timeout_s=2.0,
    )
    assert result is None


@pytest.mark.asyncio
async def test_pick_bucket_returns_none_on_empty_inputs():
    client = _make_client_with_text("Android")
    assert (await client.pick_bucket("", ["Android"], 2.0)) is None
    assert (await client.pick_bucket("brief", [], 2.0)) is None


# ─── Prose pattern deterministic routing ───────────────────────────────

@pytest.mark.parametrize("brief, expected_in_routed", [
    # The audit screenshot case — "should raised bug in Desktop Lead Manager"
    (
        "[Desktop Lead Manager] Chat conversation crashes when buyer types reply. "
        "Browser: Google Chrome Enviornment: Live ->should raised bug in Desktop Lead Manager.",
        "Desktop Lead Manager",
    ),
    (
        "Bug in BL form. Should create in BL and Enquiry forms project.",
        "BL and Enquiry forms",
    ),
    (
        "Random brief → should be opened in Desktop PDP project. Live env.",
        "Desktop PDP",
    ),
    (
        "Photo Search IM] Upload product image cta is not clickable Browser: Google "
        "Chrome Enviornment: Live device: laptop should raise bug in photo search im bucket",
        "Photo Search",
    ),
    (
        "Bug brief — bucket - Clients Templates",
        "Clients Templates",
    ),
])
def test_prose_phrasings_route_deterministically_no_llm(brief, expected_in_routed):
    """All these phrasings must route to the right project WITHOUT any LLM
    call (provenance == 'tag' or 'freetext')."""
    pid, _, provenance = extract_bucket_with_provenance(brief)
    assert pid == OP_PROJECTS[expected_in_routed], (
        f"expected project_id={OP_PROJECTS[expected_in_routed]} ({expected_in_routed}), "
        f"got pid={pid} provenance={provenance}"
    )
    assert provenance in ("tag", "freetext"), (
        f"expected deterministic routing but got provenance={provenance}"
    )


def test_provenance_default_when_no_signal():
    """A brief with no tag, no prose, no device, no project name must
    surface as 'default' so main.py knows to invoke the LLM picker."""
    pid, _, provenance = extract_bucket_with_provenance(
        "Hello, this is a generic message with no routing signal."
    )
    assert provenance == "default"


def test_provenance_device_when_only_device_mentioned():
    """A brief that mentions a device-keyword but no project alias should
    surface as 'device' provenance."""
    # 'samsung' is in ANDROID_DEVICES but is NOT a PROJECT_ALIASES key,
    # so freetext returns None and Layer 3 device-detection fires.
    pid, _, provenance = extract_bucket_with_provenance(
        "Some bug happened on a Samsung phone."
    )
    assert provenance == "device"
    assert pid == OP_PROJECTS["Android"]
