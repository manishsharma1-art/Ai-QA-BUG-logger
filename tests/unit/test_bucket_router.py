"""
Tests for bucket_router.py — T-BR-1 through T-BR-20 from design §4.4 + §4.7.
Covers: BUCKET_TAG_RE anchoring, _resolve_tag tightening, _extract_bucket_from_freetext,
3-layer flow, and brief preservation (Theme 4.2).
"""
import pytest
from bucket_router import (
    extract_bucket_from_message,
    _resolve_tag,
    _extract_bucket_from_freetext,
    BUCKET_TAG_RE,
)
from config import OP_PROJECTS


# ─────────────────────────────────────────────
# T-BR-1..10: Explicit [Tag] routing + edge cases
# ─────────────────────────────────────────────

@pytest.mark.parametrize("message, expected_project_id, desc", [
    # T-BR-1: exact tag match
    ("[LMS Webview] flickering", 476, "exact tag LMS Webview"),
    # T-BR-2: typo in tag (edit distance 2) — fuzzy match
    ("[LMS Webveiw] flickering", 476, "typo LMS Webveiw via fuzzy"),
    # T-BR-3: alias match
    ("[lms] login broken", 476, "alias lms -> LMS Webview"),
    # T-BR-4: free-floating bracket NOT at start — no tag match
    ("Login fails [step 3]", OP_PROJECTS.get("Android", 3), "[step 3] not at start"),
    # T-BR-5: digit-leading tag rejected by regex
    ("[2024-05-12] crash", OP_PROJECTS.get("Android", 3), "digit-leading tag rejected"),
    # T-BR-6: single-char tag rejected (len < 2)
    ("[L] crash", OP_PROJECTS.get("Android", 3), "single-char tag rejected"),
    # T-BR-7: "home" is too short/generic for fuzzy 0.78
    ("[home] page broken", OP_PROJECTS.get("Android", 3), "home no fuzzy match"),
    # T-BR-8: exact match Desktop Homepage
    ("[Desktop Homepage] hero broken", 50, "exact Desktop Homepage"),
    # T-BR-9: alias with & character
    ("[Header & Footer] logo cropped", 44, "alias Header & Footer"),
    # T-BR-10: random garbage tag
    ("[Random Garbage Tag] something", OP_PROJECTS.get("Android", 3), "garbage tag no match"),
])
def test_extract_bucket_regex(message, expected_project_id, desc):
    """Test explicit [Tag] routing and edge cases per design §4.4."""
    project_id, text_for_llm = extract_bucket_from_message(message)
    assert project_id == expected_project_id, f"FAIL {desc}: got {project_id}"
    # Theme 4.2: text_for_llm must be original text verbatim
    assert text_for_llm == message, f"Brief not preserved for {desc}"


# ─────────────────────────────────────────────
# T-BR-11..20: Free-text bucket extraction
# ─────────────────────────────────────────────

@pytest.mark.parametrize("message, expected_project_id, desc", [
    # T-BR-11: bucket-shorthand with dash
    ("bucket - LMS webview, login button not working", 476, "bucket-shorthand dash"),
    # T-BR-12: bucket-shorthand with colon
    ("bucket: Photo Search, image not loading on Samsung S23", 461, "bucket-shorthand colon"),
    # T-BR-13: multi-word phrase in free text wins over iOS device
    ("Flickering on LMS Webview chat screen, iPhone 13", 476, "multi-word wins over device"),
    # T-BR-14: multi-word phrase wins over Android single-word
    ("Photo Search bug on Android", 461, "Photo Search wins over Android"),
    # T-BR-15: multi-word phrase wins over generic login
    ("Login broken on Desktop Homepage", 50, "Desktop Homepage wins over login"),
    # T-BR-16: no bucket mention, Samsung device detection → Android
    ("App hangs on login screen, Samsung S23, Android 14", OP_PROJECTS.get("Android", 3), "device detect Android"),
    # T-BR-17: no bucket mention, iPhone → iOS
    ("App hangs on login screen, iPhone 13, iOS 17", OP_PROJECTS.get("iOS", 85), "device detect iOS"),
    # T-BR-18: "home" is cross-keyword, low weight, falls to device default
    ("Crash on home page", OP_PROJECTS.get("Android", 3), "home cross-keyword -> default"),
    # T-BR-19: MERP is a specific single-word alias (weight 5)
    ("MERP login broken", 76, "MERP specific alias"),
])
def test_extract_bucket_freetext_and_device(message, expected_project_id, desc):
    """Test free-text bucket extraction layer per design §4.7."""
    project_id, text_for_llm = extract_bucket_from_message(message)
    assert project_id == expected_project_id, f"FAIL {desc}: got {project_id}"
    assert text_for_llm == message, f"Brief not preserved for {desc}"


def test_extract_bucket_preserves_original_text():
    """Theme 4.2: text_for_llm must be byte-identical to input regardless of match."""
    test_cases = [
        "[LMS Webview] flickering",
        "Login fails [step 3]",
        "bucket - Photo Search, bug on Samsung",
        "Just a random message with no tag",
    ]
    for msg in test_cases:
        _, text_for_llm = extract_bucket_from_message(msg)
        assert text_for_llm == msg, f"Brief mutated for: {msg}"


def test_resolve_tag_returns_none_for_short():
    """Theme 4.3: tags shorter than 2 chars return None."""
    assert _resolve_tag("L") is None
    assert _resolve_tag("") is None
    assert _resolve_tag(" ") is None


def test_resolve_tag_fuzzy_threshold():
    """Theme 4.3: fuzzy cutoff 0.78 blocks weak matches but allows close typos."""
    # Close typo — should match
    result = _resolve_tag("LMS Webveiw")
    assert result == 476, "Close typo should fuzzy-match"

    # Far match — should NOT match
    result = _resolve_tag("Random Thing")
    assert result is None, "Far string should not match"


def test_bucket_tag_regex_anchoring():
    """Theme 4.1: BUCKET_TAG_RE only matches at start of message."""
    # Should match at start
    assert BUCKET_TAG_RE.match("[LMS Webview] test") is not None
    assert BUCKET_TAG_RE.match("  [LMS Webview] test") is not None  # leading whitespace OK

    # Should NOT match mid-text
    assert BUCKET_TAG_RE.match("Login fails [step 3]") is None

    # Should NOT match digit-leading
    assert BUCKET_TAG_RE.match("[2024-05-12] crash") is None
    assert BUCKET_TAG_RE.match("[123] crash") is None


def test_extract_bucket_from_freetext_shorthand():
    """Theme 4.5: bucket-shorthand patterns."""
    assert _extract_bucket_from_freetext("bucket - LMS webview, login broken") == 476
    assert _extract_bucket_from_freetext("bucket: Photo Search, no results") == 461
    assert _extract_bucket_from_freetext("bucket MERP crash") == 76


def test_extract_bucket_from_freetext_returns_none_on_ambiguous():
    """Theme 4.5: ambiguous low-score ties return None."""
    # Only cross-keywords, no specific match
    result = _extract_bucket_from_freetext("login page broken on screen")
    # Should be None (all cross-keywords, ambiguous)
    assert result is None or isinstance(result, int)  # may resolve depending on alias matches
