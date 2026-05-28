"""
Tests for the few-shot example loader (audit-driven prompt-engineering lift).

Pins the contract:
- _FEW_SHOT_BLOCK is non-empty when the curated file is present.
- Each rendered example follows the INPUT→OUTPUT pattern.
- Each example's JSON is valid and contains all 11 mandatory fields.
- Loader silently falls back to "" on missing/corrupt input — never raises.
- HTML entities and non-breaking-space artifacts are stripped from prompt text.
- Block size stays under a sane budget so Phase 1 latency is predictable.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from gemini_client import (
    _FEW_SHOT_BLOCK,
    _format_example,
    _load_few_shot_block,
    _synthesize_qa_brief,
    SYSTEM_PROMPT,
)


REQUIRED_OUTPUT_FIELDS = {
    "title", "actual_behavior", "expected_behavior", "steps_to_reproduce",
    "device", "operating_system", "environment", "app_version",
    "bug_type", "priority", "logs_or_links",
}


# ─── Block presence + structure ─────────────────────────────────────────

def test_few_shot_block_loaded_at_import():
    """The curated file ships with the repo; block must be non-empty."""
    assert _FEW_SHOT_BLOCK, "expected non-empty few-shot block at import time"


def test_few_shot_block_appended_to_system_prompt():
    """SYSTEM_PROMPT must include the few-shot block so the LLM sees it."""
    assert "REFERENCE EXAMPLES" in SYSTEM_PROMPT
    assert _FEW_SHOT_BLOCK in SYSTEM_PROMPT


def test_few_shot_block_has_input_output_pairs():
    """Each example must follow the INPUT/OUTPUT teaching pattern."""
    assert "INPUT (QA brief):" in _FEW_SHOT_BLOCK
    assert "OUTPUT (JSON):" in _FEW_SHOT_BLOCK
    # 5 examples = 5 pairs of each marker
    assert _FEW_SHOT_BLOCK.count("INPUT (QA brief):") == 5
    assert _FEW_SHOT_BLOCK.count("OUTPUT (JSON):") == 5


def test_few_shot_block_size_bounded():
    """Cap prompt size to keep Phase 1 latency predictable.
    5 examples should stay under 8 KB; alarm if a single example regresses."""
    assert len(_FEW_SHOT_BLOCK) < 8_000, (
        f"few-shot block ballooned to {len(_FEW_SHOT_BLOCK)} chars — "
        "reduce max_examples or trim per-example caps"
    )


# ─── Per-example correctness ────────────────────────────────────────────

def test_each_example_json_is_valid_and_complete():
    """Every OUTPUT block must parse as JSON and contain all 11 fields."""
    # Split block into sections delimited by the example separator
    sections = [s for s in _FEW_SHOT_BLOCK.split("\n\n---\n\n") if "OUTPUT (JSON):" in s]
    assert len(sections) == 5, f"expected 5 sections, got {len(sections)}"

    for i, section in enumerate(sections):
        # Pull the JSON portion after "OUTPUT (JSON):\n"
        _, json_text = section.split("OUTPUT (JSON):\n", 1)
        json_text = json_text.strip()
        try:
            parsed = json.loads(json_text)
        except json.JSONDecodeError as e:
            pytest.fail(f"example {i} OUTPUT is not valid JSON: {e}\n--- json was ---\n{json_text[:400]}")
        missing = REQUIRED_OUTPUT_FIELDS - set(parsed.keys())
        assert not missing, f"example {i} missing required fields: {missing}"


def test_no_html_entities_or_nbsp_artifacts_leak_into_prompt():
    """Source data has '&#39;', '&amp;', '\\u00a0', '┬á' — they must be
    cleaned before the LLM ever sees them."""
    artifacts = ["&#39;", "&amp;", "&quot;", "\u00a0", "┬á"]
    for artifact in artifacts:
        assert artifact not in _FEW_SHOT_BLOCK, (
            f"raw artifact {artifact!r} leaked into the few-shot prompt — "
            "_normalise() needs to handle it"
        )


# ─── Loader robustness ──────────────────────────────────────────────────

def test_loader_returns_empty_when_file_missing(tmp_path, monkeypatch):
    """If assets/training_examples_fewshot.json is missing, return '' silently."""
    fake_module_dir = tmp_path / "fake_module"
    fake_module_dir.mkdir()
    # Simulate __file__ pointing into a dir with no assets/
    with patch("gemini_client._Path") as mock_path:
        # Make _Path(__file__).parent / "assets" / ... not exist
        mock_path.return_value.parent.__truediv__.return_value.__truediv__.return_value.exists.return_value = False
        block = _load_few_shot_block()
    assert block == ""


def test_loader_returns_empty_on_corrupt_json(tmp_path, monkeypatch):
    """Corrupt JSON file must NOT raise — return '' so startup proceeds."""
    bad = tmp_path / "training_examples_fewshot.json"
    bad.write_text("{ this is not json", encoding="utf-8")

    # Point the loader at our bad file
    real_path_class = Path

    class _FakePath:
        def __init__(self, *args):
            self._inner = real_path_class(*args) if args else real_path_class("/fake")
        @property
        def parent(self):
            return self
        def __truediv__(self, other):
            if other == "assets":
                return self
            if other.endswith(".json"):
                return real_path_class(str(bad))
            return self
        def exists(self):
            return True
        def read_text(self, encoding="utf-8-sig"):
            return bad.read_text(encoding="utf-8")

    with patch("gemini_client._Path", _FakePath):
        block = _load_few_shot_block()
    assert block == "", "corrupt JSON must produce empty block, not raise"


def test_loader_filters_examples_with_missing_fields():
    """Entries with bug_type=None must be skipped."""
    # The real curated file has 13 entries, 2 of which lack bug_type.
    # We use 5 of the 11 valid entries by default (max_examples=5).
    block = _load_few_shot_block(max_examples=5)
    assert block.count("INPUT (QA brief):") == 5


def test_loader_caps_examples_count():
    """max_examples is honored as upper bound."""
    assert _load_few_shot_block(max_examples=3).count("INPUT (QA brief):") == 3
    assert _load_few_shot_block(max_examples=2).count("INPUT (QA brief):") == 2


# ─── Synthesizer correctness ────────────────────────────────────────────

def test_synthesize_qa_brief_extracts_device_and_os():
    """The synthesized brief should look like a real QA tester message,
    pulling device/OS from the test environment block."""
    example = {
        "subject": "Login button not clickable",
        "description_raw": (
            "### **Actual Behavior**\nLogin fails.\n\n"
            "### **Test Environment**:\n"
            "1.  **Device:** Samsung S23\n"
            "2.  **Environment**: Stage\n"
            "3.  **Operating System:** Android 14"
        ),
    }
    brief = _synthesize_qa_brief(example)
    assert "Login button not clickable" in brief
    assert "Samsung S23" in brief
    assert "Android 14" in brief
