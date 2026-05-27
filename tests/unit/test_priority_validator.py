"""
Tests for priority validator in models.py — Theme 5.1 behaviour table.
Covers: word-boundary matching, HIGH/LOW keyword whitelists, tie-breaker,
PRIORITY_AMBIGUOUS audit log.
"""
import logging
import pytest
from models import ExtractedBugReport, PriorityLevel


# ─────────────────────────────────────────────
# Parametrized behaviour table from design §5.1
# ─────────────────────────────────────────────

@pytest.mark.parametrize("input_str, expected_priority, desc", [
    # Clean enum values (fast path)
    ("High", PriorityLevel.HIGH, "exact High"),
    ("Medium", PriorityLevel.MEDIUM, "exact Medium"),
    ("Low", PriorityLevel.LOW, "exact Low"),
    # RC6 regression cases — substring no longer matches
    ("Medium-High", PriorityLevel.MEDIUM, "Medium-High → MEDIUM (no word boundary)"),
    ("highlighted bug", PriorityLevel.MEDIUM, "highlighted → MEDIUM (no boundary)"),
    # HIGH keyword matches
    ("app crashes constantly", PriorityLevel.HIGH, "crashes keyword"),
    ("data loss observed", PriorityLevel.HIGH, "data loss phrase"),
    ("app hangs on login screen", PriorityLevel.HIGH, "hangs keyword"),
    ("stuck on OTP screen", PriorityLevel.HIGH, "stuck on phrase"),
    ("blank screen after tap", PriorityLevel.HIGH, "blank screen phrase"),
    ("app is not responding", PriorityLevel.HIGH, "not responding phrase"),
    ("screen is frozen", PriorityLevel.HIGH, "frozen keyword"),
    ("app is unresponsive", PriorityLevel.HIGH, "unresponsive keyword"),
    ("white screen on load", PriorityLevel.HIGH, "white screen phrase"),
    ("black screen after update", PriorityLevel.HIGH, "black screen phrase"),
    ("completely failing to load", PriorityLevel.HIGH, "completely failing"),
    ("fatal error on startup", PriorityLevel.HIGH, "fatal keyword"),
    ("severe performance issue", PriorityLevel.HIGH, "severe keyword"),
    ("broken CTA", PriorityLevel.HIGH, "broken keyword"),
    # LOW keyword matches
    ("slight misalignment", PriorityLevel.LOW, "slight misalignment phrase"),
    ("minor cosmetic issue", PriorityLevel.LOW, "minor keyword"),
    ("trivial font size", PriorityLevel.LOW, "trivial keyword"),
    ("rarely happens", PriorityLevel.LOW, "rarely keyword"),
    ("sometimes fails", PriorityLevel.LOW, "sometimes keyword"),
    ("occasionally visible", PriorityLevel.LOW, "occasionally keyword"),
    ("slightly off center", PriorityLevel.LOW, "slightly keyword"),
    # Tie-breaker cases (HIGH + LOW → MEDIUM)
    ("intermittent crash", PriorityLevel.MEDIUM, "HIGH+LOW tie → MEDIUM"),
    ("screen freezes intermittently", PriorityLevel.MEDIUM, "HIGH+LOW tie → MEDIUM"),
    ("sometimes crashes on payment", PriorityLevel.MEDIUM, "HIGH+LOW tie → MEDIUM"),
    # Neither HIGH nor LOW
    ("button not clickable", PriorityLevel.MEDIUM, "no keywords → MEDIUM"),
    ("page not loading properly", PriorityLevel.MEDIUM, "no keywords → MEDIUM"),
    # Edge: empty / None
    ("", PriorityLevel.MEDIUM, "empty → MEDIUM"),
    ("  ", PriorityLevel.MEDIUM, "whitespace → MEDIUM"),
])
def test_priority_validator_word_boundary(input_str, expected_priority, desc):
    """Test priority validator per design §5.1 behaviour table."""
    report = ExtractedBugReport(priority=input_str)
    assert report.priority == expected_priority, f"FAIL {desc}: got {report.priority}"


def test_priority_validator_none_returns_medium():
    """Non-string/None priority defaults to MEDIUM."""
    report = ExtractedBugReport(priority=None)
    assert report.priority == PriorityLevel.MEDIUM


# ─────────────────────────────────────────────
# PRIORITY_AMBIGUOUS log assertion
# ─────────────────────────────────────────────

@pytest.mark.parametrize("input_str", [
    "intermittent crash",
    "screen freezes intermittently",
    "sometimes crashes on payment",
])
def test_priority_validator_ambiguous_logs_warning(input_str, caplog):
    """When both HIGH and LOW keywords match, PRIORITY_AMBIGUOUS warning is emitted."""
    with caplog.at_level(logging.WARNING, logger="models"):
        report = ExtractedBugReport(priority=input_str)
    assert report.priority == PriorityLevel.MEDIUM
    assert any("PRIORITY_AMBIGUOUS" in rec.message for rec in caplog.records), \
        f"Expected PRIORITY_AMBIGUOUS log for '{input_str}'"
