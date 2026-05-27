# CHECKLIST — production-reliability-fixes

> **Purpose:** Quick visual progress tracker. Tick a box only when the task is **actually done in source code**, not just marked in the task tracker.
>
> Companion docs:
> - `HANDOVER.md` — full context, what's done, how to resume
> - `design.md` — technical contract
> - `requirements.md` — EARS acceptance criteria
> - `tasks.md` — execution plan with sub-tasks and dependencies

---

## Phase summary

| Phase | What | Tasks | Done | Status |
|---|---|---|---|---|
| 0 | Repo hygiene | 3 | 3 | ✅ Done |
| 1 | Test infra | 5 | 5 | ✅ Done |
| 2 | Component fixes (A-G) | 35 | 0 | 🟡 **DO THIS NEXT** |
| 3 | Integration glue | 3 | 0 | ⬜ Blocked by Phase 2 |
| 4 | Synthetic webhook scenarios | 11 | 0 | ⬜ Blocked by Phase 2 + 3 |
| 5 | Secret hygiene | 5 | 0 | ⬜ Can start any time |
| 6 | Local end-to-end verification | 6 | 0 | ⬜ Blocked by Phase 2-5 |
| **7** | **HARD GATE — user sign-off** | **1** | **0** | **🛑 STOP HERE** |
| 8 | Deploy | 4 | 0 | ⬜ DEPLOY-ONLY |
| 9 | Post-deploy verify | 4 | 0 | ⬜ DEPLOY-ONLY |
| 10 | Rollback (only on failure) | 2 | 0 | ⬜ Failure path |
| **TOTAL** | | **102** | **10** | **9.8%** |

---

## ✅ Phase 0 — Repo hygiene

- [x] **1.1** Branch `fix/production-reliability` created from `main` with checkpoint commit `4e06893`
- [x] **1.2** `.gitignore` / `.dockerignore` / `.gcloudignore` `.env*` exclusion verified
- [x] **1.3** Tag `pre-reliability-fix-20260527` on commit `6cbb855` (rollback anchor)

---

## ✅ Phase 1 — Test infrastructure

- [x] **2.1** `tests/__init__.py` + `tests/unit/__init__.py` + `tests/unit/conftest.py` with `log_capture` fixture
- [x] **2.2** `requirements-dev.txt` (`hypothesis==6.108.5`, `pytest==8.3.3`, `pytest-asyncio==0.24.0`)
- [x] **2.3** `scripts/preflight.sh` skeleton (POSIX, 7 steps)
- [x] **2.4** `scripts/preflight.bat` skeleton (Windows cmd mirror)
- [x] **2.5** `scripts/synthetic_webhook.py` skeleton with `--scenario {S1..S9, all}` CLI

---

## 🟡 Phase 2 — Component fixes (DO THIS NEXT)

All 7 components touch different files — safe to work in parallel. Recommended order: A → B → C → D → E → F → G.

### Component A — Bucket router (`bucket_router.py`)
Maps to: design Theme 4, requirements §1, design §4.5/4.6/4.7

- [ ] **3.1** Replace `re.search(r'\[([^\]]+)\]', text)` with anchored `BUCKET_TAG_RE = re.compile(r'^\s*\[([A-Za-z][A-Za-z0-9 &/\-]{1,40})\]\s*')`
- [ ] **3.2** Stop stripping `[Tag]` — return original text verbatim as `text_for_llm`
- [ ] **3.3** Tighten `_resolve_tag` (drop inverse substring, fuzzy 0.6 → 0.78, len ≥ 3 alias, len < 2 tag guard)
- [ ] **3.4** Add `CROSS_KEYWORD_SINGLE_WORDS` constant
- [ ] **3.5** Implement `_extract_bucket_from_freetext(text)` (purely Python, no LLM)
- [ ] **3.6** Update `extract_bucket_from_message` to 3-layer flow ([Tag] → free-text → device)
- [ ] **3.7** Tests T-BR-1..T-BR-20 in `tests/unit/test_bucket_router.py`
- [ ] **3.8*** Hypothesis test for typo tolerance in `tests/unit/test_bucket_router_property.py`

### Component B — Priority validator (`models.py`)
Maps to: design Theme 5, requirements §4

- [ ] **4.1** Add `_HIGH_PRIORITY_RE` and `_LOW_PRIORITY_RE` word-boundary regexes
- [ ] **4.2** Rewrite `validate_priority` with fast-path + tie-breaker + `PRIORITY_AMBIGUOUS` log
- [ ] **4.3** Document fail-fast vs fallback fields in `ExtractedBugReport` docstring
- [ ] **4.4*** `test_priority_validator_word_boundary` parametrized over §5.1 behaviour table
- [ ] **4.5*** `test_priority_validator_ambiguous_logs_warning` with `caplog`
- [ ] **4.6*** Hypothesis test for Property 4

### Component C — GCS sync observability (`database.py`)
Maps to: design Theme 2, requirements §2 + §8

- [ ] **5.1** Define `GcsSyncStatus` Pydantic model with 8-outcome Literal
- [ ] **5.2** Add module-level `_last_gcs_sync` + `get_last_gcs_sync()` accessor
- [ ] **5.3** Refactor `_download_db_from_gcs()` with typed exception ladder + `GCS_SYNC` log line
- [ ] **5.4** Refactor `_upload_db_to_gcs()` (CRITICAL: do not silently `pass` on `ImportError`)
- [ ] **5.5** Verify upload calls in `create_or_update_user` and `close_database` preserved
- [ ] **5.6*** `test_download_db_each_outcome` parametrized over 8 outcomes
- [ ] **5.7*** `test_upload_db_each_outcome` parametrized over 8 outcomes

### Component D — Phase 2 LLM correctness (`gemini_client.py`)
Maps to: design Theme 3, requirements §3

- [ ] **6.1** Define `PHASE2_PROMPT_TEMPLATE` constant with all 11 mandatory fields
- [ ] **6.2** Define `Phase2TruncatedError` exception + `JsonCleanResult` NamedTuple
- [ ] **6.3** Rewrite `_clean_json_response` to RAISE on truncation (no silent repair)
- [ ] **6.4** Define `DEFAULT_STUFFING_MARKERS` + implement `_detect_default_stuffing` (pure)
- [ ] **6.5** Update `enrich_with_media`: `max_tokens=6000`, `client_timeout=45s`, `wait_for(50s)`
- [ ] **6.6** Wire 3 fall-back paths: `Phase2TruncatedError` / `asyncio.TimeoutError` / default-stuffing → return `initial_report`. NO RETRIES.
- [ ] **6.7*** `test_clean_json_response_*` tests
- [ ] **6.8*** `test_detect_default_stuffing_all_paths` (2-of-4 threshold)
- [ ] **6.9*** `test_enrich_with_media_falls_back_to_phase1_*` (truncation, default-stuffing, timeout)
- [ ] **6.10*** Hypothesis test for Property 6 (token budget invariance)

### Component E — Env validator + BUILD_MARKER (NEW: `env_validator.py`, `Dockerfile`, `main.py`)
Maps to: design Theme 1.2, requirements §5

- [ ] **7.1** Implement `validate_env_vars(settings) -> list[str]` with 5 checks
- [ ] **7.2** Implement `read_build_marker()` helper
- [ ] **7.3** Update `Dockerfile` with `ARG BUILD_MARKER` + `RUN echo > /app/BUILD_MARKER`
- [ ] **7.4** Wire validator + `BUILD_MARKER` log into `main.py` `lifespan()`
- [ ] **7.5*** `test_validate_env_vars_*` tests

### Component F — /health endpoint (`models.py`, `main.py`)
Maps to: design Theme 2.3, requirements §5 + §2

- [ ] **8.1** Extend `HealthResponse` with `last_gcs_sync` + `build_marker` fields
- [ ] **8.2** Update `/health` handler to populate fields + apply `degraded` rule
- [ ] **8.3*** `test_health_endpoint_reports_gcs_status_and_build_marker`

### Component G — OP_CALL log wrapper (`openproject_client.py`)
Maps to: requirements §8 OpenProject portion

- [ ] **9.1** Wrap each HTTP call with `OP_CALL outcome=… duration_ms=…` log (5 outcomes)
- [ ] **9.2*** `test_op_call_log_outcomes` parametrized over 5 outcomes via `httpx.MockTransport`

---

## ⬜ Phase 3 — Integration glue (`main.py`)

Depends on Phase 2 components A, D, E being done.

- [ ] **10.1** Wire bucket router output through `_handle_bug_report` so LLM gets original brief
- [ ] **10.2** Verify Phase 2 fall-back paths each produce exactly one OpenProject ticket
- [ ] **10.3** Confirm env-validator + `BUILD_MARKER` emitted before any other startup line

---

## ⬜ Phase 4 — Synthetic webhook scenarios (`scripts/synthetic_webhook.py`)

Depends on Phase 3 done. Each scenario is independent.

- [ ] **11.1** Build common test harness (mocks for `OpenProjectClient.create_ticket`, `GeminiClient.client.chat.completions.create`, `google.cloud.storage.Client`)
- [ ] **11.2** S1 — empty brief + photo
- [ ] **11.3** S2 — `[LMS Webview] flickering` brief
- [ ] **11.4** S3 — `Login fails [step 3]` brief (negative test)
- [ ] **11.5** S4 — 20-frame video bug
- [ ] **11.6** S5 — photo-only with default-stuffed Phase 2 response
- [ ] **11.7** S6 — registration survives mocked GCS round-trip
- [ ] **11.8** S7 — RC2 env-var corruption reproduction
- [ ] **11.9** S8 — truncated Phase 2 → fall-back
- [ ] **11.10** S9 — Phase 2 timeout → fall-back
- [ ] **11.11** Wire `--scenario all` aggregation with non-zero exit on any failure

---

## ⬜ Phase 5 — Secret hygiene

Can start any time after Phase 1.

- [ ] **12.1** Replace `.env.example` real values with placeholders
- [ ] **12.2** Add pre-commit hook at `.git/hooks/pre-commit` AND committed copy at `scripts/hooks/pre-commit`
- [ ] **12.3** Document hook installation in `README.md` or `scripts/install-hooks.sh`
- [ ] **12.4** Re-verify `.gitignore` / `.dockerignore` / `.gcloudignore` exclusion contract
- [ ] **12.5*** Test pre-commit hook (fake key rejected, placeholder allowed)

---

## ⬜ Phase 6 — Local end-to-end verification

Depends on Phase 2 + 3 + 4 + 5 done.

- [ ] **13.1** `python -m pytest -q` green (all unit tests pass)
- [ ] **13.2** `python scripts/synthetic_webhook.py --scenario all` green (all S1–S9 pass)
- [ ] **13.3** `docker build --no-cache --build-arg BUILD_MARKER=local-<sha> .` clean
- [ ] **13.4** `docker run` → `/health` returns `status=healthy` + `build_marker` non-null + `last_gcs_sync` populated
- [ ] **13.5** Grep startup logs for `BUILD_MARKER`, `ENV_VALIDATION`, `GCS_SYNC` markers
- [ ] **13.6** `scripts/preflight.sh` (or `.bat`) green end-to-end

---

## 🛑 Phase 7 — HARD SIGN-OFF GATE

- [ ] **14.1** Present local-test summary to user. **STOP.** Do not proceed without explicit "deploy" approval.

> **Until the user types "deploy", do not run `gcloud`, do not create `env.yaml`, do not `git push`.**

---

## ⬜ Phase 8 — Deploy (DEPLOY-ONLY)

Only after Phase 7 sign-off.

- [ ] **15.1** Create `env.yaml` from `.env` (NOT committed; one YAML scalar per env var)
- [ ] **15.2** `git add -A && git commit && git tag reliability-fix-<YYYYMMDD> && git push`. Pre-commit hook (12.2) MUST pass.
- [ ] **15.3** `gcloud builds submit --no-cache --substitutions=_BUILD_MARKER=<sha> --tag <image> .`
- [ ] **15.4** `gcloud run deploy qa-bugbot --image <image> --region asia-south1 --env-vars-file env.yaml --service-account qaautomation@artful-affinity-634.iam.gserviceaccount.com`

---

## ⬜ Phase 9 — Post-deploy verification (DEPLOY-ONLY)

- [ ] **16.1** `curl /health` — `status=healthy`, `build_marker == <sha>`, `last_gcs_sync.outcome=ok`, `database=connected`
- [ ] **16.2** Grep Cloud Run logs for `BUILD_MARKER`, `ENV_VALIDATION`, `GCS_SYNC` lines
- [ ] **16.3** Confirm `Database initialized` log ≥ 200 ms after `Starting up...` (proves real GCS call)
- [ ] **16.4** Send one known-good bug to dev space; assert ticket payload (project 476, priority HIGH, real steps)

---

## ⬜ Phase 10 — Rollback (failure path only)

Only run if Phase 9 fails.

- [ ] **17.1** `gcloud run services update-traffic qa-bugbot --to-revisions qa-bugbot-00026-btk=100 --region asia-south1`
- [ ] **17.2** Document regression in `.kiro/specs/production-reliability-fixes/postmortem.md`

---

## Tasks marked with `*` are optional test sub-tasks

They can be skipped for a faster MVP, but the property-based tests (3.8, 4.6, 6.10) are highly recommended because they catch the most fragile invariants.

---

## How to update this checklist

After completing each leaf:

1. Verify the change actually landed in source (`grep_search` or `read_file`)
2. Run the relevant unit tests for that component
3. Tick the box `[x]`
4. Update the "Done" count in the Phase summary table at the top
5. Commit to the feature branch with a clear message

---

## Critical reminders

- **Never** push to origin or run `gcloud` before Phase 7 user approval
- **Always** use `--env-vars-file env.yaml` (NEVER `--set-env-vars` with spaces)
- **Always** use `--no-cache` on `gcloud builds submit` to prevent stale-image regression
- **Trust source files over the task tracker** — the tracker may have stale `in_progress` markers from earlier tooling glitches
