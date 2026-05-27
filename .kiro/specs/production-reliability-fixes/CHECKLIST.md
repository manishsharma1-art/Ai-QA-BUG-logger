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
| 2 | Component fixes (A-G) | 35 | 35 | ✅ Done |
| 3 | Integration glue | 3 | 3 | ✅ Done |
| 4 | Synthetic webhook scenarios | 11 | 11 | ✅ Done (9/9 green) |
| 5 | Secret hygiene | 5 | 5 | ✅ Done |
| 6 | Local end-to-end verification | 6 | 2 | 🟡 13.1 + 13.2 green; 13.3-13.6 need Docker |
| **7** | **HARD GATE — user sign-off** | **1** | **0** | **🛑 STOP HERE** |
| 8 | Deploy | 4 | 0 | ⬜ DEPLOY-ONLY |
| 9 | Post-deploy verify | 4 | 0 | ⬜ DEPLOY-ONLY |
| 10 | Rollback (only on failure) | 2 | 0 | ⬜ Failure path |
| **TOTAL** | | **102** | **74** | **72.5%** |

> Note: 19 of the 28 "remaining" leaves are deploy-only (Phases 8–10) and are intentionally gated behind Phase 7. The genuinely-open *local* work is 4 leaves: 13.3, 13.4, 13.5, 13.6 — all of which require a working Docker daemon. Docker is not installed on this dev machine, so those four are blocked on the operator running them where Docker is available (or skipping straight to the cloud build in Phase 8 which is itself a `--no-cache` build).

---

## ✅ Phase 0 — Repo hygiene

- [x] **1.1** Branch `fix/production-reliability` created from `main`
- [x] **1.2** `.gitignore` / `.dockerignore` / `.gcloudignore` `.env*` exclusion verified
- [x] **1.3** Tag `pre-reliability-fix-20260527` on commit `6cbb855` (rollback anchor)

---

## ✅ Phase 1 — Test infrastructure

- [x] **2.1** `tests/__init__.py` + `tests/unit/__init__.py` + `tests/unit/conftest.py`
- [x] **2.2** `requirements-dev.txt` (`hypothesis`, `pytest`, `pytest-asyncio`)
- [x] **2.3** `scripts/preflight.sh` (POSIX, 7 steps)
- [x] **2.4** `scripts/preflight.bat` (Windows cmd mirror)
- [x] **2.5** `scripts/synthetic_webhook.py` skeleton with `--scenario` CLI

---

## ✅ Phase 2 — Component fixes (all done in source)

### Component A — Bucket router (`bucket_router.py`)
- [x] **3.1** `BUCKET_TAG_RE` anchored regex
- [x] **3.2** Brief preserved verbatim (no `[Tag]` stripping)
- [x] **3.3** `_resolve_tag` tightened (cutoff 0.78, alias len ≥ 3)
- [x] **3.4** `CROSS_KEYWORD_SINGLE_WORDS` constant
- [x] **3.5** `_extract_bucket_from_freetext(text)` helper
- [x] **3.6** 3-layer flow in `extract_bucket_from_message`
- [x] **3.7** T-BR-1..T-BR-20 unit tests in `test_bucket_router.py`
- [x] **3.8\*** Hypothesis typo-tolerance test in `test_bucket_router_property.py`

### Component B — Priority validator (`models.py`)
- [x] **4.1** `_HIGH_PRIORITY_RE` and `_LOW_PRIORITY_RE` word-boundary regexes
- [x] **4.2** `validate_priority` rewritten with fast-path + `PRIORITY_AMBIGUOUS` log
- [x] **4.3** `ExtractedBugReport` docstring documents fail-fast vs fallback fields
- [x] **4.4\*** 17-row word-boundary table test
- [x] **4.5\*** `PRIORITY_AMBIGUOUS` `caplog` assertion test
- [x] **4.6\*** Hypothesis property test

### Component C — GCS sync observability (`database.py`)
- [x] **5.1** `GcsSyncStatus` Pydantic model with 8-outcome Literal
- [x] **5.2** `_last_gcs_sync` + `get_last_gcs_sync()` accessor
- [x] **5.3** `_download_db_from_gcs()` typed exception ladder + `GCS_SYNC` log
- [x] **5.4** `_upload_db_to_gcs()` ladder (no silent `pass` on `ImportError`)
- [x] **5.5** Upload calls preserved in `create_or_update_user` and `close_database`
- [x] **5.6\*** Per-outcome download tests
- [x] **5.7\*** Per-outcome upload tests

### Component D — Phase 2 LLM correctness (`gemini_client.py`)
- [x] **6.1** `PHASE2_PROMPT_TEMPLATE` with 11 mandatory fields
- [x] **6.2** `Phase2TruncatedError` + `JsonCleanResult`
- [x] **6.3** `_clean_json_response` raises on truncation (no silent repair)
- [x] **6.4** `DEFAULT_STUFFING_MARKERS` + `_detect_default_stuffing` (pure)
- [x] **6.5** `enrich_with_media`: `max_tokens=6000`, 45/50 s timeouts
- [x] **6.6** Three fall-back paths to Phase 1 (truncation / timeout / default-stuffing) — no retries
- [x] **6.7\*** `test_clean_json_response_*` tests
- [x] **6.8\*** `test_detect_default_stuffing_all_paths` (2-of-4)
- [x] **6.9\*** Three fall-back tests in `test_enrich_with_media_fallbacks.py`
- [x] **6.10\*** Property test for token budget invariance

### Component E — Env validator + BUILD_MARKER
- [x] **7.1** `validate_env_vars(settings)` with 5 checks (`env_validator.py`)
- [x] **7.2** `read_build_marker()` helper
- [x] **7.3** `Dockerfile` `ARG BUILD_MARKER` + `RUN echo > /app/BUILD_MARKER`
- [x] **7.4** `main.py lifespan()` calls validator + emits `BUILD_MARKER` log
- [x] **7.5\*** `test_env_validator.py`

### Component F — `/health` endpoint
- [x] **8.1** `HealthResponse` extended with `last_gcs_sync` + `build_marker`
- [x] **8.2** `/health` populates new fields + applies `degraded` rule
- [x] **8.3\*** `test_health_endpoint.py`

### Component G — `OP_CALL` log wrapper
- [x] **9.1** `_log_op_call` wrapper in `openproject_client.py` (5 outcomes)
- [x] **9.2\*** `test_op_call_logger.py` (5 outcomes)

---

## ✅ Phase 3 — Integration glue

- [x] **10.1** Bucket router output flows into `_handle_bug_report` (LLM gets original brief)
- [x] **10.2** Phase 2 fall-back paths each produce exactly one ticket
- [x] **10.3** `validate_env_vars` + `BUILD_MARKER` emitted before `init_database`

---

## ✅ Phase 4 — Synthetic webhook scenarios (9/9 green)

- [x] **11.1** Common harness (mocks for OP, Gemini, GCS)
- [x] **11.2** S1 — empty brief + photo (rejection)
- [x] **11.3** S2 — `[LMS Webview] flickering` → project 476
- [x] **11.4** S3 — `Login fails [step 3]` (negative test)
- [x] **11.5** S4 — 20-frame video bug
- [x] **11.6** S5 — default-stuffed Phase 2 fall-back
- [x] **11.7** S6 — registration GCS round-trip
- [x] **11.8** S7 — RC2 env-var corruption
- [x] **11.9** S8 — truncated Phase 2 fall-back
- [x] **11.10** S9 — Phase 2 timeout fall-back
- [x] **11.11** `--scenario all` aggregation

---

## ✅ Phase 5 — Secret hygiene

- [x] **12.1** `.env.example` placeholders (no real `sk-…` tokens)
- [x] **12.2** Pre-commit hook at `scripts/hooks/pre-commit`
- [x] **12.3** Hook installation script `scripts/install-hooks.sh`
- [x] **12.4** `.gitignore` / `.dockerignore` / `.gcloudignore` exclusion contract
- [x] **12.5\*** Pre-commit hook tests (real key rejected, placeholder allowed)

---

## 🟡 Phase 6 — Local end-to-end verification

- [x] **13.1** `python -m pytest -q` green — **112 passed, 0 failed**
- [x] **13.2** `python scripts/synthetic_webhook.py --scenario all` green — **9/9 passed**
- [ ] **13.3** `docker build --no-cache --build-arg BUILD_MARKER=local-<sha> .` — *blocked: Docker not installed*
- [ ] **13.4** `docker run` + `/health` shape verification — *blocked: Docker not installed*
- [ ] **13.5** Grep startup logs for `BUILD_MARKER`, `ENV_VALIDATION`, `GCS_SYNC` — *blocked: depends on 13.4*
- [ ] **13.6** `scripts/preflight.sh` / `.bat` end-to-end — *blocked: depends on 13.3-13.5*

> The four open Phase 6 leaves all need Docker. On this dev machine `docker --version` returns "command not found". Options to clear them:
> 1. Run on a machine with Docker Desktop / Docker Engine installed.
> 2. Skip straight to Phase 8 — `gcloud builds submit --no-cache` performs the equivalent build in Cloud Build, with the BUILD_MARKER substitution already wired (task 7.3 added the `ARG`).
>
> Either way, do **not** mark these `[x]` until they actually run green.

---

## 🛑 Phase 7 — HARD SIGN-OFF GATE

- [ ] **14.1** Present local-test summary to user. **STOP.**

> Until the user types "deploy", do not run `gcloud`, do not create `env.yaml`, do not `git push`.

**Local test summary as of this revision:**
> - Branch: `fix/production-reliability` @ `5228bf2` (clean tree, after the `space_name` fix)
> - `pytest tests/unit -q`: **112 passed, 0 failed**
> - `synthetic_webhook.py --scenario all`: **9/9 passed**
> - Bug fixed in main.py: `_handle_bug_report` no longer NameErrors on `space_name` for text-only bug reports
> - Docker-dependent steps (13.3-13.6) deferred to Cloud Build at deploy time

---

## ⬜ Phase 8 — Deploy (DEPLOY-ONLY)

Only after Phase 7 sign-off.

- [ ] **15.1** Create `env.yaml` from `.env`
- [ ] **15.2** Commit + tag + push (pre-commit hook will scan)
- [ ] **15.3** `gcloud builds submit --no-cache --substitutions=_BUILD_MARKER=<sha>`
- [ ] **15.4** `gcloud run deploy ... --env-vars-file env.yaml`

---

## ⬜ Phase 9 — Post-deploy verification (DEPLOY-ONLY)

- [ ] **16.1** `/health` shape (status, build_marker, last_gcs_sync, database)
- [ ] **16.2** Cloud Run logs grep for `BUILD_MARKER` / `ENV_VALIDATION` / `GCS_SYNC`
- [ ] **16.3** `Database initialized` ≥ 200 ms after `Starting up...`
- [ ] **16.4** Send `[LMS Webview] login button broken on iPhone 13` and assert ticket payload

---

## ⬜ Phase 10 — Rollback (failure path only)

- [ ] **17.1** `gcloud run services update-traffic ... --to-revisions qa-bugbot-00026-btk=100`
- [ ] **17.2** `postmortem.md`

---

## Tasks marked with `*` are optional test sub-tasks (all done)

---

## Critical reminders

- **Never** push to origin or run `gcloud` before Phase 7 user approval
- **Always** use `--env-vars-file env.yaml` (NEVER `--set-env-vars` with spaces)
- **Always** use `--no-cache` on `gcloud builds submit` to prevent stale-image regression
- **Trust source files over the task tracker**
