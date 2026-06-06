"""
testlink_retriever.py - Semantic retriever over TestLink sanity test cases.

Given a QA bug brief, returns the single most relevant test case that shows
the normal working flow of the feature under test.  Used by gemini_client.py
to inject domain-knowledge context into the LLM prompt.

Design: mirrors bug_retriever.py (same model, same GCS cache pattern, same
log format) so both files can be maintained together.
"""

import hashlib
import json
import logging
import os
import time
from typing import Literal, Optional, TypedDict

import numpy as np

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# Type aliases
# ─────────────────────────────────────────────

IndexOutcome = Literal[
    "ok",
    "cache_hit",
    "cache_stale",
    "cache_miss",
    "model_load_failed",
    "corpus_load_failed",
    "disabled",
    "pending",
]

CacheSource = Literal["gcs", "recompute", "static_fallback", "none"]


class TestCaseEntry(TypedDict):
    tc_id: str
    name: str
    module: str
    preconditions: str
    steps: list[str]
    expected_outcomes: list[str]
    step_count: int


class RetrievedTestCase(TestCaseEntry):
    score: float


# ─────────────────────────────────────────────
# Retriever
# ─────────────────────────────────────────────


class TestLinkRetriever:
    MIN_SIMILARITY: float = 0.30
    CORPUS_PATH: str = "assets/testlink_cases.json"
    GCS_CACHE_BLOB: str = "testlink_embeddings.npz"

    def __init__(self, enabled: bool = True, use_gcs_cache: bool = True) -> None:
        self._enabled = enabled
        self._use_gcs_cache = use_gcs_cache

        self._matrix: Optional[np.ndarray] = None
        self._cases: list[TestCaseEntry] = []
        self._model = None
        self._content_hash: str = ""
        self._last_outcome: IndexOutcome = "disabled" if not enabled else "pending"
        self._last_cache_source: CacheSource = "none"
        self._cache_existed_but_mismatched: bool = False

    @classmethod
    def from_env(cls) -> "TestLinkRetriever":
        enabled = os.environ.get("TESTLINK_RAG_ENABLED", "true").lower() == "true"
        use_gcs_cache = os.environ.get("RAG_CACHE_GCS", "true").lower() == "true"
        return cls(enabled=enabled, use_gcs_cache=use_gcs_cache)

    def is_ready(self) -> bool:
        return self._matrix is not None and len(self._cases) > 0

    def last_outcome(self) -> IndexOutcome:
        return self._last_outcome

    def to_health_dict(self) -> dict:
        return {
            "enabled": self._enabled,
            "index_outcome": self._last_outcome,
            "corpus_size": len(self._cases),
            "model_name": "sentence-transformers/all-MiniLM-L6-v2",
            "cache_source": self._last_cache_source,
        }

    # ── Logging helpers ──────────────────────────────────────────────────────

    def _emit_index_log(
        self,
        started_at: float,
        outcome: IndexOutcome,
        source: CacheSource,
        corpus_size: int,
        detail: str = "",
    ) -> None:
        duration_ms = int((time.monotonic() - started_at) * 1000)
        self._last_outcome = outcome
        self._last_cache_source = source
        msg = (
            f"TESTLINK_INDEX outcome={outcome} duration_ms={duration_ms} "
            f"corpus_size={corpus_size} source={source}"
        )
        if detail:
            msg += f' detail="{detail}"'
        if outcome in ("model_load_failed", "corpus_load_failed"):
            logger.warning(msg)
        else:
            logger.info(msg)

    def _emit_retrieve_log(
        self,
        started_at: float,
        outcome: str,
        score: Optional[float] = None,
        name: Optional[str] = None,
    ) -> None:
        duration_ms = int((time.monotonic() - started_at) * 1000)
        msg = f"TESTLINK_RETRIEVE outcome={outcome} duration_ms={duration_ms}"
        if score is not None:
            msg += f" score={score:.2f}"
        if name is not None:
            msg += f' name="{name}"'
        if duration_ms > 250:
            logger.warning(msg)
        else:
            logger.info(msg)

    # ── Corpus loading ───────────────────────────────────────────────────────

    def _load_corpus_rows(self) -> list[TestCaseEntry]:
        try:
            with open(self.CORPUS_PATH, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
        except Exception as e:
            raise RuntimeError(f"failed to load {self.CORPUS_PATH}: {e}")

        entries: list[TestCaseEntry] = []
        for row in data:
            steps = [str(s) for s in row.get("steps", [])]
            expected_outcomes = [str(s) for s in row.get("expected_outcomes", [])]
            entry: TestCaseEntry = {
                "tc_id": str(row.get("tc_id", row.get("id", ""))),
                "name": str(row.get("name", "")),
                "module": str(row.get("module", "")),
                "preconditions": str(row.get("preconditions", "")),
                "steps": steps,
                "expected_outcomes": expected_outcomes,
                "step_count": len(steps),
            }
            if entry["tc_id"] and entry["name"]:
                entries.append(entry)

        return entries

    # ── Model ────────────────────────────────────────────────────────────────

    def _load_model(self):
        os.environ["TOKENIZERS_PARALLELISM"] = "false"
        try:
            from sentence_transformers import SentenceTransformer

            return SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
        except Exception as e:
            raise RuntimeError(f"failed to load model: {e}")

    def _embed_rows_l2_normalized(self, rows: list[TestCaseEntry]) -> np.ndarray:
        if not self._model:
            raise RuntimeError("Model not loaded")
        texts = [
            f"Module: {tc['module']} | {tc['name']} | "
            f"Preconditions: {tc['preconditions']} | "
            f"Steps: {' | '.join(tc['steps'][:6])}"
            for tc in rows
        ]
        embeddings = self._model.encode(
            texts, batch_size=16, normalize_embeddings=True, show_progress_bar=False
        )
        return embeddings.astype(np.float32)

    def _embed_query_l2_normalized(self, query: str) -> np.ndarray:
        if not self._model:
            raise RuntimeError("Model not loaded")
        return self._model.encode(query, normalize_embeddings=True).astype(np.float32)

    # ── Corpus hash ──────────────────────────────────────────────────────────

    def _compute_corpus_hash(self, rows: list[TestCaseEntry]) -> str:
        minimal = [
            {
                "id": r["tc_id"],
                "name": r["name"],
                "steps_joined": " | ".join(r["steps"]),
            }
            for r in rows
        ]
        minimal.sort(key=lambda r: r["id"])
        payload = json.dumps(
            minimal, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    # ── GCS helpers ──────────────────────────────────────────────────────────

    def _gcs_credentials_available(self) -> bool:
        try:
            if "GOOGLE_APPLICATION_CREDENTIALS" in os.environ and os.path.exists(
                os.environ["GOOGLE_APPLICATION_CREDENTIALS"]
            ):
                return True
            from google.auth import default  # type: ignore

            default()
            return True
        except Exception:
            return False

    def _gcs_get_blob(self, bucket_name: str, blob_name: str) -> Optional[bytes]:
        try:
            from google.cloud import storage

            client = storage.Client()
            bucket = client.bucket(bucket_name)
            blob = bucket.blob(blob_name)
            if not blob.exists():
                return None
            return blob.download_as_bytes()
        except Exception:
            return None

    def _try_load_cache(self, expected_hash: str) -> Optional[np.ndarray]:
        if not self._use_gcs_cache or not self._gcs_credentials_available():
            return None
        import tempfile

        try:
            data_bytes = self._gcs_get_blob("qa-bugbot-data", self.GCS_CACHE_BLOB)
            if not data_bytes:
                return None

            with tempfile.NamedTemporaryFile(delete=False, suffix=".npz") as f:
                f.write(data_bytes)
                f_name = f.name

            with np.load(f_name) as data:
                cached_hash = str(data["corpus_content_hash"][0])
                if cached_hash != expected_hash:
                    self._cache_existed_but_mismatched = True
                    os.unlink(f_name)
                    return None
                matrix = data["vectors"]
            os.unlink(f_name)
            return matrix
        except Exception:
            return None

    def _try_upload_cache(self, matrix: np.ndarray, content_hash: str) -> None:
        if not self._use_gcs_cache or not self._gcs_credentials_available():
            return
        import tempfile
        from datetime import datetime, timezone

        try:
            from google.cloud import storage

            client = storage.Client()
            bucket = client.bucket("qa-bugbot-data")
            blob = bucket.blob(self.GCS_CACHE_BLOB)

            with tempfile.NamedTemporaryFile(suffix=".npz", delete=False) as f:
                np.savez_compressed(
                    f.name,
                    vectors=matrix,
                    corpus_content_hash=np.array([content_hash], dtype="<U64"),
                    model_name=np.array(
                        ["sentence-transformers/all-MiniLM-L6-v2"], dtype="<U128"
                    ),
                    built_at=np.array(
                        [datetime.now(timezone.utc).isoformat()], dtype="<U32"
                    ),
                )
                f_name = f.name

            blob.upload_from_filename(f_name)
            os.unlink(f_name)
        except Exception as e:
            logger.info(
                f'GCS_SYNC op=upload outcome=error detail="testlink_embeddings: {e}"'
            )

    # ── Index ────────────────────────────────────────────────────────────────

    def index(self) -> None:
        started_at = time.monotonic()
        outcome: IndexOutcome = "disabled"
        source: CacheSource = "none"

        if not self._enabled:
            self._emit_index_log(started_at, "disabled", "none", 0)
            return

        try:
            try:
                rows = self._load_corpus_rows()
            except Exception as e:
                self._matrix = None
                self._cases = []
                self._emit_index_log(
                    started_at,
                    "corpus_load_failed",
                    "none",
                    0,
                    detail=f"{type(e).__name__}: {e}",
                )
                return

            if not rows:
                self._matrix = None
                self._cases = []
                self._emit_index_log(
                    started_at,
                    "corpus_load_failed",
                    "none",
                    0,
                    detail=f"no valid entries in {self.CORPUS_PATH}",
                )
                return

            try:
                self._model = self._load_model()
            except Exception as e:
                self._matrix = None
                self._cases = []
                self._emit_index_log(
                    started_at,
                    "model_load_failed",
                    "none",
                    0,
                    detail=f"{type(e).__name__}: {e}",
                )
                return

            self._content_hash = self._compute_corpus_hash(rows)

            matrix = self._try_load_cache(self._content_hash)
            if matrix is not None:
                outcome, source = "cache_hit", "gcs"
            else:
                try:
                    matrix = self._embed_rows_l2_normalized(rows)
                except Exception as e:
                    self._matrix = None
                    self._cases = []
                    self._emit_index_log(
                        started_at,
                        "model_load_failed",
                        "none",
                        0,
                        detail=f"embed failed: {type(e).__name__}: {e}",
                    )
                    return

                outcome = (
                    "cache_stale"
                    if self._cache_existed_but_mismatched
                    else "cache_miss"
                )
                source = "recompute"
                self._try_upload_cache(matrix, self._content_hash)

            self._matrix = matrix
            self._cases = rows
            self._emit_index_log(started_at, outcome, source, len(rows))
        except Exception as e:
            self._matrix = None
            self._cases = []
            self._last_outcome = f"error: {type(e).__name__} - {str(e)}"  # type: ignore[assignment]
            logger.error("Unexpected error in TESTLINK index: %s", e, exc_info=True)

    # ── Retrieve ─────────────────────────────────────────────────────────────

    def retrieve(self, query: str) -> Optional[dict]:
        """
        Return the single best-matching test case for *query*, or None if:
          - the index is not ready
          - query is too short (< 15 chars)
          - the best cosine similarity is below MIN_SIMILARITY
        """
        t0 = time.monotonic()

        if not self.is_ready():
            self._emit_retrieve_log(t0, "index_unavailable")
            return None

        if not query or len(query.strip()) < 15:
            self._emit_retrieve_log(t0, "short_query")
            return None

        try:
            q_vec = self._embed_query_l2_normalized(query)
        except Exception as e:
            logger.exception("TESTLINK_RETRIEVE embed_error: %s", e)
            self._emit_retrieve_log(t0, "embed_error")
            return None

        scores = self._matrix @ q_vec  # type: ignore[operator]
        best_idx = int(np.argmax(scores))
        best_score = float(scores[best_idx])

        if best_score < self.MIN_SIMILARITY:
            self._emit_retrieve_log(t0, "no_match", score=best_score)
            return None

        tc = self._cases[best_idx]
        result: dict = {**tc, "score": best_score}
        self._emit_retrieve_log(t0, "ok", score=best_score, name=tc["name"])
        return result

    # ── Prompt formatting ────────────────────────────────────────────────────

    def format_for_prompt(self, tc: dict) -> str:
        """
        Render a retrieved test case as a structured block ready to be
        embedded in a system prompt.
        """
        steps_block = "\n".join(
            f"  {i + 1}. {step}" for i, step in enumerate(tc.get("steps", []))
        )
        return (
            "## REFERENCE TEST CASE (normal working flow for this feature)\n"
            f"Name: {tc['name']}\n"
            f"Module: {tc['module']}\n"
            f"Preconditions: {tc['preconditions']}\n"
            "Steps (normal flow):\n"
            f"{steps_block}\n"
            "Use these steps as the baseline reproduction path.\n"
            'Stop at the step where the tester says it broke, then add "Observe that [issue]".\n'
            "Do NOT use expected_outcomes as the expected_behavior field "
            "— describe what SHOULD happen for the specific bug instead."
        )


# ─────────────────────────────────────────────
# Module-level singleton (mirrors bug_retriever pattern)
# ─────────────────────────────────────────────

_testlink_retriever: Optional[TestLinkRetriever] = None


def init_testlink_retriever() -> TestLinkRetriever:
    """Initialise (once) and return the module-level TestLinkRetriever."""
    global _testlink_retriever
    if _testlink_retriever is None:
        _testlink_retriever = TestLinkRetriever.from_env()
        _testlink_retriever.index()
    return _testlink_retriever


def get_testlink_retriever() -> Optional[TestLinkRetriever]:
    """Return the singleton if already initialised, otherwise None."""
    return _testlink_retriever
