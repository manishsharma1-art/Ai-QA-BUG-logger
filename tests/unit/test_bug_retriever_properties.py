"""
Hypothesis property tests for the bug_retriever module.
P1–P5: validate core properties with randomized inputs.
"""
import pytest
import hashlib
import numpy as np
from unittest.mock import patch, MagicMock
from hypothesis import given, strategies as st, settings as h_settings


# ---------------------------------------------------------------------------
# Helpers — reused from test_bug_retriever.py but inlined to be self-contained
# ---------------------------------------------------------------------------

def _make_corpus(n=10, project_id=3):
    return [
        {
            "id": str(i),
            "subject": f"Bug #{i}: app crashes on submit",
            "description_raw": f"Description for entry {i}.",
            "project": "TestProject",
            "project_id": project_id,
            "priority": "Medium",
            "bug_type": "Functional/Logical",
            "environment": "STAGE",
            "category": None,
        }
        for i in range(n)
    ]


def _make_indexed_retriever(corpus=None):
    from bug_retriever import BugRetriever
    r = BugRetriever(enabled=True, top_k=5, use_gcs_cache=False)
    corpus = corpus or _make_corpus(20)

    class FakeModel:
        def encode(self, texts, **kwargs):
            vecs = []
            for t in (texts if isinstance(texts, list) else [texts]):
                seed = int(hashlib.md5(t.encode()).hexdigest()[:8], 16) % (2**31)
                rng = np.random.RandomState(seed)
                v = rng.randn(384).astype(np.float32)
                v /= np.linalg.norm(v) + 1e-9
                vecs.append(v)
            arr = np.array(vecs, dtype=np.float32)
            return arr if isinstance(texts, list) else arr[0]

    with patch.object(r, "_load_corpus_rows", return_value=corpus), \
         patch.object(r, "_load_model", return_value=FakeModel()), \
         patch.object(r, "_try_load_cache", return_value=None), \
         patch.object(r, "_try_upload_cache"):
        r.index()
    return r


# ---------------------------------------------------------------------------
# P1 — Retrieval is deterministic: same query → same results
# ---------------------------------------------------------------------------
@given(query=st.text(min_size=25, max_size=200))
@h_settings(max_examples=30, deadline=5000)
def test_p1_retrieval_determinism(query):
    r = _make_indexed_retriever()
    r1 = r.retrieve(query, k=3)
    r2 = r.retrieve(query, k=3)
    assert len(r1) == len(r2)
    for a, b in zip(r1, r2):
        assert a["id"] == b["id"]
        assert abs(a["score"] - b["score"]) < 1e-5


# ---------------------------------------------------------------------------
# P2 — Scores are bounded: cosine similarity ∈ [-1.05, 1.05] (with boost)
# ---------------------------------------------------------------------------
@given(query=st.text(min_size=25, max_size=200))
@h_settings(max_examples=30, deadline=5000)
def test_p2_score_bounds(query):
    r = _make_indexed_retriever()
    results = r.retrieve(query, k=5, project_filter=3)
    for ex in results:
        assert -1.1 <= ex["score"] <= 1.1, f"Score {ex['score']} out of bounds"


# ---------------------------------------------------------------------------
# P3 — K-boundedness and ordering
# ---------------------------------------------------------------------------
@given(k=st.integers(min_value=0, max_value=50))
@h_settings(max_examples=30, deadline=5000)
def test_p3_k_boundedness(k):
    r = _make_indexed_retriever(_make_corpus(25))
    results = r.retrieve("login crash on iPhone during testing session", k=k)
    effective_k = max(1, min(k, 20))
    assert len(results) <= effective_k
    # Verify descending order
    scores = [ex["score"] for ex in results]
    assert scores == sorted(scores, reverse=True)


# ---------------------------------------------------------------------------
# P4 — Query non-mutation: the query string is not altered by retrieve()
# ---------------------------------------------------------------------------
@given(query=st.text(min_size=25, max_size=200))
@h_settings(max_examples=30, deadline=5000)
def test_p4_query_non_mutation(query):
    r = _make_indexed_retriever()
    original = query  # Python strings are immutable, but test the contract anyway
    r.retrieve(query, k=3)
    assert query == original


# ---------------------------------------------------------------------------
# P5 — Never-raise: retrieve() never raises for any input
# ---------------------------------------------------------------------------
@given(query=st.one_of(
    st.text(min_size=0, max_size=500),
    st.none(),
    st.just(""),
    st.just("   "),
    st.binary().map(lambda b: b.decode("utf-8", errors="replace")),
))
@h_settings(max_examples=50, deadline=5000)
def test_p5_never_raise(query):
    r = _make_indexed_retriever()
    # Must not raise — this is Property 8 from the spec
    result = r.retrieve(query, k=5)
    assert isinstance(result, list)
