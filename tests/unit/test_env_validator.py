"""
Tests for env_validator.py — Theme 1.2.
Covers: validate_env_vars 5-check suite, RC2 corruption detection,
BUILD_MARKER resolution.
"""
import logging
import os
import pytest
from unittest.mock import patch, MagicMock
from env_validator import validate_env_vars, read_build_marker


class MockSettings:
    """Mock settings object for testing validate_env_vars."""
    def __init__(self, **kwargs):
        self.llm_api_key = kwargs.get("llm_api_key", "sk-test-key-1234567890")
        self.openproject_base_url = kwargs.get("openproject_base_url", "https://project.intermesh.net")
        self.default_openproject_api_key = kwargs.get("default_openproject_api_key", "normal-key")
        self.demo_space_id = kwargs.get("demo_space_id", "AAQAhf6qdAw")


class TestValidateEnvVars:
    """Test validate_env_vars per Theme 1.2."""

    def test_clean_settings_pass(self, caplog):
        """All checks pass for clean settings."""
        settings = MockSettings()
        with caplog.at_level(logging.INFO, logger="qa_bugbot.env_validator"):
            warnings = validate_env_vars(settings)
        assert len(warnings) == 0
        assert any("all checks passed" in rec.message for rec in caplog.records)

    def test_missing_required_keys(self, caplog):
        """Check 1: empty required keys emit warnings."""
        settings = MockSettings(llm_api_key="", openproject_base_url="")
        with caplog.at_level(logging.WARNING, logger="qa_bugbot.env_validator"):
            warnings = validate_env_vars(settings)
        assert any("LLM_API_KEY is empty" in w for w in warnings)
        assert any("OPENPROJECT_BASE_URL is empty" in w for w in warnings)

    def test_rc2_corruption_detection(self, caplog):
        """Check 3: RC2 corruption signature (=UPPER_SNAKE inside a value) is detected."""
        settings = MockSettings(
            default_openproject_api_key="8cf6e08ea593 DEMO_SPACE_ID=AAQAhf6qdAw"
        )
        with caplog.at_level(logging.WARNING, logger="qa_bugbot.env_validator"):
            warnings = validate_env_vars(settings)
        assert any("appears corrupted" in w for w in warnings)
        assert any("ENV_VALIDATION" in rec.message for rec in caplog.records)

    def test_llm_key_prefix_check(self, caplog):
        """Check 4: LLM_API_KEY not starting with sk- triggers warning."""
        settings = MockSettings(llm_api_key="not-a-sk-key")
        with caplog.at_level(logging.WARNING, logger="qa_bugbot.env_validator"):
            warnings = validate_env_vars(settings)
        assert any("does not start with expected 'sk-'" in w for w in warnings)

    def test_empty_demo_space_id(self, caplog):
        """Check 5: empty DEMO_SPACE_ID triggers warning."""
        settings = MockSettings(demo_space_id="")
        with caplog.at_level(logging.WARNING, logger="qa_bugbot.env_validator"):
            warnings = validate_env_vars(settings)
        assert any("DEMO_SPACE_ID is empty" in w for w in warnings)

    def test_demo_space_bad_shape(self, caplog):
        """Check 5: DEMO_SPACE_ID with special chars triggers warning."""
        settings = MockSettings(demo_space_id="space with spaces!!")
        with caplog.at_level(logging.WARNING, logger="qa_bugbot.env_validator"):
            warnings = validate_env_vars(settings)
        assert any("does not match expected shape" in w for w in warnings)

    def test_whitespace_in_value(self, caplog):
        """Check 2: values with trailing newlines emit warnings."""
        settings = MockSettings(llm_api_key="sk-test-key\n")
        with caplog.at_level(logging.WARNING, logger="qa_bugbot.env_validator"):
            warnings = validate_env_vars(settings)
        assert any("whitespace/newline" in w for w in warnings)


class TestReadBuildMarker:
    """Test read_build_marker per Theme 1.4."""

    def test_env_var_fallback(self):
        """BUILD_MARKER env var is used when /app/BUILD_MARKER doesn't exist."""
        with patch.dict(os.environ, {"BUILD_MARKER": "test-abc123"}):
            marker = read_build_marker()
        assert marker == "test-abc123"

    def test_dev_fallback(self):
        """dev-<timestamp> fallback when both file and env var are missing."""
        with patch.dict(os.environ, {"BUILD_MARKER": ""}):
            marker = read_build_marker()
        assert marker.startswith("dev-")

    def test_file_takes_precedence(self, tmp_path):
        """/app/BUILD_MARKER file takes precedence over env var."""
        marker_file = tmp_path / "BUILD_MARKER"
        marker_file.write_text("file-marker-sha")

        with patch("env_validator.os.path.exists", return_value=True):
            with patch("builtins.open", create=True) as mock_open:
                mock_open.return_value.__enter__ = lambda s: s
                mock_open.return_value.__exit__ = MagicMock(return_value=False)
                mock_open.return_value.read = lambda: "file-marker-sha"
                marker = read_build_marker()
        assert marker == "file-marker-sha"
