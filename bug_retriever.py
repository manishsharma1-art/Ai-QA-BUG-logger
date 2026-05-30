"""
bug_retriever.py - RAG few-shot retrieval logic.
"""
import json
import logging
import time
import os
import hashlib
from typing import Optional, Literal, TypedDict, Any

import numpy as np
# lazy load sentence_transformers in _load_model to save startup time

logger = logging.getLogger(__name__)

class CorpusEntry(TypedDict):
    id: str
    subject: str
    description_raw: str
    project: str
    project_id: Optional[int]
    priority: str
    bug_type: str
    environment: str
    category: Optional[str]

IndexOutcome = Literal[
    "ok",
    "cache_hit",
    "cache_stale",
    "cache_miss",
    "model_load_failed",
    "corpus_load_failed",
    "disabled",
]

CacheSource = Literal["gcs", "recompute", "static_fallback", "none"]

class RetrievedExample(TypedDict):
    id: str
    subject: str
    description_raw: str
    project: str
    project_id: Optional[int]
    priority: str
    bug_type: str
    environment: str
    category: Optional[str]
    score: float
    matched_project: bool

class RetrieveOutcome(TypedDict):
    examples: list[RetrievedExample]
    log_outcome: Literal[
        "ok",
        "index_unavailable",
        "embed_error",
        "empty_corpus",
        "short_brief",
    ]
    duration_ms: int
    matched_in_project: int

class BugRetriever:
    def __init__(self, enabled: bool = True, top_k: int = 5, use_gcs_cache: bool = True):
        self._enabled = enabled
        self._top_k = max(1, min(int(top_k), 20))
        self._use_gcs_cache = use_gcs_cache
        
        self._matrix: Optional[np.ndarray] = None
        self._entries: list[CorpusEntry] = []
        self._project_id_array: Optional[np.ndarray] = None
        self._model = None
        self._content_hash: str = ""
        self._last_outcome: IndexOutcome = "disabled" if not enabled else "ok"
        self._last_cache_source: CacheSource = "none"
        self._cache_existed_but_mismatched = False
        
    @classmethod
    def from_env(cls) -> "BugRetriever":
        enabled = os.environ.get("RAG_ENABLED", "true").lower() == "true"
        top_k = int(os.environ.get("RAG_TOPK", "5"))
        use_gcs_cache = os.environ.get("RAG_CACHE_GCS", "true").lower() == "true"
        return cls(enabled=enabled, top_k=top_k, use_gcs_cache=use_gcs_cache)

    def is_ready(self) -> bool:
        return self._matrix is not None and len(self._entries) > 0

    def last_outcome(self) -> IndexOutcome:
        return self._last_outcome

    def to_health_dict(self) -> dict:
        return {
            "enabled": self._enabled,
            "index_outcome": self._last_outcome,
            "corpus_size": len(self._entries),
            "embedding_dim": 384,
            "model_name": "sentence-transformers/all-MiniLM-L6-v2",
            "top_k": self._top_k,
            "cache_source": getattr(self, "_last_cache_source", "none")
        }

    def _emit_index_log(self, started_at: float, outcome: IndexOutcome, source: CacheSource, corpus_size: int, detail: str = "") -> None:
        duration_ms = int((time.monotonic() - started_at) * 1000)
        self._last_outcome = outcome
        self._last_cache_source = source
        msg = f"RAG_INDEX outcome={outcome} duration_ms={duration_ms} corpus_size={corpus_size} source={source} embedding_dim=384"
        if detail:
            msg += f" detail=\"{detail}\""
        if outcome in ("model_load_failed", "corpus_load_failed"):
            logger.warning(msg)
        else:
            logger.info(msg)

    def _emit_retrieve_log(self, started_at: float, phase: str, outcome: str, k: int, corpus_size: int, project_filter: Optional[int], matched: int) -> None:
        duration_ms = int((time.monotonic() - started_at) * 1000)
        p_filter = project_filter if project_filter is not None else "none"
        msg = f"RAG_RETRIEVE phase={phase} outcome={outcome} duration_ms={duration_ms} k={k} corpus_size={corpus_size} project_filter={p_filter} matched_in_project={matched}"
        if duration_ms > 250:
            logger.warning(msg)
        else:
            logger.info(msg)

    def _load_corpus_rows(self) -> list[CorpusEntry]:
        import json
        from config import OP_PROJECTS
        try:
            with open("assets/training_examples.json", "r", encoding="utf-8-sig") as f:
                data = json.load(f)
        except Exception as e:
            raise RuntimeError(f"failed to load training_examples.json: {e}")
        
        entries: list[CorpusEntry] = []
        for row in data:
            project_name = row.get("project", "")
            # lookup by exact match
            pid = OP_PROJECTS.get(project_name)
            if pid is None:
                # try case insensitive
                for k, v in OP_PROJECTS.items():
                    if k.lower() == project_name.lower():
                        pid = v
                        break
            
            entry: CorpusEntry = {
                "id": str(row.get("id", "")),
                "subject": str(row.get("subject", "")),
                "description_raw": str(row.get("description_raw", "")),
                "project": str(project_name),
                "project_id": pid,
                "priority": str(row.get("priority", "")),
                "bug_type": str(row.get("bug_type", "")),
                "environment": str(row.get("environment", "")),
                "category": row.get("category"),
            }
            if entry["id"] and entry["subject"]:
                entries.append(entry)
                
        return entries

    def _load_model(self):
        os.environ["TOKENIZERS_PARALLELISM"] = "false"
        try:
            from sentence_transformers import SentenceTransformer
            return SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
        except Exception as e:
            raise RuntimeError(f"failed to load model: {e}")

    def _embed_rows_l2_normalized(self, rows: list[CorpusEntry]) -> np.ndarray:
        if not self._model:
            raise RuntimeError("Model not loaded")
        texts = [
            f"Subject: {r['subject']}\nDescription: {r['description_raw']}"
            for r in rows
        ]
        embeddings = self._model.encode(texts, batch_size=32, normalize_embeddings=True)
        return embeddings.astype(np.float32)

    def _embed_query_l2_normalized(self, query: str) -> np.ndarray:
        if not self._model:
            raise RuntimeError("Model not loaded")
        return self._model.encode(query, normalize_embeddings=True).astype(np.float32)


    def _compute_corpus_hash(self, rows: list[CorpusEntry]) -> str:
        minimal = [
            {"id":               r["id"],
             "subject":          r["subject"],
             "description_raw":  r["description_raw"]}
            for r in rows
        ]
        minimal.sort(key=lambda r: r["id"])
        payload = json.dumps(minimal, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def _gcs_credentials_available(self) -> bool:
        try:
            if "GOOGLE_APPLICATION_CREDENTIALS" in os.environ and os.path.exists(os.environ["GOOGLE_APPLICATION_CREDENTIALS"]):
                return True
            from google.auth import default # type: ignore
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
            data_bytes = self._gcs_get_blob("qa-bugbot-data", "embeddings.npz")
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
            blob = bucket.blob("embeddings.npz")
            
            with tempfile.NamedTemporaryFile(suffix=".npz", delete=False) as f:
                np.savez_compressed(
                    f.name,
                    vectors=matrix,
                    corpus_content_hash=np.array([content_hash], dtype="<U64"),
                    model_name=np.array(["sentence-transformers/all-MiniLM-L6-v2"], dtype="<U128"),
                    embedding_dim=np.array([384], dtype=np.int32),
                    built_at=np.array([datetime.now(timezone.utc).isoformat()], dtype="<U32")
                )
                f_name = f.name
            
            blob.upload_from_filename(f_name)
            os.unlink(f_name)
        except Exception as e:
            logger.info(f'GCS_SYNC op=upload outcome=error detail="rag_embeddings: {e}"')

    def index(self) -> None:
        started_at = time.monotonic()
        outcome: IndexOutcome = "disabled"
        source: CacheSource = "none"

        if not self._enabled:
            self._emit_index_log(started_at, "disabled", "none", 0)
            return

        try:
            rows = self._load_corpus_rows()
        except Exception as e:
            self._matrix = None
            self._entries = []
            self._emit_index_log(started_at, "corpus_load_failed", "none", 0, detail=f"{type(e).__name__}: {e}")
            return
            
        if not rows:
            self._matrix = None
            self._entries = []
            self._emit_index_log(started_at, "corpus_load_failed", "none", 0, detail="no valid entries in training_examples.json")
            return

        try:
            self._model = self._load_model()
        except Exception as e:
            self._matrix = None
            self._entries = []
            self._emit_index_log(started_at, "model_load_failed", "none", 0, detail=f"{type(e).__name__}: {e}")
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
                self._entries = []
                self._emit_index_log(started_at, "model_load_failed", "none", 0, detail=f"embed failed: {type(e).__name__}: {e}")
                return
            
            outcome = "cache_stale" if self._cache_existed_but_mismatched else "cache_miss"
            source = "recompute"
            self._try_upload_cache(matrix, self._content_hash)

        self._matrix = matrix
        self._entries = rows
        self._project_id_array = np.array([r["project_id"] if r["project_id"] is not None else -1 for r in rows], dtype=np.int32)
        self._emit_index_log(started_at, outcome, source, len(rows))

    def _finish(self, started_at: float, examples: list[RetrievedExample], outcome: str, k: int, project_filter: Optional[int], matched_in_project: int, phase: str) -> list[RetrievedExample]:
        self._emit_retrieve_log(started_at, phase, outcome, k, len(self._entries), project_filter, matched_in_project)
        self._last_retrieve_outcome = outcome
        return examples

    def retrieve(
        self,
        query: str,
        k: int = 5,
        project_filter: Optional[int] = None,
        *,
        phase: Literal["phase1", "phase2"] = "phase1",
    ) -> list[RetrievedExample]:
        t0 = time.monotonic()
        k = max(1, min(int(k), 20))

        if not self.is_ready():
            return self._finish(t0, [], "index_unavailable", k, project_filter, 0, phase)

        short = (query is None) or (len(query.strip()) < 20)
        
        try:
            q = self._embed_query_l2_normalized(query or "")
        except Exception as e:
            logger.exception("RAG_RETRIEVE embed_error: %s", e)
            return self._finish(t0, [], "embed_error", k, project_filter, 0, phase)

        if self._matrix is None or len(self._entries) == 0:
            return self._finish(t0, [], "empty_corpus", k, project_filter, 0, phase)

        scores = self._matrix @ q

        if project_filter is not None and self._project_id_array is not None:
            same_project_mask = self._project_id_array == project_filter
            scores = scores + (same_project_mask * 0.05)

        if len(scores) <= k:
            idx = np.argsort(-scores)
        else:
            partition = np.argpartition(-scores, -k)[-k:]
            idx = partition[np.argsort(-scores[partition])]

        examples: list[RetrievedExample] = []
        matched_in_project = 0
        for i in idx:
            e = self._entries[i]
            matched = (project_filter is not None and e["project_id"] == project_filter)
            if matched:
                matched_in_project += 1
            examples.append({**e, "score": float(scores[i]), "matched_project": matched})

        outcome = "short_brief" if short else "ok"
        return self._finish(t0, examples, outcome, k, project_filter, matched_in_project, phase)

_retriever: Optional["BugRetriever"] = None

def init_retriever() -> "BugRetriever":
    global _retriever
    if _retriever is None:
        _retriever = BugRetriever.from_env()
        _retriever.index()
    return _retriever

def get_retriever() -> Optional["BugRetriever"]:
    return _retriever
