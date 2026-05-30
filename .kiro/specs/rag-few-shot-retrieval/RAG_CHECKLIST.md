# CHECKLIST — rag-few-shot-retrieval

> **Purpose:** Quick visual progress tracker.
>
> _Refreshed 2026-05-30 after Phase 9 + the `/health.rag` model wiring landed. Phases 0–9 are committed and pushed; Phase 10 (deploy gate) is the next leaf._
>
> Source of truth for granular status is `tasks.md`. This file is a human-readable mirror — update it when a phase fully closes.

---

## Phase summary

| Phase | What | Leaves | Done | Status |
|---|---|---|---|---|
| 0 | Branch + spec hygiene | 3 | 3 | ✅ Done |
| 1 | Test infrastructure | 5 | 5 | ✅ Done |
| 2 | `bug_retriever.py` core | 13 | 13 | ✅ Done |
| 3 | GCS cache + content hash | 9 | 9 | ✅ Done |
| 4 | Singleton + lifespan integration | 6 | 6 | ✅ Done |
| 5 | `gemini_client.py` integration | 10 | 10 | ✅ Done |
| 6 | `/health` extension | 4 | 4 | ✅ Done (model field + main.py wiring landed in this refresh) |
| 7 | Property tests + S10 synthetic webhook | 10 | 10 | ✅ Done |
| 8 | Dependencies + Dockerfile | 4 | 4 | ✅ Done |
| 9 | Local end-to-end verification | 7 | 7 | ✅ Done |
| 10 | 🚫 **HARD SIGN-OFF GATE** | 1 | 0 | 🚫 Next leaf — readiness summary + literal `deploy` |
| 11 | Deploy | 3 | 0 | 🔒 Locked behind Phase 10 + literal `deploy` |
| 12 | Post-deploy verify + handover refresh | 4 | 0 | 🔒 Locked behind Phase 10 + literal `deploy` |
| 13 | Rollback | 2 | n/a | ⬜ Only used if Phase 12 fails |
| **TOTAL leaves** | | **81** | **81** | **100% local; deploy gated** |

The orchestrator's task DB will report 81/95 done — that includes the 4 parent rows (Phase 0–9 parents 1–10 are flipped) and the 14 leaves spanning Phases 10–13.

---

## ✅ Phase 0 — Branch + spec hygiene  (commits `6648d56`, `c436051`)

- [x] **1.1** Create feature branch `feat/rag-few-shot-retrieval` from `fix/production-reliability` HEAD — HEAD `ab75c4a`
- [x] **1.2** Verify clean working tree and existing checkpoint tag — `checkpoint-stable-20260530` → `159677fa3` preserved
- [x] **1.3** Tag pre-feature baseline `pre-rag-few-shot-20260530` → `6648d56` (additive only)

## ✅ Phase 1 — Test infrastructure  (commit `e8361a6`)

- [x] **2.1** `tests/unit/test_bug_retriever.py` skeleton (replaced by 33 real tests in `b9ba47f`)
- [x] **2.2** `tests/unit/test_bug_retriever_properties.py` skeleton (5 hypothesis tests P1..P5)
- [x] **2.3** `tests/unit/test_gemini_client_rag.py` skeleton (U27..U31 placeholders → real tests)
- [x] **2.4** `tests/unit/test_models_health_rag.py` skeleton (U32, U33 placeholders → real tests)
- [x] **2.5** Shared retriever fixtures in `tests/unit/conftest.py` (`mock_sentence_transformer`, `tiny_corpus_rows`, `fake_gcs_storage_client`, `caplog_rag`)

## ✅ Phase 2 — `bug_retriever.py` core  (commit `2f66eb0`)

- [x] **3.1** `BugRetriever.__init__` and `BugRetriever.from_env`
- [x] **3.2** `_load_corpus_rows` (utf-8-sig, schema validation, project_id resolution)
- [x] **3.3** `_load_model` (lazy import, telemetry off)
- [x] **3.4** `_embed_rows_l2_normalized` (batch=32, normalize=True, dtype check)
- [x] **3.5** `_embed_query_l2_normalized` (single-string, no try/except — caller wraps)
- [x] **3.6** `BugRetriever.retrieve` — cosine + soft-boost + top-K (per design §3 Theme 2)
- [x] **3.7** `BugRetriever.index` orchestrator
- [x] **3.8** `is_ready`, `to_health_dict`, `last_outcome` accessors
- [x] **3.9** `_emit_index_log` and `_emit_retrieve_log` helpers
- [x] **3.10** Unit tests for retrieve happy path + project boost (U10, U11, U12, U17)
- [x] **3.11** Unit tests for retrieve fallback outcomes (U13, U14, U15, U16, U18)
- [x] **3.12** Unit tests for index outcomes without cache (U5, U6, U7, U8, U9)
- [x] **3.13** Unit tests for accessors (U32, U33, plus is_ready)

## ✅ Phase 3 — GCS cache + content hash  (commit `2f66eb0`)

- [x] **4.1** `_compute_corpus_hash` exactly per design §5.4 (canonical JSON spec)
- [x] **4.2** `_gcs_credentials_available` helper
- [x] **4.3** `_try_load_cache(expected_hash)` (never raises)
- [x] **4.4** `_try_upload_cache(matrix, content_hash)` (never raises)
- [x] **4.5** Wire cache paths into `index()` (`cache_hit` / `cache_stale` / `cache_miss`)
- [x] **4.6** Unit tests for `_compute_corpus_hash` byte-equivalence (U22, U23, U24, U25)
- [x] **4.7** Unit test for npz round-trip schema (U26)
- [x] **4.8** Unit tests for cache load outcomes (U1, U3, U4)
- [x] **4.9** Unit test for cache stale recompute + upload (U2)

## ✅ Phase 4 — Singleton + lifespan integration  (commit `2f66eb0`)

- [x] **5.1** `init_retriever()` and `get_retriever()` singleton (idempotent)
- [x] **5.2** Wire `init_retriever()` into `main.py:lifespan()` after smoke test
- [x] **5.3** Verify import failure of `bug_retriever` does not take down lifespan
- [x] **5.4** Add `RAG_ENABLED`, `RAG_TOPK`, `RAG_CACHE_GCS` to `.env.example`
- [x] **5.5** Unit test for `init_retriever` idempotency
- [x] **5.6** Unit test for lifespan resilience to import failure

## ✅ Phase 5 — `gemini_client.py` integration  (commit `bc36d17`)

- [x] **6.1** Rename `SYSTEM_PROMPT` → `SYSTEM_PROMPT_BASE` with backwards-compat alias
- [x] **6.2** `_render_examples_block(examples)` helper
- [x] **6.3** `_build_fewshot_block(*, query, project_id, phase)` helper (three-stage fallback)
- [x] **6.4** `analyze_text_brief` accepts `project_id` and uses `_build_fewshot_block`
- [x] **6.5** `enrich_with_media` accepts `project_id` and uses `_build_fewshot_block`
- [x] **6.6** Extend `_log_llm_call` extras with `rag_examples`, `rag_outcome`, `rag_source`
- [x] **6.7** Wire `target_project_id` through `main.py:_handle_bug_report` to both phases
- [x] **6.8** Unit test: `_render_examples_block` byte-equivalent to `_load_few_shot_block` for same inputs (U27)
- [x] **6.9** Unit test: `_build_fewshot_block` fallback chain (U28, U29, U30)
- [x] **6.10** Unit test: `LLM_CALL` extra fields populated (U31)

## ✅ Phase 6 — `/health` extension  (commits `bc36d17` lifespan, this refresh: model field + populate)

- [x] **7.1** Extend `HealthResponse` in `models.py` with `rag` field — landed in this refresh
- [x] **7.2** Populate `rag` in `main.py:health_check()` from `bug_retriever.get_retriever()` — landed in this refresh
- [x] **7.3** Integration test: `/health` includes `rag` sub-object after `init_retriever()` succeeds (U32)
- [x] **7.4** Integration test: `/health.rag.enabled=false` shape under `RAG_ENABLED=false` (U33)

## ✅ Phase 7 — Property tests + synthetic webhook S10  (commit `cad1b78`)

- [x] **8.1** Property test P1 — retrieval determinism (Property 1)
- [x] **8.2** Property test P2 — cosine + soft-boost bounds (Property 2)
- [x] **8.3** Property test P3 — K boundedness and ordering (Property 3)
- [x] **8.4** Property test P4 — query non-mutation (Property 4)
- [x] **8.5** Property test P5 — never-raise (Property 8)
- [x] **8.6** Unit test U20 — no socket / open / httpx calls inside `retrieve()` (Property 6)
- [x] **8.7** Unit test U19 — slow-call WARNING level (Req 5.2)
- [x] **8.8** Unit test U21 — query non-mutation (example-based companion to P4)
- [x] **8.9** Add scenario S10 to `scripts/synthetic_webhook.py`
- [x] **8.10** Wire S10 into `--scenario all` runner; 10/10 pass

## ✅ Phase 8 — Dependencies + Dockerfile  (commits `cb0db84`, `e28756f`)

- [x] **9.1** `sentence-transformers==2.7.0` and `numpy==1.26.4` in `requirements.txt`
- [x] **9.2** `pip install --dry-run -r requirements.txt` resolves cleanly
- [x] **9.3** Model pre-fetch step in `Dockerfile`
- [x] **9.4** Image-size delta budget verified (Req 8.7: ≤ 80 MB delta)

## ✅ Phase 9 — Local end-to-end verification  (commits `2000b96`, `b9ba47f`)

- [x] **10.1** `python -m pytest tests/unit -q` → 236 passed (1 pre-existing flake on `test_resolve_tag_typo_tolerance`, unrelated to RAG)
- [x] **10.2** `python scripts/synthetic_webhook.py --scenario all` → 10/10 passed
- [x] **10.3** Build local Docker image clean
- [x] **10.4** Run container locally and verify `/health` shape (now includes `rag` sub-object)
- [x] **10.5** Grep startup logs for `RAG_INDEX outcome=ok|cache_hit`
- [x] **10.6** A/B latency: RAG_ENABLED=true vs false on the same brief
- [x] **10.7** Each fallback path demonstrated locally (`embed_error`, `empty_corpus`, `index_unavailable`, `RAG_ENABLED=false`)

---

## 🚫 Phase 10 — HARD SIGN-OFF GATE  (next leaf)

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

- [ ] **12.1** Commit and tag the feature branch — `git tag rag-few-shot-deploy-<YYYYMMDD-HHMM>`
- [ ] **12.2** Build + deploy via `gcloud run deploy --source .` with new env vars (`RAG_ENABLED`, `RAG_TOPK`, `RAG_CACHE_GCS`)
- [ ] **12.3** Force traffic flip to the new revision

Deploy hard rules: comma-separated `--update-env-vars`, `--no-cpu-throttling`, `--memory 1Gi`, system gcloud only, `service-account.json` in source upload.

---

## 🔒 Phase 12 — Post-deploy verify + handover refresh

- [ ] **13.1** `/health.rag` populated against the live URL
- [ ] **13.2** `RAG_INDEX outcome=ok|cache_hit` present in `/logs`
- [ ] **13.3** Canary bug routes correctly with `rag_source=retrieved`
- [ ] **13.4** Tag the new stable revision (`checkpoint-stable-rag-<YYYYMMDD>`) and update `LLM_HANDOVER.md`

---

## ⬜ Phase 13 — Rollback (only if Phase 12 fails)

- [ ] **14.1** Roll back traffic to `qa-bugbot-00042-8zj`
- [ ] **14.2** Author `postmortem.md` documenting the regression

---

## Tag chain (rollback targets, newest → oldest)

```
pre-rag-few-shot-20260530       → 6648d56  ← pre-feature baseline
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
