import pytest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock
from gemini_client import GeminiClient, Phase2TruncatedError
from models import ExtractedBugReport, PriorityLevel

@pytest.fixture
def gemini_client():
    return GeminiClient(api_key="fake-key", base_url="http://fake", model="fake-model")

@pytest.fixture
def initial_report():
    return ExtractedBugReport(
        title="Phase 1 title",
        actual_behavior="Phase 1 behavior",
        expected_behavior="Phase 1 expected",
        steps_to_reproduce=["Phase 1 step 1"],
        device="Not specified",
        operating_system="Not specified",
        environment="STAGE",
        app_version="Not specified",
        bug_type="Functional/Logical",
        priority=PriorityLevel.MEDIUM,
        platform="Android",
    )

@pytest.mark.asyncio
async def test_enrich_with_media_truncation_fallback(gemini_client, initial_report, caplog):
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content='{"title": "incomplete"'))]
    
    gemini_client.client = MagicMock()
    gemini_client.client.chat.completions.create.return_value = mock_response
    
    result = await gemini_client.enrich_with_media("text", initial_report, [{"mime_type": "image/jpeg", "data": b"abc"}])
    
    # Should fallback to Phase 1 report
    assert result == initial_report
    
    # Verify log
    assert any("PHASE2_TRUNCATED" in record.message for record in caplog.records)

@pytest.mark.asyncio
async def test_enrich_with_media_timeout_fallback(gemini_client, initial_report, caplog):
    gemini_client.client = MagicMock()
    # To trigger asyncio.TimeoutError from run_in_executor, we can mock the inner create to sleep longer than the timeout,
    # OR we can mock asyncio.wait_for directly. Mocking wait_for is easier to trigger TimeoutError reliably without real sleep.
    with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError("timeout")):
        result = await gemini_client.enrich_with_media("text", initial_report, [{"mime_type": "image/jpeg", "data": b"abc"}])
        
    assert result == initial_report
    assert any("PHASE2_SLOW" in record.message for record in caplog.records)

@pytest.mark.asyncio
async def test_enrich_with_media_default_stuffing_fallback(gemini_client, initial_report, caplog):
    # Mock create to return a fully stuffed response (all fields are "Not specified")
    stuffed_json = '''{
        "title": "Not specified",
        "actual_behavior": "Not specified",
        "expected_behavior": "Not specified",
        "steps_to_reproduce": ["See attached media for reproduction steps"],
        "device": "Not specified",
        "operating_system": "Not specified",
        "environment": "STAGE",
        "app_version": "Not specified",
        "bug_type": "Functional/Logical",
        "priority": "Medium",
        "platform": "Android"
    }'''
    
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content=stuffed_json))]
    
    gemini_client.client = MagicMock()
    gemini_client.client.chat.completions.create.return_value = mock_response
    
    result = await gemini_client.enrich_with_media("text", initial_report, [{"mime_type": "image/jpeg", "data": b"abc"}])
    
    assert result == initial_report
    assert any("PHASE2_DEFAULT_STUFFED" in record.message for record in caplog.records)
