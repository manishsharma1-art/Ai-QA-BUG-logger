# HANDOVER — production-reliability-fixes

> **Read this entire file before doing anything.** It is the single source of truth for the current state of the work, what is done, what remains, and exactly how to continue without breaking anything.

This document is written for **another LLM or developer** taking over mid-flight. The user (Imart) has been working on this fix incrementally and stopped midway through Phase 2 (component fixes) due to a tooling hiccup. Nothing destructive happened — all in-progress work was on the task tracker only, not on source files.

---

## TL;DR — Where we are

| Item | Value |
|---|---|
| **Spec folder** | `.kiro/specs/production-reliability-fixes/` |
| **Current branch** | `fix/production-reliability` |
| **Current HEAD** | `4e06893` — `wip: pre-reliability-fix checkpoint (capturing uncommitted working tree)` |
| **Rollback tag** | `pre-reliability-fix-20260527` → commit `6cbb855` (the original `main` HEAD) |
| **Tasks completed** | **10 of 102** (Phases 0 + 1 only) |
| **Tasks remaining** | **92** |
| **Production revision** | `qa-bugbot-00039-dth` (Cloud Run, region `asia-south1`) — UNCHANGED, do not deploy yet |
| **Sign-off gate** | Phase 7 / task 14.1 — HARD STOP before any deploy |

---

## Project context (so you don't have to re-read everything)

- **Project**: `QA_BUG_Logger` — a FastAPI bot deployed on Google Cloud Run (`qa-bugbot`, asia-south1). Receives bug reports via Google Chat webhook, analyzes with Gemini 2.5 Flash via the IndiaMART LLM gateway (`https://imllm.intermesh.net/v1`), and creates tickets in OpenProject (`https://project.intermesh.net`).
- **Why this spec exists**: production was degraded across 8 confirmed root causes (RC1–RC8). See `design.md` §Architecture for the failure injection diagram.
- **Why design-first**: user explicitly chose "Start with Design" because the symptoms were well-understood and they wanted to lock in the technical approach before requirements.
- **Hard rule from user**: "lets do it locally first after everything done, we will deploy". **NO deploy** is allowed before the user explicitly types "deploy" at task 14.1.

### The 8 root causes (locked in design.md)

1. **RC1** — Stale image: deployed `database.py` doesn't have GCS sync code (proven by 112ms gap between "Starting up" and "Database initialized" in `/logs`)
2. **RC2** — Env-var corruption: `DEFAULT_OPENPROJECT_API_KEY` got `DEMO_SPACE_ID=...` concatenated into it via space-separator `--set-env-vars`
3. **RC3** — Silent GCS exceptions: every failure path collapses into one generic log line
4. **RC4** — Phase 2 truncation pipeline: weak prompt + `max_tokens=2000` + silent JSON repair + Pydantic defaults → "see attached video" tickets
5. **RC5** — Bucket router strips/over-matches: `[LMS Webview]` becomes `flickering`; `[step 3]` resolves to a wrong bucket
6. **RC6** — Priority substring match: `Medium-High`, `highlighted bug` both → HIGH
7. **RC7** — `.env.example` leaked the real `LLM_API_KEY=sk-KNy4qPAxAw0OEvgZuNyOeA` (company gateway key, not customer secret — no rotation needed, just placeholder fix)
8. **RC8** — No commit discipline: only 1 commit existed when this work started ("Initial commit for Hackathon submission")

### Locked-in user decisions (do not change without asking)

- **Priority HIGH whitelist**: `high`, `broken`, `completely failing`, `data loss`, `fatal`, `severe`, `crash`/`crashes`/`crashing`, `hang`/`hangs`/`hanging`, `stuck`/`stuck on`, `freezes`/`frozen`, `not responsive`/`unresponsive`/`not responding`, `blank screen`/`white screen`/`black screen`
- **Priority LOW whitelist**: `low`, `minor`, `cosmetic`, `trivial`, `nit`, `intermittent`/`intermittently`, `sometimes`, `occasionally`, `rarely`, `slight misalignment`, `slightly`
- **Tie-breaker** (HIGH ∧ LOW): return MEDIUM with `PRIORITY_AMBIGUOUS` audit log
- **Phase 2 max_tokens**: **6000** (3× safety multiplier, design Theme 3.2)
- **Phase 2 client timeout**: 45s; **asyncio.wait_for**: 50s; latency budget enforced (design Theme 3.2.1)
- **Truncation handling**: NEVER silently repair JSON. Raise `Phase2TruncatedError` and fall back to Phase 1 result. Same for default-stuffing and timeout. NO RETRIES.
- **Bucket routing**: 3 layers — explicit `[Tag]` at start (highest) → free-text bucket extraction (`bucket - X` shorthand + scoring) → device detection. **Brief is preserved verbatim** to LLM (no stripping).
- **No rotation needed**: `LLM_API_KEY` is a company-issued gateway token. Just replace with placeholder in `.env.example`.
- **No new runtime deps**: `requirements.txt` stays frozen. Dev deps go in `requirements-dev.txt` only.
- **No frame reduction**: 20 frames per video stays.
- **No model swap**: stays on `google/gemini-2.5-flash`.

---

## Phase status — full breakdown

The spec has 17 phases (top-level tasks) totaling 102 leaf tasks. Marked with ✅ done, 🟡 partial, ⬜ not started.

### ✅ Phase 0 — Repository hygiene (3/3 done)

- ✅ **1.1** Branch `fix/production-reliability` created from `main`. Checkpoint commit `4e06893` captures the previously-uncommitted working tree (17 files, 5308 insertions, 356 deletions including `bucket_router.py`, modified `database.py`/`gemini_client.py`/`main.py`/`models.py`/`openproject_client.py`/`config.py`, and the spec docs).
- ✅ **1.2** `.gitignore` / `.dockerignore` / `.gcloudignore` exclusion rules verified.
- ✅ **1.3** Tag `pre-reliability-fix-20260527` created on commit `6cbb855` (anchor for fast rollback).

### ✅ Phase 1 — Test infrastructure (5/5 done)

- ✅ **2.1** `tests/__init__.py`, `tests/unit/__init__.py`, `tests/unit/conftest.py` (with `log_capture` fixture)
- ✅ **2.2** `requirements-dev.txt` pinning `hypothesis==6.108.5`, `pytest==8.3.3`, `pytest-asyncio==0.24.0` (httpx intentionally NOT pinned here — runtime already pins 0.28.1)
- ✅ **2.3** `scripts/preflight.sh` skeleton (POSIX, 7 steps with placeholders)
- ✅ **2.4** `scripts/preflight.bat` skeleton (Windows cmd mirror)
- ✅ **2.5** `scripts/synthetic_webhook.py` skeleton with `argparse --scenario {S1..S9, all}` CLI and 9 `NotImplementedError` stubs

### 🟡 Phase 2 — Core component fixes (0/35 done — DO THIS NEXT)

This is where you pick up. **CRITICAL**: the task tracker may show some tasks as `in_progress` due to the tooling hiccup — those are NOT actually done. **Verify by reading the actual source files** (`bucket_router.py`, `models.py`, `database.py`, `gemini_client.py`) — they are still in their original (broken) state.

Six independent component fixes. Each maps to a Theme in `design.md` and a Requirement in `requirements.md`. They can be done in parallel because they touch different files.

#### Component A — Bucket router (Theme 4 → Requirement 1) — 8 tasks
- ⬜ **3.1** Add `BUCKET_TAG_RE = re.compile(r'^\s*\[([A-Za-z][A-Za-z0-9 &/\-]{1,40})\]\s*')` constant. Replace existing `re.search(r'\[([^\]]+)\]', text)` with `BUCKET_TAG_RE.match(text)`.
- ⬜ **3.2** Stop stripping `[Tag]` from text. Return original `text` byte-identically as `text_for_llm`. Remove the `text[:tag_match.start()] + text[tag_match.end():]` slice.
- ⬜ **3.3** Tighten `_resolve_tag`: drop the `tag_lower in alias` clause, raise fuzzy cutoff `0.6 → 0.78`, add `if len(tag_lower) < 2: return None`, require `len(alias) >= 3` for substring match.
- ⬜ **3.4** Add `CROSS_KEYWORD_SINGLE_WORDS = {"login", "home", "homepage", "search", "page", "screen", "app", "android", "ios", "user", "buyer", "seller"}` constant.
- ⬜ **3.5** Implement `_extract_bucket_from_freetext(text)` per design Theme 4.5 algorithm. Pure Python, no LLM call.
- ⬜ **3.6** Update `extract_bucket_from_message` to 3-layer flow: `BUCKET_TAG_RE.match` → `_extract_bucket_from_freetext` → `_detect_device_platform`.
- ⬜ **3.7** Write `tests/unit/test_bucket_router.py` with `test_extract_bucket_regex` parametrized over T-BR-1..T-BR-20 (cases listed in design §4.4 + §4.7 and requirements §1).
- ⬜* **3.8** Write `tests/unit/test_bucket_router_property.py` with hypothesis test `test_resolve_tag_typo_tolerance` for Property 3 (typos within Levenshtein 1-2 → same project id or None, never different).

#### Component B — Priority validator (Theme 5 → Requirement 4) — 6 tasks
- ⬜ **4.1** Replace substring priority validator with word-boundary regex in `models.py`. Add module-level `_HIGH_PRIORITY_RE` and `_LOW_PRIORITY_RE` (full keyword lists from design §5.1, compiled with `re.IGNORECASE`).
- ⬜ **4.2** Rewrite `validate_priority` field validator with: empty/non-string → MEDIUM; lowercased exact match `high|medium|low` → fast-path; HIGH and LOW both match → MEDIUM + `logger.warning("PRIORITY_AMBIGUOUS: both HIGH and LOW keywords matched in %r — defaulting to MEDIUM", v)`; only HIGH → HIGH; only LOW → LOW; neither → MEDIUM.
- ⬜ **4.3** Document fail-fast vs fallback fields in `ExtractedBugReport` docstring (per design Theme 5.2 table).
- ⬜* **4.4** Write `tests/unit/test_priority_validator.py` with `test_priority_validator_word_boundary` parametrized over Requirement 4.10 behaviour table (17 rows).
- ⬜* **4.5** Write `test_priority_validator_ambiguous_logs_warning` using `caplog`. Test cases: `"intermittent crash"`, `"screen freezes intermittently"`, `"sometimes crashes on payment"`.
- ⬜* **4.6** Write `tests/unit/test_priority_validator_property.py` hypothesis test for Property 4.

#### Component C — GCS sync observability (Theme 2 → Requirements 2+8) — 7 tasks
- ⬜ **5.1** Define `GcsSyncStatus` Pydantic model in `database.py` with fields: `op`, `started_at`, `finished_at`, `duration_ms`, `outcome` (8-value Literal: `ok|skipped|import_error|auth_error|forbidden|not_found|network_error|unknown_error`), `bytes`, `detail`. Validators: `duration_ms ≥ 0`, `bytes ≥ 0`, `bytes > 0` only when `outcome == "ok"`, `detail` ≤ 500 chars.
- ⬜ **5.2** Add module-level `_last_gcs_sync: Optional[GcsSyncStatus] = None` plus accessor `def get_last_gcs_sync() -> Optional[GcsSyncStatus]: return _last_gcs_sync`.
- ⬜ **5.3** Refactor `_download_db_from_gcs()` with typed exception ladder per design §2.1 pseudocode. 8 outcomes. Always set `_last_gcs_sync`. Always emit exactly one `GCS_SYNC op=download outcome=… duration_ms=… bytes=… detail="…"` log line. Never re-raise.
- ⬜ **5.4** Refactor `_upload_db_to_gcs()` with same exception ladder. CRITICAL: must NOT silently `pass` on `ImportError` (current code does — that's the RC3 bug).
- ⬜ **5.5** Verify upload calls in `create_or_update_user` and `close_database` are preserved (existing behaviour).
- ⬜* **5.6** Write `tests/unit/test_database_gcs_sync.py` `test_download_db_each_outcome` parametrized over all 8 outcomes via mocked exceptions.
- ⬜* **5.7** Write `test_upload_db_each_outcome` (same shape).

#### Component D — Phase 2 LLM correctness (Theme 3 → Requirement 3) — 10 tasks
- ⬜ **6.1** Define `PHASE2_PROMPT_TEMPLATE` constant in `gemini_client.py` per design Theme 3.1. All 11 fields mandatory, "Not specified" fallback, forbid placeholder string `"See attached media for reproduction steps"`. Use `{initial_json}` and `{original_brief}` substitution slots.
- ⬜ **6.2** Define `Phase2TruncatedError` exception class and `JsonCleanResult` NamedTuple (`cleaned: str`, `was_truncated: bool`, `repair_log: list[str]`).
- ⬜ **6.3** Rewrite `_clean_json_response` per design Theme 3.3 pseudocode. On truncation detection: `logger.error("PHASE2_TRUNCATED detections=%s preview=%r", ...)` then RAISE `Phase2TruncatedError`. **DO NOT** append closing braces/brackets/quotes.
- ⬜ **6.4** Define `DEFAULT_STUFFING_MARKERS` constant and implement `_detect_default_stuffing(report) -> tuple[bool, list[str]]`. Pure function, ≥ 2-of-4 threshold per Requirement 3.10.
- ⬜ **6.5** Update `enrich_with_media`: build prompt via `PHASE2_PROMPT_TEMPLATE.format(...)`, set `max_tokens=6000`, `client.chat.completions.create(..., timeout=45.0)`, outer `asyncio.wait_for(..., timeout=50.0)`.
- ⬜ **6.6** Wire 3 fall-back paths in `enrich_with_media`: catch `Phase2TruncatedError` → log + return `initial_report`; catch `asyncio.TimeoutError` → `logger.error("PHASE2_SLOW outcome=timeout duration_ms=50000 frames=%d", frame_count)` + return `initial_report`; after parse, run `_detect_default_stuffing` → if stuffed: `logger.error("PHASE2_DEFAULT_STUFFED reasons=%s", reasons)` + return `initial_report`. **NO RETRIES.**
- ⬜* **6.7** `tests/unit/test_clean_json_response.py` — `test_clean_json_response_clean_input_unchanged` and `test_clean_json_response_raises_on_truncation`.
- ⬜* **6.8** `tests/unit/test_detect_default_stuffing.py` covering 2-of-4 threshold (single-trigger pass, paired triggers fail).
- ⬜* **6.9** `tests/unit/test_enrich_with_media_fallbacks.py` covering all three fall-back paths.
- ⬜* **6.10** `tests/unit/test_phase2_token_budget_property.py` for Property 6.

#### Component E — Env validator + BUILD_MARKER (Theme 1 → Requirement 5) — 5 tasks
- ⬜ **7.1** Implement `validate_env_vars(settings) -> list[str]` in NEW module `env_validator.py`. 5 checks per Requirements 5.6..5.10. Return `list[str]`, never raise, never mutate. Log each warning at WARNING with prefix `ENV_VALIDATION:`. On empty result, log `ENV_VALIDATION: all checks passed` at INFO.
- ⬜ **7.2** Add `read_build_marker()` helper to `env_validator.py`. Reads `/app/BUILD_MARKER` if present, else `os.environ.get("BUILD_MARKER")`, else returns `dev-<unix-timestamp>`.
- ⬜ **7.3** Update `Dockerfile`: add `ARG BUILD_MARKER` after FROM, add `RUN echo "$BUILD_MARKER" > /app/BUILD_MARKER`. Add comment that `gcloud builds submit` must pass `--substitutions=_BUILD_MARKER=<sha>`.
- ⬜ **7.4** Wire into `main.py` `lifespan()`: immediately after `settings = get_settings()` and before `init_database`, call `validate_env_vars(settings)` exactly once. Then `logger.info("BUILD_MARKER: %s", read_build_marker())`. Store the marker in module-level `_build_marker` for `/health`.
- ⬜* **7.5** `tests/unit/test_env_validator.py` — corruption + clean cases.

#### Component F — /health extension (Theme 2.3 → Requirement 5+2) — 3 tasks
- ⬜ **8.1** Extend `HealthResponse` in `models.py` with `last_gcs_sync: Optional[dict] = None` and `build_marker: Optional[str] = None`.
- ⬜ **8.2** Update `/health` handler in `main.py`: read `last_gcs_sync` via `database.get_last_gcs_sync()` and `model_dump()` it, read `_build_marker`, apply `status="degraded"` rule when `last_gcs_sync.outcome ∉ {ok, skipped}`. Depends on 5.2, 7.4, 8.1.
- ⬜* **8.3** `tests/unit/test_health_endpoint.py` using `httpx.AsyncClient + ASGITransport(app=main.app)`.

#### Component G — OP_CALL log wrapper (Requirement 8) — 2 tasks
- ⬜ **9.1** Wrap each HTTP call in `OpenProjectClient` with `OP_CALL outcome=… duration_ms=…` log emitter. 5 outcomes: `ok` (2xx), `client_error` (4xx), `server_error` (5xx), `network_error` (httpx.RequestError/TimeoutError), `unknown_error`. Apply to `verify_api_key`, `create_work_package`, `add_attachment`, all public methods.
- ⬜* **9.2** `tests/unit/test_openproject_client_logging.py` parametrized over 5 outcomes via `httpx.MockTransport`.

### ⬜ Phase 3 — Integration glue (3 tasks)
- ⬜ **10.1** Wire bucket router output through `_handle_bug_report` so LLM gets original brief (depends on 3.2, 3.6).
- ⬜ **10.2** Verify Phase 2 fall-back paths each produce exactly one OpenProject ticket (depends on 6.6).
- ⬜ **10.3** Confirm env-validator + `BUILD_MARKER` are emitted before any other startup line (depends on 7.4).

### ⬜ Phase 4 — Synthetic webhook scenarios (11 tasks: 11.1–11.11)
- Implement scenarios S1–S9 in `scripts/synthetic_webhook.py` (skeleton already exists from task 2.5)
- 11.1 = harness; 11.2..11.10 = each scenario; 11.11 = `--scenario all` aggregation

### ⬜ Phase 5 — Secret hygiene (5 tasks: 12.1–12.5)
- 12.1 Replace `.env.example` real values with placeholders. **CRITICAL**: confirm via grep that no real `sk-…` token remains.
- 12.2 Add pre-commit hook at `.git/hooks/pre-commit` AND `scripts/hooks/pre-commit` (committed copy). Regex: `\b(sk|pk|api|key|token)[-_][A-Za-z0-9]{16,}\b`. Allow-list `REPLACE_WITH_*` and `<single-line-token>`.
- 12.3 Document hook installation in `README.md` or `scripts/install-hooks.sh`.
- 12.4 Verify `.gitignore`/`.dockerignore`/`.gcloudignore` (already done in 1.2 — re-verify after 12.1).
- 12.5* Test the hook with fake key (must reject) + placeholder (must allow).

### ⬜ Phase 6 — Local end-to-end verification (6 tasks: 13.1–13.6)
- 13.1 `python -m pytest -q` green
- 13.2 `python scripts/synthetic_webhook.py --scenario all` green
- 13.3 `docker build --no-cache --build-arg BUILD_MARKER=local-<sha> .`
- 13.4 `docker run` + `/health` healthy + `build_marker` non-null + `last_gcs_sync` populated
- 13.5 Grep startup logs for `BUILD_MARKER`, `ENV_VALIDATION`, `GCS_SYNC` markers
- 13.6 Run `scripts/preflight.sh` (or `.bat`) end-to-end green

### 🛑 Phase 7 — HARD GATE (task 14.1)

**STOP HERE.** Present a summary of local test results to the user and ask them to type "deploy" before proceeding. **No `gcloud` command, no `env.yaml` creation, no `git push`** before this approval.

### ⬜ Phase 8 — Deploy (4 tasks: 15.1–15.4) — DEPLOY-ONLY

- 15.1 Create `env.yaml` from `.env` (NOT committed). Format: one YAML scalar per env var, single-line.
- 15.2 `git add -A && git commit -m "fix: production reliability — RC1..RC8"` then `git tag reliability-fix-<YYYYMMDD>` then `git push -u origin fix/production-reliability && git push --tags`. Pre-commit hook from 12.2 MUST pass.
- 15.3 `gcloud builds submit --no-cache --substitutions=_BUILD_MARKER=$(git rev-parse --short HEAD) --tag <image> .`
- 15.4 `gcloud run deploy qa-bugbot --image <image> --region asia-south1 --env-vars-file env.yaml --service-account qaautomation@artful-affinity-634.iam.gserviceaccount.com`

### ⬜ Phase 9 — Post-deploy verification (4 tasks: 16.1–16.4) — DEPLOY-ONLY

- 16.1 `curl /health`: assert `status=healthy`, `build_marker == <sha from 15.3>`, `last_gcs_sync.outcome=ok`, `database=connected`.
- 16.2 Grep Cloud Run logs for `BUILD_MARKER`, `ENV_VALIDATION`, `GCS_SYNC` lines.
- 16.3 Confirm `Database initialized` log appears ≥ 200 ms after `Starting up...` (proves real GCS call ran — counter to RC1's 112ms symptom).
- 16.4 Send one known-good bug to dev space (`[LMS Webview] login button broken on iPhone 13`). Assert ticket lands in project 476, priority HIGH (broken keyword), `steps_to_reproduce` not the placeholder.

### ⬜ Phase 10 — Rollback (2 tasks: 17.1–17.2) — failure-only

- 17.1 `gcloud run services update-traffic qa-bugbot --to-revisions qa-bugbot-00026-btk=100 --region asia-south1` (the last known-good revision).
- 17.2 Document regression in `.kiro/specs/production-reliability-fixes/postmortem.md`.

---

## EXACT next steps for the new agent

### 1. Verify the current state matches what this doc claims

Run these and confirm:

```powershell
git branch --show-current      # expect: fix/production-reliability
git log --oneline -3            # expect HEAD: 4e06893
git tag -l "pre-reliability-fix-*"  # expect: pre-reliability-fix-20260527
git status --porcelain          # expect: empty (clean)
```

Then verify these files exist:
- `.kiro/specs/production-reliability-fixes/design.md`
- `.kiro/specs/production-reliability-fixes/requirements.md`
- `.kiro/specs/production-reliability-fixes/tasks.md`
- `tests/unit/conftest.py`
- `requirements-dev.txt`
- `scripts/preflight.sh`, `scripts/preflight.bat`, `scripts/synthetic_webhook.py`

### 2. Verify the source files are STILL in their original (broken) state

This is critical — the task tracker may have stale `in_progress` markers from the tooling hiccup. Check the actual files:

- `bucket_router.py` — should still have `re.search(r'\[([^\]]+)\]', text)` (NOT `BUCKET_TAG_RE.match`). If it has the new constant, that task is actually done.
- `models.py` `validate_priority` — should still use `if 'high' in v_clean: return PriorityLevel.HIGH` substring match. If it uses word-boundary regex, that task is actually done.
- `database.py` `_download_db_from_gcs` — should have a single broad `except Exception as e: logger.error(...)`. If it has the typed ladder (Forbidden/NotFound/etc.), that task is actually done.
- `gemini_client.py` `_clean_json_response` — should still silently close braces/brackets. If it raises `Phase2TruncatedError`, that task is actually done.
- `gemini_client.py` `enrich_with_media` — should still have `max_tokens=2000`, client `timeout=180.0`, outer `wait_for timeout=210.0`. If it has `max_tokens=6000` / `timeout=45.0` / `timeout=50.0`, that task is actually done.

**Trust the source files over the task tracker.**

### 3. Resume from Phase 2

Pick the next ⬜ leaf task (likely **3.1** if all source files are still original). Each component (A–G) is independent, so you can work on them in any order. The recommended order is the same as the task numbers (3.x → 4.x → 5.x → 6.x → 7.x → 8.x → 9.x).

### 4. After each component is done

- Run the unit tests for that component locally: `python -m pytest tests/unit/test_<component>.py -v`
- Update the task tracker to mark leaves complete (use the task tools)
- Commit to the feature branch with a clear message: `fix: <component> per design Theme N`

### 5. After Phase 2 + 3 + 4 + 5 are all done

Move to Phase 6 (local verification). Then **STOP at Phase 7** and ask the user. Do not run any `gcloud` command until they type "deploy".

---

## Critical things to NEVER do

1. **Never run `gcloud builds submit` or `gcloud run deploy`** without explicit user approval at Phase 7.
2. **Never `git push`** until the user approves at Phase 7 (commit locally only).
3. **Never modify `requirements.txt`** to add new runtime deps. Only `requirements-dev.txt`.
4. **Never reduce video frame extraction** below 20 frames.
5. **Never silently repair truncated JSON** — that was the RC4 bug. Raise `Phase2TruncatedError`.
6. **Never retry Phase 2** on truncation/timeout/default-stuffing. Fall back to Phase 1.
7. **Never strip `[Tag]`** from the brief sent to the LLM. Return original text verbatim.
8. **Never commit a real token to `.env.example`**. Use `REPLACE_WITH_*` placeholders.
9. **Never use `gcloud run deploy --set-env-vars`** with space-separated values. Always `--env-vars-file env.yaml`. (RC2 was caused by this exact mistake.)
10. **Never deploy to production from a dirty working tree.** `git status --porcelain` must be empty.
11. **Never skip the env validator wiring (task 7.4)** — it's the canary for future RC2-style env corruption.
12. **Never deploy without `--no-cache`** on the build — that's how RC1 (stale image) happened.

---

## Reference files in priority order

When in doubt, consult these in this order:

1. `design.md` — the technical contract. Theme 1–6 are the fix surfaces. Properties 1–7 are the testable invariants.
2. `requirements.md` — the EARS-format acceptance criteria. Every leaf task has `_Requirements: X.Y_` references that map to specific ACs.
3. `tasks.md` — the execution plan. 102 leaves with `_Requirements:_` traceability.
4. `BUCKET_ANALYSIS.md` (workspace root) — original bucket discovery doc, useful for understanding the project taxonomy.
5. `LLM_HANDOVER.md` (workspace root, may exist) — older general handover for the project (pre-this-spec).

---

## Production environment facts

- Cloud Run service: `qa-bugbot`, region `asia-south1`
- Active revision: `qa-bugbot-00039-dth` (DO NOT TOUCH until Phase 8)
- Last known-good rollback revision: `qa-bugbot-00026-btk`
- Service account: `qaautomation@artful-affinity-634.iam.gserviceaccount.com` (has `roles/storage.objectAdmin` on `gs://qa-bugbot-data`)
- GCS bucket: `gs://qa-bugbot-data/qa_bugbot.db`
- LLM gateway: `https://imllm.intermesh.net/v1`, model `google/gemini-2.5-flash`
- OpenProject: `https://project.intermesh.net`
- Image registry: `asia-south1-docker.pkg.dev/artful-affinity-634/cloud-run-source-deploy/qa-bugbot`

## Known production-state quirks (from live diagnostics)

- The active revision's env vars include the corrupted `DEFAULT_OPENPROJECT_API_KEY` value (with `DEMO_SPACE_ID=...` concatenated). Phase 8 task 15.1 (env.yaml) fixes this.
- `LLM_API_KEY=sk-KNy4qPAxAw0OEvgZuNyOeA` is the company gateway token. Do NOT rotate it. Just remove from `.env.example`.
- `/logs` endpoint is reachable at `https://qa-bug-bot-542857204182.us-central1.run.app/logs` — but note the URL is the OLD us-central1 URL (the active service is in asia-south1). Use the asia-south1 URL when querying after Phase 8 deploy.

---

## Glossary (quick reference)

- **Phase 1** = text-only LLM analysis (`analyze_text_brief`)
- **Phase 2** = media-enriched LLM analysis (`enrich_with_media`)
- **BUILD_MARKER** = startup log line proving new image shipped
- **GCS_SYNC** = structured log line for every download/upload attempt
- **PHASE2_TRUNCATED** = ERROR log when Phase 2 JSON is truncated (should never fire at max_tokens=6000)
- **PHASE2_DEFAULT_STUFFED** = ERROR log when Phase 2 returns mostly placeholders
- **PHASE2_SLOW** = ERROR log when Phase 2 hits 50s asyncio timeout
- **PRIORITY_AMBIGUOUS** = WARNING log when both HIGH and LOW priority keywords match
- **ENV_VALIDATION** = WARNING/INFO log prefix from startup env validator
- **OP_CALL** = structured log line wrapping every OpenProjectClient HTTP call

---

## Final note for the new agent

If anything in this document conflicts with `design.md` or `requirements.md`, **the spec docs win**. This file is a navigation aid, not the contract.

If the user asks you to deploy WITHOUT completing local verification, refuse. Their hard rule is "lets do it locally first after everything done, we will deploy". Phase 7 is the only legitimate gate.

If you find that some Phase 2 tasks are actually already done (because the user's prior working tree had partial fixes), update the task tracker accordingly and proceed from the genuinely-not-done leaves. Do not redo work that's already correct.

Good luck. The hard parts (design + requirements) are locked in. Phase 2 onward is mostly mechanical execution against the spec.
