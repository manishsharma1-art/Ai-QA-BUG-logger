"""
Gateway error classification + smoke test + LLM_CALL log line tests.

Pins the contract:
- Every gateway exception is mapped to one of 5 outcomes.
- Phase 1 raises LLMGatewayError with the categorised outcome (no leaking
  raw SDK text to the user-facing reply).
- smoke_test never raises and returns the same outcome vocabulary.
"""
from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gemini_client import (
    GeminiClient,
    LLMGatewayError,
    _classify_gateway_exception,
    _log_llm_call,
)


# ─────────────────────────────────────────────
# Classifier — pure-function tests
# ─────────────────────────────────────────────

class _FakeAuthError(Exception):
    pass
class _FakeRateLimitError(Exception):
    pass
class _FakeAPIConnectionError(Exception):
    pass
class _FakeInternalServerError(Exception):
    pass


@pytest.mark.parametrize("exc, expected", [
    (_FakeAuthError("AuthenticationError: 401"), "auth_error"),
    (Exception("HTTP 401 Unauthorized"), "auth_error"),
    (Exception("HTTP 403 Forbidden"), "auth_error"),
    (_FakeRateLimitError("RateLimitError: 429"), "rate_limit"),
    (Exception("HTTP 429 Too Many"), "rate_limit"),
    (_FakeInternalServerError("InternalServerError"), "server_error"),
    (Exception("HTTP 502 Bad Gateway"), "server_error"),
    (Exception("HTTP 503 Service Unavailable"), "server_error"),
    (_FakeAPIConnectionError("APIConnectionError"), "network_error"),
    (TimeoutError("connect timeout"), "network_error"),
    (ValueError("something else entirely"), "unknown_error"),
])
def test_classify_gateway_exception(exc, expected):
    assert _classify_gateway_exception(exc) == expected


# ─────────────────────────────────────────────
# _log_llm_call — emits one structured line, returns outcome string
# ─────────────────────────────────────────────

def test_log_llm_call_ok(caplog):
    import time
    start = time.time() - 0.1
    with caplog.at_level(logging.INFO, logger="gemini_client"):
        outcome = _log_llm_call("phase1", start, response_chars=312)
    assert outcome == "ok"
    line = next(r.message for r in caplog.records if "LLM_CALL" in r.message)
    assert "phase=phase1" in line
    assert "outcome=ok" in line
    assert "duration_ms=" in line
    assert "chars=312" in line


def test_log_llm_call_failure(caplog):
    import time
    start = time.time() - 0.05
    with caplog.at_level(logging.WARNING, logger="gemini_client"):
        outcome = _log_llm_call("phase1", start, exc=Exception("HTTP 401 Unauthorized"))
    assert outcome == "auth_error"
    line = next(r.message for r in caplog.records if "LLM_CALL" in r.message)
    assert "outcome=auth_error" in line
    # Must include detail but NOT the full raw exception trace
    assert "Exception=" in line or "phase=phase1" in line


def test_log_llm_call_unknown_logged_at_error_level(caplog):
    import time
    with caplog.at_level(logging.ERROR, logger="gemini_client"):
        _log_llm_call("phase1", time.time(), exc=ValueError("weird"))
    err_records = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert any("outcome=unknown_error" in r.message for r in err_records)


# ─────────────────────────────────────────────
# smoke_test — never raises, returns dict
# ─────────────────────────────────────────────

def _make_client_with_response(response_text: str) -> GeminiClient:
    client = GeminiClient.__new__(GeminiClient)
    client.client = MagicMock()
    client.model = "test-model"
    fake_resp = MagicMock()
    fake_resp.choices = [MagicMock()]
    fake_resp.choices[0].message.content = response_text
    client.client.chat.completions.create = MagicMock(return_value=fake_resp)
    return client


def _make_client_that_raises(exc: Exception) -> GeminiClient:
    client = GeminiClient.__new__(GeminiClient)
    client.client = MagicMock()
    client.model = "test-model"
    client.client.chat.completions.create = MagicMock(side_effect=exc)
    return client


@pytest.mark.asyncio
async def test_smoke_test_ok():
    client = _make_client_with_response("pong")
    result = await client.smoke_test(timeout_s=2.0)
    assert result["outcome"] == "ok"
    assert result["duration_ms"] >= 0
    assert "chars=" in result["detail"]


@pytest.mark.asyncio
async def test_smoke_test_auth_error():
    client = _make_client_that_raises(Exception("AuthenticationError: invalid api key"))
    result = await client.smoke_test(timeout_s=2.0)
    assert result["outcome"] == "auth_error"
    assert result["duration_ms"] >= 0


@pytest.mark.asyncio
async def test_smoke_test_rate_limit():
    client = _make_client_that_raises(Exception("RateLimitError: 429"))
    result = await client.smoke_test(timeout_s=2.0)
    assert result["outcome"] == "rate_limit"


@pytest.mark.asyncio
async def test_smoke_test_server_error():
    client = _make_client_that_raises(Exception("HTTP 503 Service Unavailable"))
    result = await client.smoke_test(timeout_s=2.0)
    assert result["outcome"] == "server_error"


@pytest.mark.asyncio
async def test_smoke_test_network_error():
    client = _make_client_that_raises(ConnectionError("connection refused"))
    result = await client.smoke_test(timeout_s=2.0)
    assert result["outcome"] == "network_error"


# ─────────────────────────────────────────────
# Phase 1 — raises LLMGatewayError, no raw SDK text leaks
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_phase1_raises_categorized_llm_gateway_error_on_auth_failure():
    client = _make_client_that_raises(Exception("AuthenticationError: 401"))
    with pytest.raises(LLMGatewayError) as exc_info:
        await client.analyze_text_brief("Some bug brief that is long enough")
    assert exc_info.value.outcome == "auth_error"


@pytest.mark.asyncio
async def test_phase1_raises_categorized_llm_gateway_error_on_rate_limit():
    client = _make_client_that_raises(Exception("RateLimitError: 429 Too Many Requests"))
    with pytest.raises(LLMGatewayError) as exc_info:
        await client.analyze_text_brief("Some bug brief that is long enough")
    assert exc_info.value.outcome == "rate_limit"


@pytest.mark.asyncio
async def test_phase1_raises_categorized_llm_gateway_error_on_server_error():
    client = _make_client_that_raises(Exception("HTTP 502 Bad Gateway"))
    with pytest.raises(LLMGatewayError) as exc_info:
        await client.analyze_text_brief("Some bug brief that is long enough")
    assert exc_info.value.outcome == "server_error"
