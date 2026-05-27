"""
Tests for _clean_json_response, _detect_default_stuffing, and Phase2TruncatedError
in gemini_client.py — Theme 3.
"""
import pytest
from gemini_client import (
    Phase2TruncatedError,
    JsonCleanResult,
    _detect_default_stuffing,
    GeminiClient,
)
from models import ExtractedBugReport


# ─────────────────────────────────────────────
# _clean_json_response
# ─────────────────────────────────────────────

class TestCleanJsonResponse:
    """Test _clean_json_response per Theme 3.3."""

    @pytest.fixture
    def client(self):
        """Create a GeminiClient with dummy credentials."""
        return GeminiClient(api_key="test-key", base_url="http://test", model="test-model")

    def test_clean_input_unchanged(self, client):
        """Valid JSON passes through unchanged."""
        valid_json = '{"title": "Bug report", "priority": "Medium"}'
        result = client._clean_json_response(valid_json)
        assert result == valid_json

    def test_strips_markdown_fences(self, client):
        """Markdown code fences are stripped."""
        fenced = '```json\n{"title": "Bug"}\n```'
        result = client._clean_json_response(fenced)
        assert '"title"' in result
        assert "```" not in result

    def test_raises_on_open_brace(self, client):
        """Truncated JSON with unclosed brace raises Phase2TruncatedError."""
        truncated = '{"title": "Bug", "steps": ['
        with pytest.raises(Phase2TruncatedError) as exc_info:
            client._clean_json_response(truncated)
        assert "open" in str(exc_info.value).lower() or len(exc_info.value.repair_log) > 0

    def test_raises_on_unterminated_string(self, client):
        """Truncated JSON with unterminated string raises Phase2TruncatedError."""
        truncated = '{"title": "Bug report'
        with pytest.raises(Phase2TruncatedError) as exc_info:
            client._clean_json_response(truncated)
        assert any("unterminated" in d for d in exc_info.value.repair_log)

    def test_raises_on_open_array(self, client):
        """Truncated JSON with unclosed array raises Phase2TruncatedError."""
        truncated = '{"steps": ["step 1", "step 2"'
        with pytest.raises(Phase2TruncatedError) as exc_info:
            client._clean_json_response(truncated)
        assert len(exc_info.value.repair_log) > 0

    def test_raises_on_empty_response(self, client):
        """Empty response raises Phase2TruncatedError."""
        with pytest.raises(Phase2TruncatedError):
            client._clean_json_response("")
        with pytest.raises(Phase2TruncatedError):
            client._clean_json_response("   ")

    def test_valid_complex_json_passes(self, client):
        """Complete complex JSON with arrays and nested objects passes."""
        valid = '{"title": "Bug", "steps": ["a", "b"], "nested": {"key": "val"}}'
        result = client._clean_json_response(valid)
        assert result == valid


# ─────────────────────────────────────────────
# _detect_default_stuffing
# ─────────────────────────────────────────────

class TestDetectDefaultStuffing:
    """Test _detect_default_stuffing per Theme 3.4 / Requirement 3.10."""

    def test_fully_stuffed_report(self):
        """All 4 indicators fire → is_stuffed=True."""
        report = ExtractedBugReport(
            title="Bug report",
            actual_behavior="See attached media for details.",
            expected_behavior="Expected normal behavior.",
            steps_to_reproduce=["See attached media for reproduction steps"],
            device="Not specified",
            operating_system="Not specified",
            app_version="Not specified",
        )
        is_stuffed, reasons = _detect_default_stuffing(report)
        assert is_stuffed is True
        assert len(reasons) >= 2

    def test_single_trigger_not_stuffed(self):
        """Only 1 of 4 indicators fires → is_stuffed=False."""
        report = ExtractedBugReport(
            title="Login button broken",
            actual_behavior="Login CTA does not respond to tap",
            expected_behavior="Expected normal behavior.",  # 1 trigger
            steps_to_reproduce=["Open app", "Tap login", "Nothing happens"],
            device="Samsung S23",
            operating_system="Android 14",
            app_version="12.3.4",
        )
        is_stuffed, reasons = _detect_default_stuffing(report)
        assert is_stuffed is False

    def test_two_triggers_is_stuffed(self):
        """2 of 4 indicators → is_stuffed=True (≥2 threshold)."""
        report = ExtractedBugReport(
            title="Bug report",
            actual_behavior="See attached media for details.",  # trigger b
            expected_behavior="The button should work.",
            steps_to_reproduce=["Review attached media"],  # trigger a
            device="Samsung S23",
            operating_system="Android 14",
            app_version="12.3.4",
        )
        is_stuffed, reasons = _detect_default_stuffing(report)
        assert is_stuffed is True
        assert len(reasons) == 2

    def test_real_report_not_stuffed(self):
        """A genuine bug report should NOT be detected as stuffed."""
        report = ExtractedBugReport(
            title="Login button not responding on home screen",
            actual_behavior="Tapping the login button does nothing",
            expected_behavior="Login form should open",
            steps_to_reproduce=["Open app", "Tap Login button", "Nothing happens"],
            device="iPhone 13",
            operating_system="iOS 17",
            app_version="12.0.1",
        )
        is_stuffed, reasons = _detect_default_stuffing(report)
        assert is_stuffed is False
        assert len(reasons) == 0

    def test_all_device_fields_blank_trigger(self):
        """Rule (d): device+os+app_version all 'Not specified' is a trigger."""
        report = ExtractedBugReport(
            title="Bug found",
            actual_behavior="Something broken",
            expected_behavior="Expected normal behavior.",  # trigger c
            steps_to_reproduce=["Open app", "See bug"],
            device="Not specified",
            operating_system="Not specified",
            app_version="Not specified",  # trigger d
        )
        is_stuffed, reasons = _detect_default_stuffing(report)
        assert is_stuffed is True  # c + d = 2 triggers
