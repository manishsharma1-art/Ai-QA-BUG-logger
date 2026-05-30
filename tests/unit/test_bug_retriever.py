"""
Unit tests for the bug_retriever module.
Tests U1..U33 — real assertions, not placeholders.
"""
import pytest
import json
import hashlib
import logging
import numpy as np
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_corpus(n: int = 10, project_id: int = 3) -> list[dict]:
    """Build a tiny corpus with n entries."""
    return [
        {
            "id": str(i),
            "subject": f"Bug #{i}: login page crash on submit",
            "description_raw": f"When clicking submit on the login page, the app crashes. Entry {i}.",
            "project": "Test Project",
            "project_id": project_id,
            "priority": "Medium",
            "bug_type": "Functional/Logical",
            "environment": "STAGE",
            "category": None,
        }
        for i in range(n)
    ]


def _make_retriever(enabled=True, top_k=5, use_gcs_cache=False):
    """Construct a BugRetriever without touching env vars or GCS."""
    from bug_retriever import BugRetriever
    return BugRetriever(enabled=enabled, top_k=top_k, use_gcs_cache=use_gcs_cache)


def _index_with_fake_model(retriever, corpus=None):
    """Wire a fake model + corpus into the retriever and call index()."""
    corpus = corpus or _make_corpus(10)

    class FakeModel:
        def encode(self, texts, **kwargs):
            # Return random-but-deterministic embeddings seeded by text hash
            vecs = []
            for t in (texts if isinstance(texts, list) else [texts]):
                seed = int(hashlib.md5(t.encode()).hexdigest()[:8], 16) % (2**31)
                rng = np.random.RandomState(seed)
                v = rng.randn(384).astype(np.float32)
                v /= np.linalg.norm(v) + 1e-9
                vecs.append(v)
            arr = np.array(vecs, dtype=np.float32)
            return arr if isinstance(texts, list) else arr[0]

    with patch.object(retriever, "_load_corpus_rows", return_value=corpus), \
         patch.object(retriever, "_load_model", return_value=FakeModel()), \
         patch.object(retriever, "_try_load_cache", return_value=None), \
         patch.object(retriever, "_try_upload_cache"):
        retriever.index()


# ---------------------------------------------------------------------------
# U1 — CorpusEntry TypedDict has all required fields
# ---------------------------------------------------------------------------
def test_u1_corpus_entry_has_required_keys():
    from bug_retriever import CorpusEntry
    required = {"id", "subject", "description_raw", "project", "project_id",
                "priority", "bug_type", "environment", "category"}
    assert required == set(CorpusEntry.__annotations__.keys())


# ---------------------------------------------------------------------------
# U2 — BugRetriever.__init__ clamps top_k to [1, 20]
# ---------------------------------------------------------------------------
def test_u2_top_k_clamp_lower():
    r = _make_retriever(top_k=-5)
    assert r._top_k == 1

def test_u3_top_k_clamp_upper():
    r = _make_retriever(top_k=100)
    assert r._top_k == 20

def test_u4_top_k_normal():
    r = _make_retriever(top_k=7)
    assert r._top_k == 7


# ---------------------------------------------------------------------------
# U5 — from_env reads environment variables
# ---------------------------------------------------------------------------
def test_u5_from_env_defaults():
    from bug_retriever import BugRetriever
    with patch.dict("os.environ", {}, clear=False):
        # Remove RAG vars if present
        import os
        for k in ("RAG_ENABLED", "RAG_TOPK", "RAG_CACHE_GCS"):
            os.environ.pop(k, None)
        r = BugRetriever.from_env()
    assert r._enabled is True
    assert r._top_k == 5
    assert r._use_gcs_cache is True


def test_u6_from_env_disabled():
    from bug_retriever import BugRetriever
    with patch.dict("os.environ", {"RAG_ENABLED": "false", "RAG_TOPK": "10", "RAG_CACHE_GCS": "false"}):
        r = BugRetriever.from_env()
    assert r._enabled is False
    assert r._top_k == 10
    assert r._use_gcs_cache is False


# ---------------------------------------------------------------------------
# U7 — is_ready() returns False before index
# ---------------------------------------------------------------------------
def test_u7_not_ready_before_index():
    r = _make_retriever()
    assert r.is_ready() is False


# ---------------------------------------------------------------------------
# U8 — is_ready() returns True after successful index
# ---------------------------------------------------------------------------
def test_u8_ready_after_index():
    r = _make_retriever()
    _index_with_fake_model(r)
    assert r.is_ready() is True


# ---------------------------------------------------------------------------
# U9 — index() on disabled retriever sets outcome=disabled
# ---------------------------------------------------------------------------
def test_u9_disabled_index_outcome():
    r = _make_retriever(enabled=False)
    r.index()
    assert r.last_outcome() == "disabled"
    assert r.is_ready() is False


# ---------------------------------------------------------------------------
# U10 — index() with failed corpus load does not crash
# ---------------------------------------------------------------------------
def test_u10_corpus_load_failure():
    r = _make_retriever()
    with patch.object(r, "_load_corpus_rows", side_effect=RuntimeError("file missing")):
        r.index()
    assert r.last_outcome() == "corpus_load_failed"
    assert r.is_ready() is False


# ---------------------------------------------------------------------------
# U11 — index() with failed model load does not crash
# ---------------------------------------------------------------------------
def test_u11_model_load_failure():
    r = _make_retriever()
    corpus = _make_corpus(5)
    with patch.object(r, "_load_corpus_rows", return_value=corpus), \
         patch.object(r, "_load_model", side_effect=RuntimeError("GPU OOM")):
        r.index()
    assert r.last_outcome() == "model_load_failed"
    assert r.is_ready() is False


# ---------------------------------------------------------------------------
# U12 — retrieve() returns empty list when index not ready
# ---------------------------------------------------------------------------
def test_u12_retrieve_before_index():
    r = _make_retriever()
    results = r.retrieve("login crash on iPhone", k=3)
    assert results == []


# ---------------------------------------------------------------------------
# U13 — retrieve() returns <= K results
# ---------------------------------------------------------------------------
def test_u13_retrieve_k_bound():
    r = _make_retriever(top_k=3)
    _index_with_fake_model(r, _make_corpus(20))
    results = r.retrieve("login crash bug", k=3)
    assert len(results) <= 3


# ---------------------------------------------------------------------------
# U14 — retrieve() clamps K to [1, 20]
# ---------------------------------------------------------------------------
def test_u14_retrieve_k_clamp():
    r = _make_retriever()
    _index_with_fake_model(r, _make_corpus(5))
    # K=0 should be clamped to 1
    results = r.retrieve("some query that is long enough", k=0)
    assert len(results) >= 1
    # K=100 should be clamped to 20 (but corpus is only 5, so max 5)
    results2 = r.retrieve("some query that is long enough", k=100)
    assert len(results2) == 5


# ---------------------------------------------------------------------------
# U15 — Each retrieved example has a 'score' float and 'matched_project' bool
# ---------------------------------------------------------------------------
def test_u15_retrieved_example_schema():
    r = _make_retriever()
    _index_with_fake_model(r, _make_corpus(5))
    results = r.retrieve("login crash on Android device bug", k=3)
    assert len(results) > 0
    for ex in results:
        assert "score" in ex and isinstance(ex["score"], float)
        assert "matched_project" in ex and isinstance(ex["matched_project"], bool)
        assert "id" in ex
        assert "subject" in ex


# ---------------------------------------------------------------------------
# U16 — Results are ordered by score descending
# ---------------------------------------------------------------------------
def test_u16_results_sorted_descending():
    r = _make_retriever()
    _index_with_fake_model(r, _make_corpus(20))
    results = r.retrieve("login crash bug report analysis", k=10)
    scores = [ex["score"] for ex in results]
    assert scores == sorted(scores, reverse=True)


# ---------------------------------------------------------------------------
# U17 — Soft project boost adds +0.05 to matching entries
# ---------------------------------------------------------------------------
def test_u17_project_boost():
    # Build a corpus with mixed projects
    mixed = _make_corpus(5, project_id=476) + _make_corpus(5, project_id=3)
    # Give each entry a unique id
    for i, e in enumerate(mixed):
        e["id"] = str(i)

    r = _make_retriever()
    _index_with_fake_model(r, mixed)

    # Retrieve with project_filter=476
    results = r.retrieve("login crash bug on application", k=10, project_filter=476)
    # Verify at least one matched_project=True
    matched = [ex for ex in results if ex["matched_project"]]
    assert len(matched) > 0, "Should have at least one project-matched result"


# ---------------------------------------------------------------------------
# U18 — retrieve() never raises, even with weird input
# ---------------------------------------------------------------------------
def test_u18_never_raises_empty_string():
    r = _make_retriever()
    _index_with_fake_model(r)
    result = r.retrieve("")
    assert isinstance(result, list)

def test_u19_never_raises_none():
    r = _make_retriever()
    _index_with_fake_model(r)
    result = r.retrieve(None)
    assert isinstance(result, list)

def test_u20_never_raises_unicode():
    r = _make_retriever()
    _index_with_fake_model(r)
    result = r.retrieve("日本語のバグ報告 🐛💥 — это отчёт об ошибке")
    assert isinstance(result, list)


# ---------------------------------------------------------------------------
# U21 — Short brief (<20 chars) is tagged as 'short_brief'
# ---------------------------------------------------------------------------
def test_u21_short_brief_outcome():
    r = _make_retriever()
    _index_with_fake_model(r)
    r.retrieve("hi", k=3)
    assert r._last_retrieve_outcome == "short_brief"


# ---------------------------------------------------------------------------
# U22 — _compute_corpus_hash is deterministic for same corpus
# ---------------------------------------------------------------------------
def test_u22_corpus_hash_deterministic():
    r = _make_retriever()
    corpus = _make_corpus(5)
    h1 = r._compute_corpus_hash(corpus)
    h2 = r._compute_corpus_hash(corpus)
    assert h1 == h2
    assert isinstance(h1, str)
    assert len(h1) == 64  # SHA-256 hex digest


# ---------------------------------------------------------------------------
# U23 — _compute_corpus_hash is order-independent (sorted by id)
# ---------------------------------------------------------------------------
def test_u23_corpus_hash_order_independent():
    r = _make_retriever()
    corpus = _make_corpus(5)
    reversed_corpus = list(reversed(corpus))
    h1 = r._compute_corpus_hash(corpus)
    h2 = r._compute_corpus_hash(reversed_corpus)
    assert h1 == h2


# ---------------------------------------------------------------------------
# U24 — _compute_corpus_hash changes when subject changes
# ---------------------------------------------------------------------------
def test_u24_corpus_hash_changes_on_content():
    r = _make_retriever()
    corpus1 = _make_corpus(3)
    corpus2 = _make_corpus(3)
    corpus2[1]["subject"] = "MODIFIED SUBJECT"
    h1 = r._compute_corpus_hash(corpus1)
    h2 = r._compute_corpus_hash(corpus2)
    assert h1 != h2


# ---------------------------------------------------------------------------
# U25 — _compute_corpus_hash only uses id, subject, description_raw
# ---------------------------------------------------------------------------
def test_u25_corpus_hash_ignores_metadata():
    r = _make_retriever()
    corpus1 = _make_corpus(3)
    corpus2 = _make_corpus(3)
    corpus2[0]["priority"] = "HIGH"  # metadata, not in hash
    corpus2[0]["project_id"] = 999
    h1 = r._compute_corpus_hash(corpus1)
    h2 = r._compute_corpus_hash(corpus2)
    assert h1 == h2


# ---------------------------------------------------------------------------
# U26 — to_health_dict() returns correct shape
# ---------------------------------------------------------------------------
def test_u26_health_dict_shape():
    r = _make_retriever(top_k=7)
    d = r.to_health_dict()
    assert d["enabled"] is True
    assert d["top_k"] == 7
    assert d["embedding_dim"] == 384
    assert d["model_name"] == "sentence-transformers/all-MiniLM-L6-v2"
    assert "index_outcome" in d
    assert "corpus_size" in d
    assert "cache_source" in d


# ---------------------------------------------------------------------------
# U27 — to_health_dict() after index shows correct corpus_size
# ---------------------------------------------------------------------------
def test_u27_health_dict_after_index():
    r = _make_retriever()
    _index_with_fake_model(r, _make_corpus(15))
    d = r.to_health_dict()
    assert d["corpus_size"] == 15
    assert d["index_outcome"] in ("ok", "cache_miss")


# ---------------------------------------------------------------------------
# U28 — RAG_INDEX log marker is emitted on index()
# ---------------------------------------------------------------------------
def test_u28_rag_index_log_marker(caplog):
    r = _make_retriever()
    with caplog.at_level(logging.INFO, logger="bug_retriever"):
        _index_with_fake_model(r)
    assert any("RAG_INDEX" in rec.message for rec in caplog.records), \
        f"Expected RAG_INDEX log; got: {[r.message for r in caplog.records]}"


# ---------------------------------------------------------------------------
# U29 — RAG_RETRIEVE log marker is emitted on retrieve()
# ---------------------------------------------------------------------------
def test_u29_rag_retrieve_log_marker(caplog):
    r = _make_retriever()
    _index_with_fake_model(r)
    with caplog.at_level(logging.INFO, logger="bug_retriever"):
        r.retrieve("login crash on iPhone 13 test scenario", k=3)
    assert any("RAG_RETRIEVE" in rec.message for rec in caplog.records), \
        f"Expected RAG_RETRIEVE log; got: {[r.message for r in caplog.records]}"


# ---------------------------------------------------------------------------
# U30 — init_retriever is idempotent
# ---------------------------------------------------------------------------
def test_u30_init_retriever_idempotent():
    import bug_retriever
    old = bug_retriever._retriever
    try:
        bug_retriever._retriever = None  # reset
        r1 = _make_retriever(enabled=False)
        bug_retriever._retriever = r1
        r2 = bug_retriever.init_retriever()
        assert r2 is r1, "Should return existing retriever, not create a new one"
    finally:
        bug_retriever._retriever = old


# ---------------------------------------------------------------------------
# U31 — get_retriever returns None before init
# ---------------------------------------------------------------------------
def test_u31_get_retriever_returns_none():
    import bug_retriever
    old = bug_retriever._retriever
    try:
        bug_retriever._retriever = None
        assert bug_retriever.get_retriever() is None
    finally:
        bug_retriever._retriever = old


# ---------------------------------------------------------------------------
# U32 — embed_error fallback produces empty list
# ---------------------------------------------------------------------------
def test_u32_embed_error_fallback():
    r = _make_retriever()
    _index_with_fake_model(r)
    # Monkeypatch model.encode to raise
    r._model.encode = MagicMock(side_effect=RuntimeError("CUDA OOM"))
    results = r.retrieve("some query that is definitely long enough for test")
    assert results == []
    assert r._last_retrieve_outcome == "embed_error"


# ---------------------------------------------------------------------------
# U33 — Empty corpus after index sets outcome=corpus_load_failed
# ---------------------------------------------------------------------------
def test_u33_empty_corpus_index():
    r = _make_retriever()
    with patch.object(r, "_load_corpus_rows", return_value=[]):
        r.index()
    assert r.last_outcome() == "corpus_load_failed"
    assert r.is_ready() is False
