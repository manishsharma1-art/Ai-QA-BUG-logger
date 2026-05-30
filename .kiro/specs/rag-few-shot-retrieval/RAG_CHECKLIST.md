# CHECKLIST — rag-few-shot-retrieval

> **Purpose:** Quick visual progress tracker.
>
> _Created 2026-05-30. Phase 0 done; everything else pending._
>
> Source of truth for granular status is `tasks.md`. This file is a human-readable mirror — update it when a phase fully closes.

---

## Phase summary

| Phase | What | Tasks | Done | Status |
|---|---|---|---|---|
| 0 | Branch + spec hygiene | 3 | 3 | ✅ Done |
| 1 | Test infrastructure | 5 | 0 | ⬜ Not started |
| 2 | `bug_retriever.py` core | 13 | 0 | ⬜ Not started |
| 3 | GCS cache + content hash | 9 | 0 | ⬜ Not started |
| 4 | Singleton + lifespan integration | 6 | 0 | ⬜ Not started |
| 5 | `gemini_client.py` integration | 10 | 0 | ⬜ Not started |
| 6 | `/health` extension | 4 | 0 | ⬜ Not started |
| 7 | Property tests + S10 synthetic webhook | 10 | 0 | ⬜ Not started |
| 8 | Dependencies + Dockerfile | 4 | 0 | ⬜ Not started |
| 9 | Local end-to-end verification | 7 | 0 | ⬜ Not started |
| 10 | 🚫 **HARD SIGN-OFF GATE** | 1 | 0 | 🚫 Locked until everything above is green |
| 11 | Deploy | 3 | 0 | 🔒 Locked behind Phase 10 + literal `deploy` |
| 12 | Post-deploy verify + handover refresh | 4 | 0 | 🔒 Locked behind Phase 10 + literal `deploy` |
| 13 | Rollback | 2 | n/a | ⬜ Only used if Phase 12 fails |
| **TOTAL leaves** | | **81** | **3** | **4%** |

---

## ✅ Phase 0 — Branch + spec hygiene

- [x] **1.1** Create feature branch `feat/rag-few-shot-retrieval` from `fix/production-reliability` HEAD — HEAD `ab75c4a`
- [x] **1.2** Verify clean working tree and existing checkpoint tag — spec committed (`6648d56`); `checkpoint-stable-20260530` → `159677fa3` preserved
- [x] **1.3** Tag pre-feature baseline `pre-rag-few-shot-20260530` → `6648d56` (additive only)

---

## ⬜ Phase 1 — Test infrastructure

These 5 tasks create independent test skeletons and a shared conftest. Parallel safe.

- [ ] **2.1** Create `tests/unit/test_bug_retriever.py` skeleton (33 placeholder tests U1..U33)
- [ ] **2.2** Create `tests/unit/test_bug_retriever_properties.py` skeleton (5 hypothesis tests P1..P5)
- [ ] **2.3** Create `tests/unit/test_gemini_client_rag.py` skeleton (U27..U31 placeholders)
- [ ] **2.4** Create `tests/unit/test_models_health_rag.py` skeleton (U32, U33 placeholders)
- [ ] **2.5** Add shared retriever fixtures to `tests/unit/conftest.py` (`mock_sentence_transformer`, `tiny_corpus_rows`, `fake_gcs_storage_client`, `caplog_rag`)

---

## ⬜ Phase 2 — `bug_retriever.py` core

The new module's main class and its first batch of unit tests. 13 leaves; tests are marked `*` (optional in the DAG sense — code first, then tests).

- [ ] **3.1** `BugRetriever.__init__` and `BugRetriever.from_env`
- [ ] **3.2** `_load_corpus_rows` (utf-8-sig, schema validation, project_id resolution)
- [ ] **3.3** `_load_model` (lazy import, telemetry off)
- [ ] **3.4** `_embed_rows_l2_normalized` (batch=32, normalize=True, dtype check)
- [ ] **3.5** `_embed_query_l2_normalized` (single-string, no try/except — caller wraps)
- [ ] **3.6** `BugRetriever.retrieve` — cosine + soft-boost + top-K (per design §3 Theme 2)
- [ ] **3.7** `BugRetriever.index` orchestrator with cache stubs
- [ ] **3.8** `is_ready`, `to_health_dict`, `last_outcome` accessors
- [ ] **3.9** `_emit_index_log` and `_emit_retrieve_log` helpers
- [ ]* **3.10** Unit tests for retrieve happy path + project boost (U10, U11, U12, U17)
- [ ]* **3.11** Unit tests for retrieve fallback outcomes (U13, U14, U15, U16, U18)
- [ ]* **3.12** Unit tests for index outcomes without cache (U5, U6, U7, U8, U9)
- [ ]* **3.13** Unit tests for accessors (U32, U33, plus is_ready)

---

## ⬜ Phase 3 — GCS cache + content hash

- [ ] **4.1** `_compute_corpus_hash` exactly per design §5.4 (canonical JSON spec)
- [ ] **4.2** `_gcs_credentials_available` helper (catches all)
- [ ] **4.3** `_try_load_cache(expected_hash)` (never raises; returns None on any failure)
- [ ] **4.4** `_try_upload_cache(matrix, content_hash)` (never raises; logs `GCS_SYNC` on failure)
- [ ] **4.5** Wire cache paths into `index()` (`cache_hit` / `cache_stale` / `cache_miss`)
- [ ]* **4.6** Unit tests for `_compute_corpus_hash` byte-equivalence (U22, U23, U24, U25)
- [ ]* **4.7** Unit test for npz round-trip schema (U26)
- [ ]* **4.8** Unit tests for cache load outcomes (U1, U3, U4)
- [ ]* **4.9** Unit test for cache stale recompute + upload (U2)

---

## ⬜ Phase 4 — Singleton + lifespan integration

- [ ] **5.1** `init_retriever()` and `get_retriever()` module-level singleton (idempotent)
- [ ] **5.2** Wire `init_retriever()` into `main.py:lifespan()` after smoke test
- [ ] **5.3** Verify import failure of `bug_retriever` does not take down lifespan
- [ ] **5.4** Add `RAG_ENABLED`, `RAG_TOPK`, `RAG_CACHE_GCS` to `.env.example`
- [ ]* **5.5** Unit test for `init_retriever` idempotency
- [ ]* **5.6** Unit test for lifespan resilience to import failure

---

## ⬜ Phase 5 — `gemini_client.py` integration

- [ ] **6.1** Rename `SYSTEM_PROMPT` → `SYSTEM_PROMPT_BASE` with backwards-compat alias
- [ ] **6.2** Implement `_render_examples_block(examples)` helper
- [ ] **6.3** Implement `_build_fewshot_block(*, query, project_id, phase)` helper (three-stage fallback)
- [ ] **6.4** Modify `analyze_text_brief` to accept `project_id` and use `_build_fewshot_block`
- [ ] **6.5** Modify `enrich_with_media` to accept `project_id` and use `_build_fewshot_block`
- [ ] **6.6** Extend `_log_llm_call` extras with `rag_examples`, `rag_outcome`, `rag_source`
- [ ] **6.7** Wire `target_project_id` through `main.py:_handle_bug_report` to both phases
- [ ]* **6.8** Unit test: `_render_examples_block` byte-equivalent to `_load_few_shot_block` for same inputs (U27, Property 7 backbone)
- [ ]* **6.9** Unit test: `_build_fewshot_block` fallback chain (U28, U29, U30)
- [ ]* **6.10** Unit test: `LLM_CALL` extra fields populated (U31)

---

## ⬜ Phase 6 — `/health` extension

- [ ] **7.1** Extend `HealthResponse` in `models.py` with `rag` field
- [ ] **7.2** Populate `rag` in `main.py:health_check()` from `bug_retriever.get_retriever()`
- [ ]* **7.3** Integration test: `/health` includes `rag` sub-object after `init_retriever()` succeeds
- [ ]* **7.4** Integration test: `/health.rag.enabled=false` when `RAG_ENABLED=false`

---

## ⬜ Phase 7 — Property tests + synthetic webhook S10

- [ ]* **8.1** Property test P1 — retrieval determinism (Property 1; validates Reqs 5.6, 8.3)
- [ ]* **8.2** Property test P2 — cosine + soft-boost bounds (Property 2; validates Reqs 3.2, 3.3, 3.6)
- [ ]* **8.3** Property test P3 — K boundedness and ordering (Property 3; validates Reqs 2.1, 2.4, 3.3)
- [ ]* **8.4** Property test P4 — query non-mutation (Property 4; validates Reqs 2.3, 8.3)
- [ ]* **8.5** Property test P5 — never-raise (Property 8; validates Req 4.4)
- [ ]* **8.6** Unit test U20 — no socket / open / httpx calls inside `retrieve()` (Property 6)
- [ ]* **8.7** Unit test U19 — slow-call WARNING level (Req 5.2)
- [ ]* **8.8** Unit test U21 — query non-mutation (example-based companion to P4)
- [ ] **8.9** Add scenario S10 to `scripts/synthetic_webhook.py`
- [ ] **8.10** Wire S10 into `--scenario all` runner; assert all 10 scenarios still pass

---

## ⬜ Phase 8 — Dependencies + Dockerfile

- [ ] **9.1** Add `sentence-transformers==2.7.0` and `numpy==1.26.4` to `requirements.txt`
- [ ] **9.2** `pip install --dry-run -r requirements.txt` resolves cleanly (open question §9 numpy compat)
- [ ] **9.3** Add model pre-fetch step to `Dockerfile` (avoids cold-start download)
- [ ] **9.4** Verify image-size delta budget after rebuild (Req 8.7: ≤ 80 MB delta)

---

## ⬜ Phase 9 — Local end-to-end verification

- [ ] **10.1** `python -m pytest tests/unit -q` green (existing 190 tests + new RAG tests)
- [ ] **10.2** `python scripts/synthetic_webhook.py --scenario all` green (10/10)
- [ ] **10.3** Build local Docker image clean
- [ ] **10.4** Run container locally and verify `/health` shape (`rag.enabled=true`, `corpus_size=606`)
- [ ] **10.5** Grep startup logs for `RAG_INDEX outcome=ok|cache_hit`
- [ ] **10.6** A/B latency: RAG_ENABLED=true vs false on the same brief — expect ≥1500 ms median reduction (Req 5.5)
- [ ] **10.7** Demonstrate each fallback path locally (`embed_error`, `empty_corpus`, `index_unavailable`, `RAG_ENABLED=false`)

---

## 🚫 Phase 10 — HARD SIGN-OFF GATE

- [ ] **11.1** Produce deploy-readiness summary per Req 9.5 and post in chat — **STOP**

The summary MUST include:
- (a) Full unit-test pass count
- (b) Synthetic webhook scenario pass count
- (c) Phase 1 LLM-call latency: static-50 baseline AND retrieval-backed on the same brief
- (d) Retrieval-only p99 latency over ≥ 50 calls
- (e) Size in bytes of generated `embeddings.npz`
- (f) Container image size delta vs. current production image
- (g) Sample `RAG_INDEX` and `RAG_RETRIEVE` log lines from a local run
- (h) At least one demonstration of each fallback path
- (i) Rollback command + `qa-bugbot-00042-8zj` revision name as recovery target

After posting the summary, WAIT for the user. Per Req 9.6, **only the literal token `deploy`** unlocks Phase 11. Anything else means "not approved — keep working locally."

---

## 🔒 Phase 11 — Deploy (locked behind sign-off)

- [ ] **12.1** Commit and tag the feature branch
- [ ] **12.2** Build + deploy via `gcloud run deploy --source .` with new env vars (`RAG_ENABLED`, `RAG_TOPK`, `RAG_CACHE_GCS`)
- [ ] **12.3** Force traffic flip to the new revision

Deploy hard rules: comma-separated `--update-env-vars`, `--no-cpu-throttling`, `--memory 1Gi`, system gcloud only, `service-account.json` in source upload.

---

## 🔒 Phase 12 — Post-deploy verify + handover refresh

- [ ] **13.1** `/health.rag` populated against the live URL
- [ ] **13.2** `RAG_INDEX outcome=ok|cache_hit` present in `/logs`
- [ ] **13.3** Canary bug routes correctly with `rag_source=retrieved`
- [ ] **13.4** Tag the new stable revision and update `LLM_HANDOVER.md`

---

## ⬜ Phase 13 — Rollback (only if Phase 12 fails)

- [ ] **14.1** Roll back traffic to `qa-bugbot-00042-8zj`
- [ ] **14.2** Author `postmortem.md` documenting the regression

---

## Tag chain (rollback targets, newest → oldest)

```
pre-rag-few-shot-20260530       → 6648d56  ← pre-feature baseline (created in 1.3)
checkpoint-stable-20260530      → 159677f  ★ STABLE PRODUCTION (matches qa-bugbot-00042-8zj live)
reliability-fix-v3-20260530-1326 → 5002f50  (release tag for current production)
reliability-fix-v2-20260528-0829 → c09be99
reliability-fix-20260527        → 157110f
checkpoint-pre-deploy-20260527  → 5228bf2
pre-reliability-fix-20260527    → 6cbb855
```

The `checkpoint-stable-20260530` tag is the sole production rollback target. **Never amend, force-push, or delete it.** Any new tags during the RAG deploy are additive only.

---

## Critical reminders

- Pre-commit hook installed at `.git/hooks/pre-commit` — scans staged `.env*` files for `(sk|pk|api|key|token)[-_][A-Za-z0-9]{16,}` and rejects matches. Allow-list: `REPLACE_WITH_*`. **Test files with literal-looking tokens must construct strings at runtime.**
- Always use `--no-cpu-throttling` on Cloud Run (Phase 2 background tasks die without it).
- Always use `--memory 1Gi` (model + OpenCV need the headroom).
- Always use **comma-separated** values with `--update-env-vars` (RC2 prevention).
- Trust source files over markdown — this checklist is best-effort, the source is canonical.
- The orchestrator's task tools (`taskList`, `taskUpdate`, etc.) are the authoritative status source. Mirror updates here at phase boundaries.
