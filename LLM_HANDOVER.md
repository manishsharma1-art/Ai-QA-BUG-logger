# LLM Handover — QA Bug Logger Bot

> **Purpose:** This document is written for any AI/LLM agent or developer that takes over development or maintenance of this codebase. Read this FIRST before making any changes.
>
> _Last updated: 2026-05-30 — after the production reliability deploy went live and was checkpointed._

---

## 1. What This System Does

**QA Bug Logger** is a production-deployed Google Chat bot that converts QA tester messages (text + screenshots + screen recordings) into structured OpenProject bug tickets — automatically, in under 30 seconds for text, under 2 minutes for video.

### Live state (canonical, verify before touching)

| | Value |
|---|---|
| **Live URL** | `https://qa-bugbot-542857204182.asia-south1.run.app` |
| **Internal alias URL** | `https://qa-bugbot-mh76wysxxa-el.a.run.app` |
| **Cloud Run project** | `artful-affinity-634`, region `asia-south1` |
| **Service name** | `qa-bugbot` |
| **Current revision** | `qa-bugbot-00042-8zj` (100% traffic, healthy) |
| **Service account** | `qaautomation@artful-affinity-634.iam.gserviceaccount.com` |
| **Stable git checkpoint** | `checkpoint-stable-20260530` → commit `5002f50` |
| **Branch** | `fix/production-reliability` (merged-equivalent state, ahead of `main`) |
| **Deploy command** | See §9 below — `gcloud run deploy qa-bugbot --source .` plus required flags |
| **Rollback command** | `gcloud run services update-traffic qa-bugbot --region asia-south1 --to-revisions=qa-bugbot-00042-8zj=100` (when this revision is the rollback target) |
| **Tests** | `pytest tests/unit -q` → 190 passed; `synthetic_webhook.py --scenario all` → 9/9 passed |

> The OLD `https://qa-bug-bot-542857204182.us-central1.run.app/...` URL is a dead deployment in a different region. Don't probe it.

### Tech Stack

- **Framework**: FastAPI (Python 3.11)
- **Deployment**: Google Cloud Run (`asia-south1`)
- **Database**: SQLite (`data/qa_bugbot.db`) via `aiosqlite`, synced to `gs://qa-bugbot-data/qa_bugbot.db` for cross-deploy persistence
- **LLM**: `google/gemini-2.5-flash` via the IndiaMART LLM Gateway (`imllm.intermesh.net/v1`), called through the OpenAI Python SDK
- **Project Tracking**: OpenProject API v3 at `https://project.intermesh.net`
- **Video Processing**: OpenCV (`cv2`)

---

## 2. Architecture — Two Key Separations

### A. Bucket routing (Python deterministic, then optional LLM fallback)

The LLM does NOT decide which OpenProject project a bug goes to in the common case. `bucket_router.py` handles routing in three deterministic layers; only when ALL three fail (provenance == `"default"`) does `main.py` invoke a one-shot LLM bucket-picker.

```
QA brief → bucket_router.extract_bucket_with_provenance(text)
              ├─ Layer 1: [Tag] regex match at start (provenance="tag")
              ├─ Layer 2: free-text patterns (provenance="freetext")
              │     • "bucket - X", "bucket: X" shorthand
              │     • "should raise bug in X", "should be opened in X" prose patterns
              │     • Multi-word project name + alias scoring
              └─ Layer 3: device detection (provenance="device" or "default")
                    • Samsung/iPhone/IQOO etc. → Android or iOS
                    • If nothing matched → provenance="default"
                    │
                    ▼ (only when provenance == "default" AND text >= 20 chars)
              Layer 4: gemini_client.pick_bucket(brief, OP_PROJECTS.keys())
                    • One ~2s LLM call, never raises
                    • Returns canonical project name or None
                    • Bounded by 6s timeout
```

**Brief preservation contract (RC5):** the second tuple element from `extract_bucket_*` is the ORIGINAL `text` byte-identically. Bracket tags are NEVER stripped; the LLM sees the full brief. Pinned by `test_bucket_router.py` and `test_qa_audit_routing.py::test_bracket_tag_is_preserved_in_text_for_llm`.

### B. Two-Phase LLM Pipeline (for the 30-second webhook deadline)

Google Chat webhooks enforce a 30-second response deadline. Video analysis takes 15-60s. Solution:

```
PHASE 1 — Inline, synchronous (≤25s)
  ├─ bucket_router.extract_bucket_with_provenance(text)
  ├─ optional pick_bucket() if provenance == "default"
  ├─ Input validation (link-only, min-text, media-only)
  ├─ analyze_text_brief(text_for_llm)            ← LLM call #1
  │     SYSTEM_PROMPT = base rules + 50 few-shot INPUT/OUTPUT examples
  │     max_tokens=1000, client_timeout=20s, asyncio.wait_for=22s
  │     On gateway error: raises LLMGatewayError(outcome=auth/rate/server/network/unknown)
  ├─ Rejection detection on Phase 1 result
  └─ Returns HTTP response within 30s
       ├─ No media → ticket created inline + result returned
       └─ Has media → "Processing..." ack + asyncio.create_task(_process_media_and_create_ticket)

PHASE 2 — Async background task (15-50s)
  ├─ Download media via Google Chat API
  ├─ OpenCV frame extraction (1 fps, 480px, max 20 frames)
  ├─ enrich_with_media(...)                       ← LLM call #2
  │     PHASE2_PROMPT_TEMPLATE with full 11 mandatory fields
  │     max_tokens=6000, client_timeout=45s, asyncio.wait_for=50s
  │     Three fall-back paths to Phase 1 result:
  │       1. Phase2TruncatedError (response truncated)
  │       2. asyncio.TimeoutError → PHASE2_SLOW log
  │       3. _detect_default_stuffing returns True → PHASE2_DEFAULT_STUFFED log
  │     NO RETRIES on any branch.
  ├─ create_work_package(initial_or_enriched_report, project_id)
  ├─ attach_file_to_work_package() (media to ticket)
  └─ chat_client.send_message(success_msg or rejection_msg)
```

### C. Few-shot prompt augmentation (audit-driven)

`gemini_client._load_few_shot_block(max_examples=50)` runs once at module import. It loads the top 50 entries from `assets/training_examples.json` (606 curated real OpenProject tickets), renders them as INPUT→OUTPUT pairs, appends them to `SYSTEM_PROMPT`. Both Phase 1 and Phase 2 see them.

- 50 examples = ~5,700 chars of prompt overhead = ~1,500 tokens
- Empirically measured Phase 1 latency at 50 examples: ~4.4s avg (was 3.85s with 5 examples)
- 100 examples works but adds little value
- 150+ examples hits a gateway timeout cliff — DO NOT BUMP

---

## 3. File Map

| File | Purpose | Key entry points |
|---|---|---|
| `main.py` | FastAPI app, lifespan, webhook handler, `_handle_bug_report` orchestration | `webhook()`, `_handle_bug_report()`, `_process_media_and_create_ticket()` |
| `gemini_client.py` | LLM integration, prompts, frame extraction, smoke test, bucket picker | `analyze_text_brief()`, `enrich_with_media()`, `smoke_test()`, `pick_bucket()`, `_clean_json_response()`, `_log_llm_call()` |
| `bucket_router.py` | Deterministic project routing, no LLM | `extract_bucket_from_message()`, `extract_bucket_with_provenance()`, `_extract_bucket_from_freetext()`, `_resolve_tag()` |
| `models.py` | Pydantic models, validators | `ExtractedBugReport`, `validate_priority` (word-boundary regex), `validate_platform` (30-alias map) |
| `openproject_client.py` | OpenProject v3 REST client + `OP_CALL` log wrapper | `create_work_package(bug_report, api_key, project_id)`, `_log_op_call()`, `attach_file_to_work_package()` |
| `google_auth.py` | SA auth, Chat API send, attachment download | `send_message()`, `download_attachment()`, `is_available()` |
| `database.py` | SQLite + GCS sync with fail-closed safeguard | `get_user_by_chat_id()`, `create_or_update_user()`, `_download_db_from_gcs()`, `_upload_db_to_gcs()`, `_safe_upload_db_to_gcs()`, `get_last_gcs_sync()` |
| `env_validator.py` | Startup env-var corruption canary | `validate_env_vars()` (5 checks), `read_build_marker()` |
| `config.py` | Settings, `OP_PROJECTS` (34 projects), bug-type / priority / environment ID mappings | `get_settings()` |
| `assets/training_examples.json` | 606 curated real tickets — source for the 50-example few-shot pack | (read by `gemini_client._load_few_shot_block`) |

---

## 4. Bucket Routing — How to Add a Project

1. Get the project ID from OpenProject API or URL
2. Add to `config.py` → `OP_PROJECTS`: `"Project Name": ID,`
3. Add aliases to `bucket_router.py` → `PROJECT_ALIASES` (lowercase keys)
4. Add a regression case to `tests/unit/test_qa_audit_routing.py::AUDIT_CASES`
5. Deploy. No prompt changes needed.

The 34 currently-supported projects are listed in `config.py`. Three projects flagged by the May 2026 QA audit but not yet in `OP_PROJECTS` (route via LLM picker fallback): `Model Product Library`, `Msite SOI`, `Export`. Documented in `test_qa_audit_routing.py::test_known_config_gaps_documented` — that test will fail loudly the day they're added, prompting a real audit case.

---

## 5. LLM System Prompt

**File:** `gemini_client.py` → `SYSTEM_PROMPT`
**Size:** ~14,700 tokens total = ~3,100 tokens of rules + ~11,600 tokens of 50 few-shot INPUT/OUTPUT examples
**Purpose:** Bug analysis ONLY. NOT bucket routing (that's `bucket_router.py`).

**What the LLM returns:**
```json
{
  "title": "string",
  "actual_behavior": "string",
  "expected_behavior": "string",
  "steps_to_reproduce": ["step1", "step2"],
  "device": "string",
  "operating_system": "string",
  "environment": "LIVE or STAGE",
  "app_version": "string",
  "bug_type": "UI/UX or Functional/Logical or Network or Content",
  "priority": "High or Medium or Low",
  "logs_or_links": "string or null"
}
```

**What the LLM does NOT return:**
- `platform` — has a Pydantic default of `Android`; the actual project routing is independent
- `category` — disabled to prevent 422 errors

**Priority calibration (in prompt + reinforced by 50 examples):**
- 95% should be Medium
- High ONLY for crashes, complete login failure, payment broken, data loss
- Low ONLY for pure cosmetic issues

---

## 6. Observability

Every external call emits a structured log line. Greppable in Cloud Run logs OR via the bot's own `/logs` endpoint.

| Log marker | Source | Outcomes |
|---|---|---|
| `BUILD_MARKER: <sha>` | `env_validator.read_build_marker` at startup | Once at lifespan startup. Currently shows `unknown` due to a Dockerfile default; cosmetic. |
| `ENV_VALIDATION: <warning>` or `ENV_VALIDATION: all checks passed` | `env_validator.validate_env_vars` | INFO on clean, WARNING per check that failed. RC2 canary. |
| `GCS_SYNC op=<dl/ul> outcome=<8 vals> duration_ms=… bytes=… detail="…"` | `database._download/_upload_db_to_gcs` | 8 outcomes: `ok`, `skipped`, `import_error`, `auth_error`, `forbidden`, `not_found`, `network_error`, `unknown_error`. |
| `LLM_CALL phase=<phase1/phase2/smoke/bucket_picker> outcome=<5 vals> duration_ms=…` | `gemini_client._log_llm_call` | 5 outcomes: `ok`, `auth_error`, `rate_limit`, `server_error`, `network_error`, `unknown_error`. |
| `OP_CALL method=… url=… outcome=<5 vals> duration_ms=…` | `openproject_client._log_op_call` | 5 outcomes: `ok`, `client_error`, `server_error`, `network_error`, `unknown_error`. |
| `PHASE2_TRUNCATED detections=… preview=…` | `gemini_client._clean_json_response` | Fires from BOTH Phase 1 and Phase 2 — the class name is historical. |
| `PHASE2_DEFAULT_STUFFED reasons=…` | `gemini_client._detect_default_stuffing` | When the LLM returns ≥2 of 4 placeholder markers. |
| `PHASE2_SLOW outcome=timeout duration_ms=50000 frames=N` | `gemini_client.enrich_with_media` | When `asyncio.wait_for` deadline trips. |
| `PRIORITY_AMBIGUOUS:` | `models.validate_priority` | When a string matches both HIGH and LOW whitelists. |

`/health` exposes the most recent `last_gcs_sync` snapshot and the smoke-test outcome (`gemini` field).

---

## 7. Database Persistence (GCS Sync)

**Problem:** SQLite is inside the container → lost on every deployment.
**Solution:** Sync to/from `gs://qa-bugbot-data/qa_bugbot.db` (~12 KB).

**Flow:**
- On startup: `_download_db_from_gcs()` restores registrations. Outcome captured in `_last_gcs_sync` and exposed via `/health`.
- After every `create_or_update_user`: `_safe_upload_db_to_gcs()` (note: SAFE wrapper, not `_upload_db_to_gcs` directly).
- On shutdown: `close_database()` → final sync.

**Fail-closed safeguard (added 2026-05-28):** `_safe_upload_db_to_gcs` refuses to upload if the most recent download did NOT succeed (outcome ≠ `ok` and ≠ `skipped`). This prevents a fresh-empty local DB from overwriting the GCS copy after a transient download failure on cold start. Module-level flag: `database._uploads_safe`.

**Service account access:** `qaautomation@artful-affinity-634.iam.gserviceaccount.com` has `roles/storage.objectAdmin` on `gs://qa-bugbot-data`.

**Pinned by tests:** `test_registration_persistence.py::test_S6_registration_survives_simulated_restart`.

---

## 8. OpenProject Integration

**API:** OpenProject v3 REST API at `https://project.intermesh.net/api/v3/`
**Auth:** Per-user API keys via Basic auth (`apikey:<key>`)
**Project routing:** `create_work_package(bug_report, api_key, project_id=N)` — `project_id` comes from `bucket_router`, not from `bug_report.platform`.

### Key fields

| Field | Source |
|---|---|
| Project | `project_id` parameter from bucket_router (numeric ID) |
| Type | Always "Bug" (ID 7) |
| Priority | From LLM: High→9, Medium→8, Low→7 |
| Bug Type (customField6) | From LLM: UI/UX→10, Functional/Logical→11, Network→12, Content→13 |
| Environment (customField9) | From LLM: LIVE→21, STAGE→22 |
| Steps (customField4) | From LLM: numbered list |
| Category | DISABLED (was causing 422s when LLM returned invalid category names) |

### Reply payload (returned to caller / shown to user)

The `project` field in the returned dict is the canonical name from `OP_PROJECTS` (e.g. `"Seller Dashboard"`), NOT `bug_report.platform.value.upper()`. This is the QA-audit fix — previously every reply said "Project: ANDROID" regardless of where the ticket actually went.

The reply NO LONGER includes a `Platform:` line (was always misleading).

---

## 9. Deployment

```bash
gcloud run deploy qa-bugbot \
  --source . \
  --region asia-south1 \
  --no-cpu-throttling \
  --memory 1Gi \
  --cpu 1 \
  --timeout 300 \
  --min-instances 1 \
  --max-instances 100 \
  --service-account qaautomation@artful-affinity-634.iam.gserviceaccount.com \
  --update-env-vars "BUILD_MARKER=<sha>,DEFAULT_OPENPROJECT_API_KEY=<key>,DEMO_SPACE_ID=<id>"
```

### Critical deployment nuances

- `--no-cpu-throttling`: **Mandatory.** Cloud Run scales CPU to zero immediately after an HTTP response. Phase 2 uses `asyncio.create_task` to process media after the webhook ack returns, so without this flag the background task dies silently.
- `--memory 1Gi`: Required for OpenCV to process up to 20 video frames in memory.
- `--update-env-vars` value MUST be **comma-separated**, not space-separated. RC2 was caused by the space-separator concatenating `DEMO_SPACE_ID=...` into the API key value.
- `service-account.json` MUST be in the source upload. It's `.gitignored` (so it never enters version control) but ALLOWED through `.gcloudignore` and `.dockerignore`. The v1 deploy attempt failed because this file was missing.
- After the build completes, Cloud Run creates a new revision but may NOT auto-flip traffic if traffic was previously pinned. Force the flip:
  ```bash
  gcloud run services update-traffic qa-bugbot \
      --region asia-south1 \
      --to-revisions=<new-revision-name>=100
  ```

### Rollback

```bash
# Fastest path — flip traffic to a known-good revision
gcloud run services update-traffic qa-bugbot \
    --region asia-south1 \
    --to-revisions=qa-bugbot-00042-8zj=100   # <- the current stable revision
```

For source rollback: `git reset --hard checkpoint-stable-20260530`.

### Pre-commit hook (secret scan)

Installed at `.git/hooks/pre-commit` from `scripts/hooks/pre-commit`. Scans staged `.env*` files for `(sk|pk|api|key|token)[-_][A-Za-z0-9]{16,}`. Allow-list: `REPLACE_WITH_*`. Tested by `test_precommit_hook.py`.

---

## 10. Recent Changes Worth Knowing About (2026-05-25 → 2026-05-30)

### Production reliability deploy (this batch)

- **RC1–RC8 closed**: stale image bypass, env-var corruption, silent GCS exceptions, Phase 2 truncation, bracket-tag stripping, priority substring match, `.env.example` real key, commit discipline.
- **`/health` extended** with `last_gcs_sync` (8-outcome typed result) and `build_marker` fields.
- **Few-shot prompting wired in** at 50 examples from a new 600-entry curated set (was previously orphaned in `assets/`).
- **`Project: ANDROID` reply lie fixed** — reply now uses canonical `OP_PROJECTS` name resolved from the actual `project_id`.
- **`Platform: Android` reply line removed** — `PlatformType` enum default leaked into desktop ticket replies; the line was always wrong for non-mobile bugs.
- **`space_name` NameError fixed** in `_handle_bug_report` for text-only standard-format webhooks.
- **`LLMGatewayError` 5-outcome classifier** — Phase 1 gateway errors no longer leak raw SDK exception text to chat. Categorized friendly messages for auth/rate/server/network/unknown.
- **Startup smoke test** — `gemini_client.smoke_test()` runs at lifespan and surfaces via `/health.gemini` (one of `ok`, `auth_error`, `rate_limit`, `server_error`, `network_error`, `unknown_error`, `not_configured`).
- **Pre-commit hook** — `.git/hooks/pre-commit` rejects staged `.env*` files with real-looking tokens.
- **Fail-closed GCS upload guard** — `_safe_upload_db_to_gcs` won't upload if the previous download failed, protecting existing registrations from a fresh-empty local DB.

### Earlier reliability work

- Bucket routing moved entirely to Python (`bucket_router.py`) — LLM no longer chooses the project for the common case.
- LLM prompt shrunk from 8000 to ~1500 base tokens (now ~3,100 base + 11,600 few-shot = ~14,700 total).
- Two-phase pipeline introduced (Phase 1 inline + Phase 2 async).
- `--no-cpu-throttling` made mandatory after FastAPI BackgroundTasks were silently killed by Cloud Run.
- `_active_background_tasks` set added to prevent Python GC from killing in-flight Phase 2 tasks.

---

## 11. Critical Things to NEVER Do

1. **Never use `--set-env-vars` with space-separated values.** RC2 root cause. Always comma-separated, or use `--env-vars-file env.yaml`.
2. **Never deploy without `--no-cpu-throttling`.** Phase 2 will silently die.
3. **Never deploy without `--memory 1Gi`.** OpenCV will OOM.
4. **Never re-add `service-account.json` to `.gcloudignore`/`.dockerignore`.** It's gitignored; the runtime needs it in the image.
5. **Never modify `requirements.txt` to add new runtime deps without testing.** Use `requirements-dev.txt` for dev deps.
6. **Never reduce video frame extraction below 20 frames per video.**
7. **Never silently repair truncated JSON.** That was RC4 — `_clean_json_response` raises `Phase2TruncatedError`.
8. **Never retry Phase 1 or Phase 2 on truncation/timeout/default-stuffing.** Fall back to Phase 1 result instead.
9. **Never strip `[Tag]` from the brief sent to the LLM.** The LLM needs the full original text.
10. **Never add bucket routing back to the LLM prompt.** It caused timeouts and was unreliable. `bucket_router.py` is the authority.
11. **Never make `platform` field required in `ExtractedBugReport`.** LLM doesn't return it (default in models.py).
12. **Never bump few-shot examples past 100** without re-measuring latency. The IndiaMART gateway has a timeout cliff between 100 and 150.
13. **Never commit a real token to `.env.example`.** Pre-commit hook will catch you (tested).
14. **Never deploy from a dirty working tree.** `git status --porcelain` must be empty.

---

## 12. How to Continue Development

If you are an LLM reading this:

1. Read `.kiro/specs/production-reliability-fixes/HANDOVER.md` next — that's the spec-level "current truth" doc with detailed live-state evidence.
2. Verify before trusting: `curl https://qa-bugbot-542857204182.asia-south1.run.app/health` and check `/logs`.
3. Trust source files over markdown if anything seems inconsistent.
4. The current pipeline is well-instrumented (`LLM_CALL`, `OP_CALL`, `GCS_SYNC`, `ENV_VALIDATION` log markers). Use them when debugging.
5. Tests are the contract. 190 unit tests + 9 synthetic scenarios pin the current behavior.
6. The `service-account.json` file must exist locally at the repo root before any `--source .` deploy.
7. To test locally: use `ngrok` to tunnel webhooks to a local `uvicorn` instance.
