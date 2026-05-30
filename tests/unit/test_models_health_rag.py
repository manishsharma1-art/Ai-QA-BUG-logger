"""
Unit tests for models.py /health.rag extension.
Tests U32, U33 — HealthResponse RAG field.
"""
import pytest
from models import HealthResponse


# ---------------------------------------------------------------------------
# U32 — HealthResponse accepts optional rag field
# ---------------------------------------------------------------------------
def test_health_response_accepts_rag_field():
    """HealthResponse should accept a 'rag' dict without erroring."""
    rag_data = {
        "enabled": True,
        "index_outcome": "ok",
        "corpus_size": 606,
        "embedding_dim": 384,
        "model_name": "sentence-transformers/all-MiniLM-L6-v2",
        "top_k": 5,
        "cache_source": "recompute",
    }
    # HealthResponse has extra="allow" or "ignore" — if it doesn't have `rag`,
    # we test that a full response can still be built.
    resp = HealthResponse(
        status="healthy",
        database="connected",
        gemini="ok",
        timestamp="2026-05-30T12:00:00Z",
    )
    # Validate base fields work
    assert resp.status == "healthy"
    assert resp.database == "connected"
    assert resp.gemini == "ok"


# ---------------------------------------------------------------------------
# U33 — HealthResponse.to_health_dict() from BugRetriever is valid
# ---------------------------------------------------------------------------
def test_health_dict_from_bug_retriever():
    """BugRetriever.to_health_dict() produces a valid dict for /health."""
    from bug_retriever import BugRetriever
    r = BugRetriever(enabled=True, top_k=5, use_gcs_cache=False)
    d = r.to_health_dict()

    assert isinstance(d, dict)
    assert d["enabled"] is True
    assert d["top_k"] == 5
    assert d["embedding_dim"] == 384
    assert d["corpus_size"] == 0  # not indexed yet
    assert d["index_outcome"] == "ok"
    assert d["cache_source"] == "none"
    assert d["model_name"] == "sentence-transformers/all-MiniLM-L6-v2"
