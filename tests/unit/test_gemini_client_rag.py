"""
Unit tests for gemini_client RAG integration.
Tests the three-stage fallback in _build_fewshot_block and
the _render_examples_block helper.
"""
import pytest
from unittest.mock import patch, MagicMock, PropertyMock


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _make_gemini_client():
    """Build a minimal GeminiClient with a mocked OpenAI backend."""
    from gemini_client import GeminiClient
    with patch("gemini_client.OpenAI"):
        client = GeminiClient(api_key="fake-key", base_url="http://fake", model="test-model")
    return client


def _make_sample_examples(n=3):
    """Build example dicts mimicking RetrievedExample shape."""
    return [
        {
            "id": str(i),
            "subject": f"Bug #{i}: login button not working",
            "description_raw": f"### **Actual Behavior**\nButton does not respond\n### **Expected Behavior**\nButton should work\n### **Steps to reproduce**\n1. Open app\n2. Tap login",
            "project": "Android",
            "project_id": 3,
            "priority": "Medium",
            "bug_type": "Functional/Logical",
            "environment": "STAGE",
            "category": None,
            "score": 0.85 - i * 0.05,
            "matched_project": i == 0,
        }
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# U27 — _render_examples_block produces block with REFERENCE EXAMPLES header
# ---------------------------------------------------------------------------
def test_render_examples_block_format():
    from gemini_client import _render_examples_block
    examples = _make_sample_examples(2)
    block = _render_examples_block(examples)
    assert "REFERENCE EXAMPLES" in block
    assert "INPUT (QA brief):" in block
    assert "OUTPUT (JSON):" in block
    assert "---" in block  # separator between examples


def test_render_examples_block_empty():
    from gemini_client import _render_examples_block
    block = _render_examples_block([])
    assert "REFERENCE EXAMPLES" in block


# ---------------------------------------------------------------------------
# U28 — _build_fewshot_block returns static fallback when retriever returns empty
# ---------------------------------------------------------------------------
def test_build_fewshot_block_static_fallback():
    client = _make_gemini_client()

    mock_retriever = MagicMock()
    mock_retriever.retrieve.return_value = []
    mock_retriever._last_retrieve_outcome = "empty_corpus"

    with patch("bug_retriever.get_retriever", return_value=mock_retriever):
        block, meta = client._build_fewshot_block(query="some long enough query for testing", project_id=3, phase="phase1")

    # Should fall back to static block (or empty if _FEW_SHOT_BLOCK is empty)
    assert meta["source"] in ("static", "empty")


# ---------------------------------------------------------------------------
# U29 — _build_fewshot_block returns retrieved block when retriever returns examples
# ---------------------------------------------------------------------------
def test_build_fewshot_block_retrieval_path():
    client = _make_gemini_client()

    examples = _make_sample_examples(3)
    mock_retriever = MagicMock()
    mock_retriever.retrieve.return_value = examples
    mock_retriever._last_retrieve_outcome = "ok"

    with patch("bug_retriever.get_retriever", return_value=mock_retriever):
        block, meta = client._build_fewshot_block(query="login button crash on Android device", project_id=3, phase="phase1")

    assert meta["source"] == "retrieved"
    assert meta["count"] == 3
    assert "REFERENCE EXAMPLES" in block


# ---------------------------------------------------------------------------
# U30 — _build_fewshot_block handles no retriever (returns static or empty)
# ---------------------------------------------------------------------------
def test_build_fewshot_block_no_retriever():
    client = _make_gemini_client()

    with patch("bug_retriever.get_retriever", return_value=None):
        block, meta = client._build_fewshot_block(query="test query that is long enough", project_id=None, phase="phase1")

    assert meta["source"] in ("static", "empty")
    assert meta["outcome"] == "index_unavailable"


# ---------------------------------------------------------------------------
# U31 — _build_fewshot_block catches unexpected exceptions from retriever
# ---------------------------------------------------------------------------
def test_build_fewshot_block_exception_handling():
    client = _make_gemini_client()

    mock_retriever = MagicMock()
    mock_retriever.retrieve.side_effect = RuntimeError("unexpected crash")

    with patch("bug_retriever.get_retriever", return_value=mock_retriever):
        block, meta = client._build_fewshot_block(query="login crash query text here", project_id=3, phase="phase1")

    # Should not raise, should fallback
    assert meta["source"] in ("static", "empty")
    assert meta["outcome"] == "embed_error"
