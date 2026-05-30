# Requirements Document

## Introduction

The QA Bug Logger Bot (`qa-bugbot`, `asia-south1`, currently revision
`qa-bugbot-00042-8zj`) currently augments its LLM prompts with a **static
top-50 few-shot block** loaded once at module import in `gemini_client.py`
(`_load_few_shot_block(max_examples=50)`). Every webhook receives the same
50 examples regardless of whether the bug is about LMS Webview, Photo
Search, Desktop PDP, or WebERP. The block contributes ~14,700 prompt tokens
and adds ~4.4s to Phase 1 latency. Empirically, more than 100 examples hits
a gateway timeout cliff and is unsafe.

This feature replaces the static block with **retrieval-augmented few-shot
selection**. A new module `bug_retriever.py` will:

1. At cold start, embed all curated training tickets in
   `assets/training_examples.json` (~600 entries) using a local
   `sentence-transformers/all-MiniLM-L6-v2` model into an in-memory
   `numpy.ndarray(N, 384)` corpus matrix.
2. For each Phase 1 (`analyze_text_brief`) and Phase 2 (`enrich_with_media`)
   call, embed the QA brief, retrieve the top-K most similar past tickets
   by cosine similarity, and inject only those K examples into the prompt
   for that one call.
3. Fall back to the existing static 50-example block (or an empty block) if
   the retriever cannot load, embed, or score for any reason. The bot must
   never raise an error to the QA tester because of retrieval.

This directly targets **Score A "Bug Extraction Accuracy"** axes from the
QA audit:

- **Workflow sequence** — examples retrieved by semantic similarity teach
  the LLM the correct step order for the actual feature being reported,
  not a generic average of all 600 tickets.
- **No hallucinations** — examples grounded in the same product surface as
  the brief reduce the LLM's tendency to invent UI elements that do not
  exist on, e.g., the Msite when the bug is on Desktop PDP.
- **Terminology preservation** — retrieved examples are real OpenProject
  tickets whose vocabulary matches the brief, reinforcing project-specific
  terms (BL Webview, Photo Search, Mini Catalog) instead of diluting them.

The retrieval feature MUST coexist with the existing deterministic
`bucket_router.py`. Bucket routing remains Python-first; this feature only
selects which examples go into the LLM prompt, never which OpenProject
project the ticket is filed under.

This document is addressed to three stakeholder roles:

- **QA tester** — submits bug reports via Google Chat and expects faster,
  more accurate, terminology-faithful tickets without any new failure
  modes.
- **Operations / on-call engineer** — needs greppable diagnostic logs,
  health-endpoint surfacing of the retriever state, and clear SLOs to
  triage retrieval degradation.
- **Developer / contributor** — needs deterministic local verification
  that retrieval does not regress the 190 unit tests or the 9 synthetic
  webhook scenarios, and a clear contract for the new module.

## Glossary

- **Phase 1** — Text-only LLM analysis of the QA tester's brief
  (`gemini_client.analyze_text_brief`). Single attempt, ≤22s
  `asyncio.wait_for` deadline, no retries.
- **Phase 2** — Media-enriched LLM analysis (`gemini_client.enrich_with_media`)
  that combines the Phase 1 result, the original brief, and extracted
  video/screenshot frames. Single attempt, ≤50s `asyncio.wait_for` deadline.
- **Bucket router** — `bucket_router.py` module. Deterministic Python
  routing that selects the OpenProject project id from the brief. Out of
  scope for this feature except as a soft retrieval signal.
- **`text_for_llm`** — The brief text returned by
  `bucket_router.extract_bucket_with_provenance` for use in LLM prompts.
  Byte-identical to the user's input, with the original `[Tag]` preserved
  (RC5 contract).
- **Retriever** — `bug_retriever.BugRetriever`, the new module's main
  class. Owns the embedding model, the corpus matrix, and the
  `retrieve(query: str, k: int, project_id: int | None) -> list[Example]`
  method.
- **Corpus** — The set of curated training tickets in
  `assets/training_examples.json` plus their precomputed embeddings.
  Approximately 600 entries; corpus matrix shape `(N, 384)` in `float32`,
  approximately 0.9 MB.
- **Embedding model** — `sentence-transformers/all-MiniLM-L6-v2` loaded
  via the `sentence-transformers` Python package. CPU inference,
  approximately 22 MB on disk, approximately 5 ms per 256-token
  embedding on Cloud Run's standard CPU.
- **K** — The number of nearest examples retrieved per call. Default 5,
  configurable via the `RAG_TOPK` environment variable, bounded to
  `1 <= K <= 20`.
- **Static fallback block** — The existing
  `gemini_client._load_few_shot_block(max_examples=50)` output. The
  retriever falls back to this whenever a retrieval cannot be served.
- **Empty fallback** — An empty string used when both the retriever and
  the static fallback block are unavailable. The LLM still receives the
  base `SYSTEM_PROMPT` rules.
- **Cosine similarity** — `numpy` dot product of L2-normalized vectors.
  Used as the ranking score for retrieval. All corpus and query vectors
  are L2-normalized at write time so retrieval reduces to a single
  matrix-vector multiply.
- **Embedding cache** — A persisted `embeddings.npz` file containing the
  corpus matrix and a content-hash header. Stored at
  `gs://qa-bugbot-data/embeddings.npz`. Lets new container instances
  skip the embedding pass on cold start.
- **Corpus content hash** — A `sha256` of the sorted, JSON-canonicalized
  list of `(id, subject, description_raw)` triples from
  `assets/training_examples.json`. Stored alongside the cached matrix
  to detect a stale cache after the training corpus changes.
- **`RAG_INDEX`** — Greppable structured log line emitted exactly once at
  startup describing the index-build outcome. Format:
  `RAG_INDEX outcome=<ok|cache_hit|cache_stale|cache_miss|model_load_failed|corpus_load_failed|disabled> duration_ms=<n> corpus_size=<n> source=<gcs|recompute|static_fallback|none> embedding_dim=<n>`.
- **`RAG_RETRIEVE`** — Greppable structured log line emitted on every
  retrieval attempt. Format:
  `RAG_RETRIEVE phase=<phase1|phase2> outcome=<ok|index_unavailable|embed_error|empty_corpus|short_brief> duration_ms=<n> k=<n> corpus_size=<n> project_filter=<project_id_or_none> matched_in_project=<n>`.
- **`/health.rag`** — A new sub-object on the existing `/health` endpoint
  exposing the most recent `RAG_INDEX` outcome, corpus size, embedding
  dimension, model name, and whether the in-memory corpus is currently
  loaded.
- **Deterministic-Python-first** — The architectural rule that
  `bucket_router.py` selects the OpenProject project, not the LLM, and
  not the retriever. The retriever consumes the routed `project_id` only
  as a soft scoring signal.
- **Soft project filter** — Retrieval scoring boost applied to corpus
  entries whose `project` field matches the routed bucket. Does NOT
  exclude cross-project examples; only re-ranks them.

## Requirements

### Requirement 1: Build the embedding index at cold start

**User Story:** As an operations engineer, I want the embedding index for
all curated training tickets to be built once at container startup so
that the retriever is ready to serve the first webhook without surprise
latency, and so that startup does not exceed the documented cold-start
budget.

#### Acceptance Criteria

1. WHEN the FastAPI lifespan startup hook runs, THE Retriever SHALL load
   the `sentence-transformers/all-MiniLM-L6-v2` model and build an
   in-memory L2-normalized corpus matrix of shape `(N, 384)` from
   `assets/training_examples.json`.
2. WHEN the index build completes, THE Retriever SHALL emit exactly one
   `RAG_INDEX` log line whose `outcome` is one of `ok`, `cache_hit`,
   `cache_stale`, `cache_miss`, `model_load_failed`,
   `corpus_load_failed`, or `disabled`, and whose `duration_ms`,
   `corpus_size`, `source`, and `embedding_dim` fields are populated.
3. THE Retriever SHALL complete the index build within 3000 milliseconds
   of cold start when the embedding cache is hit, measured from the
   start of the lifespan startup hook to the emission of the `RAG_INDEX`
   log line.
4. THE Retriever SHALL complete the index build within 30000 milliseconds
   of cold start when no cache is available and all 600 corpus entries
   are embedded fresh on CPU.
5. WHILE the index build is in progress, THE Bot SHALL continue to
   accept webhook traffic and serve any in-flight request using the
   static fallback block defined in `gemini_client._load_few_shot_block`.
   This SHALL only apply during the index build window; once the index
   build emits its `RAG_INDEX` log line, normal retrieval-backed prompts
   resume per Requirement 2.
6. IF the embedding model cannot be downloaded or loaded, THEN THE
   Retriever SHALL set its in-memory corpus to empty, emit
   `RAG_INDEX outcome=model_load_failed`, and SHALL NOT raise an
   exception to the lifespan handler.
7. IF `assets/training_examples.json` is missing, malformed, or contains
   zero valid entries, THEN THE Retriever SHALL set its in-memory
   corpus to empty, emit `RAG_INDEX outcome=corpus_load_failed`, and
   SHALL NOT raise an exception to the lifespan handler.
8. WHERE the environment variable `RAG_ENABLED=false` is set, THE
   Retriever SHALL skip the index build entirely, emit
   `RAG_INDEX outcome=disabled source=none`, and the system SHALL behave
   exactly as it does today (static 50-example block in every prompt).

### Requirement 2: Retrieve top-K examples per LLM call

**User Story:** As a QA tester, I want each of my bug briefs to be
analyzed using the few-shot examples most semantically similar to my
specific bug so that the resulting ticket has correct workflow
sequencing, no hallucinated UI elements, and faithful product
terminology.

#### Acceptance Criteria

1. WHEN `gemini_client.analyze_text_brief` is invoked with a non-empty
   `text_for_llm` value, THE Retriever SHALL embed `text_for_llm` and
   return the top K corpus entries ranked by cosine similarity, where K
   is read once at startup from the `RAG_TOPK` environment variable and
   defaults to 5 with a hard bound of `1 <= K <= 20`.
2. WHEN `gemini_client.enrich_with_media` is invoked with a non-empty
   brief, THE Retriever SHALL be queried with the same brief
   (`text_for_llm`) using the same K value and the same scoring rule as
   Phase 1.
3. THE Retriever SHALL embed and rank the query against the brief
   `text_for_llm`, not the bucket-stripped `text`, so that `[Tag]`
   tokens contribute to retrieval signal as well as to bucket routing.
4. THE Retriever SHALL return retrieved examples as a list ordered by
   descending cosine similarity, each entry exposing the same fields the
   existing `_format_example` helper consumes (`subject`,
   `description_raw`, `project`, `priority`, `bug_type`, `environment`,
   `category`).
5. WHEN the retriever returns K examples, `gemini_client` SHALL replace
   the static fallback block in the prompt for that one call with a
   block rendered from the retrieved examples, and SHALL NOT include
   both the static block and the retrieved block in the same prompt.
6. IF the brief passed to the retriever is fewer than 20 characters in
   length, THEN THE Retriever SHALL still attempt retrieval, SHALL emit
   `RAG_RETRIEVE outcome=short_brief` along with its result, and the
   caller SHALL use the retrieved block when retrieval succeeds.
7. THE Retriever SHALL complete a single retrieval (embed + rank +
   format) in fewer than 100 milliseconds at the 99th percentile,
   measured from the entry of `retrieve()` to its return, with
   `corpus_size` up to 1000.

### Requirement 3: Soft project filter from bucket router

**User Story:** As a QA tester filing a Photo Search bug, I want the
retrieved examples to be biased toward Photo Search past tickets so the
LLM sees the right product surface, while still allowing cross-project
examples to fill the K slots when same-project examples are insufficient
or less semantically relevant.

#### Acceptance Criteria

1. WHEN `gemini_client.analyze_text_brief` is invoked with a `project_id`
   argument resolved by `bucket_router.extract_bucket_with_provenance`,
   THE Retriever SHALL accept that `project_id` as a `project_filter`
   parameter and apply it as a soft scoring boost.
2. WHEN a corpus entry's `project` field maps via `config.OP_PROJECTS`
   to the same numeric `project_id` as the `project_filter`, THE
   Retriever SHALL add a fixed bonus of `0.05` to that entry's cosine
   similarity score before top-K selection.
3. THE Retriever SHALL NOT exclude any corpus entry from candidate
   selection on the basis of project mismatch; the soft filter SHALL
   only re-rank.
4. THE Retriever SHALL include in its `RAG_RETRIEVE` log line a
   `matched_in_project=<n>` field reporting how many of the K returned
   examples carry the same `project_id` as the soft filter.
5. WHEN `bucket_router.extract_bucket_with_provenance` returns a
   provenance value of `default` (no project resolved), THE Retriever
   SHALL be invoked with `project_filter=None` and SHALL apply no
   project-based scoring boost.
6. WHEN `project_filter` is `None`, THE Retriever SHALL log
   `project_filter=none matched_in_project=0` and SHALL rank purely by
   cosine similarity.

### Requirement 4: Never-raise fallback contract

**User Story:** As a QA tester, I want my bug brief to always be analyzed
and ticketed even when the retriever degrades, so that retrieval
infrastructure problems never surface to me as a Google Chat error.

#### Acceptance Criteria

1. IF the retriever's in-memory corpus is empty at the moment Phase 1 or
   Phase 2 invokes it, THEN THE Retriever SHALL return an empty list,
   emit `RAG_RETRIEVE outcome=empty_corpus`, and the caller SHALL fall
   back to the existing static 50-example block.
2. IF the embedding model raises during query embedding, THEN THE
   Retriever SHALL catch the exception, return an empty list, emit
   `RAG_RETRIEVE outcome=embed_error`, and the caller SHALL fall back
   to the existing static 50-example block.
3. IF the retriever module fails to import for any reason at FastAPI
   startup, THEN `gemini_client` SHALL operate exactly as it does
   before this feature shipped: every prompt SHALL receive the existing
   static 50-example block.
4. THE Retriever SHALL NOT raise any exception across the
   `retrieve(query, k, project_filter)` interface for any input that
   `gemini_client.analyze_text_brief` or `gemini_client.enrich_with_media`
   can pass to it, including empty strings, strings longer than 8000
   characters, strings containing only non-ASCII characters, and
   strings containing only whitespace.
5. WHEN the retriever returns an empty list to a caller, THE caller
   SHALL substitute the static 50-example block into the prompt and
   SHALL proceed with the LLM call without altering its existing
   `max_tokens`, `client_timeout`, or `asyncio.wait_for` parameters.
6. IF the static fallback block is itself empty (e.g., training file
   missing), THEN THE caller SHALL render the prompt with no examples
   block and SHALL proceed with the LLM call.
7. THE feature SHALL NOT introduce any new path by which a Google Chat
   webhook returns HTTP 500 or sends an error message to the user that
   would not have been sent under the pre-feature behavior.

### Requirement 5: Latency and deadline budget

**User Story:** As an operations engineer, I want the retriever to
respect the existing Phase 1 22-second deadline and the 30-second
Google Chat webhook deadline so that adding RAG never causes timeouts
where the static-block path would have succeeded.

#### Acceptance Criteria

1. THE Retriever SHALL complete a single `retrieve()` call in fewer
   than 100 milliseconds at the 99th percentile when measured against
   the production corpus size of at most 1000 entries.
2. WHEN a single `retrieve()` call exceeds 250 milliseconds, THE
   Retriever SHALL emit a WARNING-level log line with the same
   `RAG_RETRIEVE` format and outcome `ok`, allowing operators to grep
   for slow calls.
3. THE feature SHALL NOT increase Phase 1 end-to-end latency
   (`analyze_text_brief` total wall time including LLM call) beyond the
   existing 22-second `asyncio.wait_for` ceiling.
4. THE feature SHALL NOT increase Phase 2 end-to-end latency
   (`enrich_with_media` total wall time) beyond the existing 50-second
   `asyncio.wait_for` ceiling.
5. WHERE retrieval-time logs show that the prompt token count for an
   LLM call has dropped from approximately 14,700 (static 50 examples)
   to approximately 1,500–3,500 (5 retrieved examples), THE feature
   SHALL deliver the median Phase 1 LLM-call latency reduction of at
   least 1500 milliseconds compared with the static 50-example baseline.
6. THE Retriever SHALL not perform any synchronous blocking I/O
   (network, disk write, GCS call) inside `retrieve()`; all such I/O
   SHALL be confined to the startup index build and the optional cache
   write paths.

### Requirement 6: Observability and health

**User Story:** As an on-call engineer, I want greppable structured logs
and a `/health` field telling me whether retrieval is live, what the
corpus size is, and how the most recent retrieval performed, so that I
can triage retrieval degradation without GCP console access.

#### Acceptance Criteria

1. THE Retriever SHALL emit exactly one `RAG_INDEX` log line at startup
   matching the format defined in the Glossary.
2. THE Retriever SHALL emit exactly one `RAG_RETRIEVE` log line per
   call to `retrieve()`, regardless of outcome, matching the format
   defined in the Glossary.
3. THE `/health` endpoint SHALL include a `rag` sub-object containing
   the fields `enabled` (bool), `index_outcome` (string from the
   `RAG_INDEX` outcome enum), `corpus_size` (int), `embedding_dim`
   (int), `model_name` (string), `top_k` (int), and `cache_source`
   (one of `gcs`, `recompute`, `static_fallback`, `none`). The
   `enabled` field SHALL reflect the environment-variable configuration
   (`RAG_ENABLED`), not the runtime state of the in-memory index. A
   value of `enabled=true` with `corpus_size=0` is permitted and means
   "RAG was requested but the index failed to build" — operators
   distinguish this from a feature-flagged-off state by `index_outcome`.
4. WHEN `RAG_ENABLED=false`, THE `/health.rag.enabled` field SHALL be
   `false` and `/health.rag.corpus_size` SHALL be `0`, regardless of
   any in-memory state that may exist for diagnostic purposes.
5. THE `RAG_RETRIEVE` log line SHALL include `phase`, `outcome`,
   `duration_ms`, `k`, `corpus_size`, `project_filter`, and
   `matched_in_project` fields so that operators can compute per-phase
   p99 latency and project-filter hit rate by `grep` and `awk`.
6. WHERE the existing `LLM_CALL` log line is emitted from
   `_log_llm_call`, THE feature SHALL extend its `extra` dict with
   `rag_examples=<n>` and `rag_outcome=<RAG_RETRIEVE outcome>` so that
   each LLM call's prompt context is observable on a single grep.
7. THE feature SHALL NOT remove, rename, or change the format of any
   existing log marker (`LLM_CALL`, `OP_CALL`, `GCS_SYNC`,
   `ENV_VALIDATION`, `BUILD_MARKER`, `PHASE2_TRUNCATED`,
   `PHASE2_DEFAULT_STUFFED`, `PHASE2_SLOW`, `PRIORITY_AMBIGUOUS`).

### Requirement 7: Embedding cache and cross-deploy persistence

**User Story:** As an operations engineer, I want a newly-started
container to skip the 30-second fresh-embed cold start when the corpus
has not changed, so that scale-up events and rolling deployments do not
introduce a noticeable latency cliff for the first request on a new
instance.

#### Acceptance Criteria

1. WHEN the index build starts and the `RAG_CACHE_GCS` environment
   variable is set to a truthy value (default `true`), THE Retriever
   SHALL attempt to download `gs://qa-bugbot-data/embeddings.npz` and
   load it into memory before falling back to fresh embedding.
2. WHEN the cached file's `corpus_content_hash` header equals the
   sha256 of the current `assets/training_examples.json` content, THE
   Retriever SHALL accept the cached corpus matrix as authoritative
   and SHALL emit `RAG_INDEX outcome=cache_hit source=gcs`.
3. WHEN the cached file's `corpus_content_hash` does not equal the
   current corpus hash, THE Retriever SHALL discard the cache, embed
   the current corpus fresh, emit `RAG_INDEX outcome=cache_stale
   source=recompute`, and attempt to upload the new embeddings to GCS.
4. IF the cache download fails for any reason (auth, not_found,
   network), THEN THE Retriever SHALL emit
   `RAG_INDEX outcome=cache_miss source=recompute`, build the corpus
   fresh from the model, and SHALL NOT raise.
5. IF the cache upload after a fresh build fails for any reason, THEN
   THE Retriever SHALL log a single `GCS_SYNC op=upload outcome=<error>
   detail="rag_embeddings"` line and SHALL NOT raise; the in-memory
   corpus SHALL remain authoritative for the lifetime of the
   container.
6. WHERE the deployment environment is local development (no GCS
   credentials configured), THE Retriever SHALL skip the cache
   download and upload paths entirely and SHALL build the corpus fresh,
   emitting `RAG_INDEX outcome=cache_miss source=recompute`.
7. THE cached `embeddings.npz` file SHALL contain the fields `vectors`
   (`float32` array of shape `(N, embedding_dim)`),
   `corpus_content_hash` (string), `model_name` (string),
   `embedding_dim` (int), and `built_at` (ISO 8601 string), so that
   future inspection and forensics can detect mismatches without
   re-reading the source corpus.

### Requirement 8: Operational SLOs and safe coexistence

**User Story:** As an operations engineer, I want documented retrieval
SLOs and a guarantee that this feature does not regress existing tests
or routing behavior, so that I can roll it out and roll it back with
confidence.

#### Acceptance Criteria

1. THE feature SHALL satisfy a retrieval-latency objective of p99 below
   100 milliseconds and p99.9 below 250 milliseconds, measured per
   container over rolling 24-hour windows on the `RAG_RETRIEVE
   duration_ms` field.
2. THE feature SHALL satisfy a retrieval-success-rate objective of at
   least 99.9 percent of `RAG_RETRIEVE` log lines having
   `outcome=ok`, measured per container over rolling 24-hour windows;
   `outcome=short_brief` SHALL count as success.
3. THE Bucket router SHALL remain the sole authority for OpenProject
   project selection; the Retriever SHALL NOT alter, override, or
   short-circuit any bucket-routing decision.
4. IF the preflight verification step (`scripts/preflight.sh` /
   `.bat`) detects that any module other than `bucket_router.py`
   exposes a function whose return value is consumed as a `project_id`
   by `openproject_client.create_work_package`, THEN THE preflight
   SHALL exit with a non-zero status, emit a `ROUTING_AUTHORITY_CONFLICT`
   error line naming the offending module, and the deploy gate SHALL
   refuse to proceed.
5. THE feature SHALL preserve the pass status of the existing 190 unit
   tests under `tests/unit` and the existing 9 synthetic webhook
   scenarios in `scripts/synthetic_webhook.py --scenario all`.
6. THE feature SHALL be controllable at runtime by the `RAG_ENABLED`
   environment variable; setting `RAG_ENABLED=false` and redeploying
   SHALL restore the pre-feature behavior (static 50-example block
   in every prompt) without a code change.
7. THE feature SHALL grow the container image size by no more than
   approximately 80 MB (sentence-transformers package + model weights
   + numpy if not already present), and SHALL NOT increase the
   declared Cloud Run memory requirement above the existing 1 GiB.
8. WHERE a rollback to revision `qa-bugbot-00042-8zj` is executed via
   `gcloud run services update-traffic`, THE Bot SHALL resume
   pre-feature behavior with no manual cleanup of the GCS embedding
   cache required.

### Requirement 9: HARD DEPLOY GATE — local-only until full sign-off

**User Story:** As the system owner, I want every implementation,
verification, and integration step of this feature to happen on a local
branch with zero touches to Cloud Run until I have personally reviewed
the full implementation and explicitly approved deployment, so that no
partial RAG state ever reaches production users.

#### Acceptance Criteria

1. WHILE any task in this spec's tasks.md remains unchecked, THE
   implementation team SHALL NOT execute `gcloud run deploy`,
   `gcloud builds submit`, or `gcloud run services update-traffic`
   against the `qa-bugbot` service in any region.
2. WHILE any task in this spec's tasks.md remains unchecked, THE
   implementation team SHALL NOT push the feature branch to a
   protected branch (`main`, any branch matching `release/*`), and
   SHALL NOT create or modify Cloud Run revisions of any kind.
3. WHEN the implementation team needs to verify behavior end-to-end
   before sign-off, THE verification SHALL run against a local
   `uvicorn` instance, the unit-test suite, the synthetic webhook
   harness, or a Docker-built local container — never against the
   live Cloud Run service.
4. WHEN every task in this spec's tasks.md is checked, THE
   implementation team SHALL post a deploy-readiness summary to the
   user matching the structure used at the production-reliability
   Phase 7 sign-off (test counts, latency measurements, log-line
   samples, image-size delta, fallback-path proof) AND SHALL stop and
   wait for the user to explicitly type "deploy" before any
   `gcloud run` command runs.
5. THE deploy-readiness summary SHALL include:
   (a) the full unit-test pass count,
   (b) the synthetic webhook scenario pass count,
   (c) measured Phase 1 LLM-call latency for the static-50 baseline
       and the retrieval-backed path on the same brief,
   (d) measured retrieval-only p99 latency over at least 50 calls,
   (e) the size in bytes of the generated `embeddings.npz`,
   (f) the container image size delta vs. the current production image,
   (g) a sample `RAG_INDEX` and `RAG_RETRIEVE` log line from a local run,
   (h) at least one demonstration of each fallback path
       (`embed_error`, `empty_corpus`, `index_unavailable`,
       `RAG_ENABLED=false`),
   (i) the rollback command and the matching `qa-bugbot-00042-8zj`
       revision name as the recovery target.
6. IF the user replies with anything other than the literal word
   "deploy" to the readiness summary, THEN THE implementation team
   SHALL treat the response as "not approved" and SHALL continue
   working locally; only the literal token "deploy" unlocks the
   deploy phase.
7. WHERE the implementation team executes any task that itself
   describes a `gcloud run` operation (e.g., a future "smoke test
   against staging" task), THE task SHALL be split such that all
   `gcloud run` invocations are gated behind the user-approval task
   and never run automatically.
8. THE feature SHALL retain the existing `checkpoint-stable-20260530`
   tag as the rollback target; deploy phase tasks SHALL NOT amend,
   force-push, or delete that tag. Any new git tag added during the
   RAG deploy SHALL be additive only.
