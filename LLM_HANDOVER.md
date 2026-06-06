# LLM Handover — QA Bug Logger Bot

> **Purpose:** This document is written for any AI/LLM agent or developer that takes over development or maintenance of this codebase. Read this FIRST before making any changes.
>
> _Last updated: 2026-06-05 — security hardening, prompt improvements, and TestLink knowledge base deployed._

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
| **Current revision** | `qa-bugbot-00059-xrv` (100% traffic, healthy) |
| **Service account** | `qaautomation@artful-affinity-634.iam.gserviceaccount.com` |
| **Stable git checkpoint** | `checkpoint-stable-rag-20260603` |
| **Branch** | `feat/rag-6k-corpus` (merged-equivalent state, ahead of `main`) |
| **Deploy command** | See §9 below — `gcloud run deploy qa-bugbot --source .` plus required flags |
| **Rollback command** | `gcloud run services update-traffic qa-bugbot --region asia-south1 --to-revisions=qa-bugbot-00055-vpc=100` (when this revision is the rollback target) |
| **Tests** | `pytest tests/unit -q` → 236 passed; `synthetic_webhook.py --scenario all` → 10/10 passed |

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
  │     SYSTEM_PROMPT = base rules
  │                   + TestLink best-match test case (Layer A, if TESTLINK_RAG_ENABLED)
  │                   + RAG-selected few-shot examples from bug corpus (Layer B)
  │     max_tokens=512, client_timeout=20s, asyncio.wait_for=22s
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
  │     environment/bug_type/priority injected from Phase 1 values (not hardcoded defaults)
  │     max_tokens=1024, client_timeout=45s, asyncio.wait_for=50s
  │     Three fall-back paths to Phase 1 result:
  │       1. Phase2TruncatedError (response truncated)
  │       2. asyncio.TimeoutError → PHASE2_SLOW log
  │       3. _detect_default_stuffing returns True → PHASE2_DEFAULT_STUFFED log
  │     NO RETRIES on any branch.
  ├─ create_work_package(initial_or_enriched_report, project_id)
  ├─ attach_file_to_work_package() (media to ticket)
  └─ chat_client.send_message(success_msg or rejection_msg)
```

### C. Dual-Layer RAG Architecture (Anti-Hallucination)

To prevent the LLM from hallucinating fake account IDs, inventing buttons, or guessing reproduction steps, the bot uses a strictly enforced **Dual-Layer Retrieval-Augmented Generation (RAG)** architecture.

#### Layer A: TestLink Knowledge Base (Functionality Flow)
*   **Corpus:** 710 TestLink sanity test cases (`assets/testlink_cases.json`).
*   **Purpose:** Acts as a dictionary for official functionality flow. It provides the exact screen names, CTA button names, and navigation paths for the feature being tested.
*   **Mechanism:** `testlink_retriever.py` embeds the incoming brief, finds the single best-matching sanity test case, and prepends it to the prompt. This strictly grounds the LLM in real domain terminology. (Skipped if `TESTLINK_RAG_ENABLED=false` or similarity < 0.30).

#### Layer B: 11k Bug Corpus (Structure & Context)
*   **Corpus:** 11,862 historical QA tickets (`assets/training_examples.json`).
*   **Purpose:** Teaches the LLM how to format the ticket and how past bugs in this specific area were written.
*   **Mechanism:** `bug_retriever.py` fetches the top 10 most semantically similar historical bugs and injects them as few-shot examples.

**Static Fallback:** If RAG is disabled or fails, the system falls back to a static block of 10 examples.

| Detail | Value |
|---|---|
| **Embedder** | `sentence-transformers/all-MiniLM-L6-v2` |
| **Corpus** | 710 sanity test cases across 80 modules — `assets/testlink_cases.json` |
| **Source** | TestLink suite ID 26691 at `https://testlink.intermesh.net` |
| **Project prefix** | AND |
| **Similarity threshold** | Cosine ≥ 0.30; no injection below threshold |
| **GCS cache** | `gs://qa-bugbot-data/testlink_embeddings.npz` |
| **Kill-switch env var** | `TESTLINK_RAG_ENABLED=false` (leave unset or `true` to enable) |
| **Refresh** | `python scripts/fetch_testlink.py` (re-fetches from TestLink API) |
| **API key env var** | `TESTLINK_API_KEY` — never commit to version control |

**Example value:** the "Purchase Buy Lead" flow now includes the Subscription Plan intermediate screen sourced from TC AND-4714, which the LLM would otherwise omit or invent.

---

## 3. Codebase Site Map

This is the complete directory structure and architectural map of the project.

```text
QA_BUG_Logger/
│
├── main.py                     # Entry point, FastAPI app, webhook handler, two-phase orchestration
├── gemini_client.py            # LLM integration, prompt templates, anti-hallucination rules, video frames
├── bucket_router.py            # Deterministic OpenProject routing logic (regex + scoring), NO LLM
├── models.py                   # Pydantic models & validation schemas
├── openproject_client.py       # OpenProject REST client, ticket creation, attachment uploading
├── google_auth.py              # Google Cloud service account auth, Chat API sending, video downloads
├── database.py                 # SQLite local DB & GCS sync for cross-deployment persistence
├── env_validator.py            # Startup checks for environment variable corruption
├── config.py                   # Project configurations, OpenProject IDs, aliases, priorities
├── bug_retriever.py            # Layer B RAG: Retrieves top-K similar bugs from 11k corpus
├── testlink_retriever.py       # Layer A RAG: Retrieves TestLink sanity case for functionality flow
│
├── assets/                     # Data dependencies (Not pushed to Git, downloaded via scripts/GCS)
│   ├── training_data_6000.csv  # Raw historical bugs
│   ├── training_examples.json  # 11.8K parsed historical bugs used for RAG Layer B
│   └── testlink_cases.json     # 710 TestLink sanity cases used for RAG Layer A
│
├── scripts/                    # Utilities and pipelines
│   └── fetch_testlink.py       # Connects to TestLink XML-RPC API to refresh testlink_cases.json
│
├── tests/                      # Unit and integration test suite (pytest)
│   ├── unit/                   # 236 unit tests for routing, prompting, auth, etc.
│   └── ...
│
└── data/                       # Local volume (gitignored)
    └── qa_bugbot.db            # Local SQLite database (synced to GCS)
```

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
**Size (static fallback):** ~5,600 tokens total = ~3,100 tokens of rules + ~2,500 tokens of 10 few-shot INPUT/OUTPUT examples. With RAG active, few-shot token count varies by retrieved content.
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

**Schema constraints enforced in the prompt (added 2026-06-05):**
- `actual_behavior`: 3-sentence format — (1) what the user did, (2) what actually happened, (3) any error text shown. Prevents copy-paste of the title as `actual_behavior`.
- `expected_behavior`: must describe the correct outcome; must NOT be a simple negation of `actual_behavior` (e.g. "should not crash" is rejected).

**Prompt rule exceptions (added 2026-06-05):**
- Rule 1 exception: login/OTP/onboarding bugs are NOT forced to use "Login as seller" as Step 1 — the bug IS the login step.
- Rule 2 exception: bugs entered via notification tap or deep link skip the manual navigation step.

**Closed-vocabulary standard flows (added 2026-06-05):** The prompt defines fixed, named flows (Purchase Buy Lead, BMC message, Add product) with precise step sequences. Replaces the previous open-ended "use your domain knowledge" instruction.

**Priority calibration (in prompt + reinforced by examples):**
- 95% should be Medium
- High ONLY for crashes, complete login failure, payment broken, data loss
- Low ONLY for pure cosmetic issues

---

## 6. Observability

Every external call emits a structured log line. Greppable in Cloud Run logs OR via the bot's own `/logs` endpoint (token-gated — see §Security).

| Log marker | Source | Outcomes |
|---|---|---|
| `BUILD_MARKER: <sha>` | `env_validator.read_build_marker` at startup | Once at lifespan startup. Currently shows `unknown` due to a Dockerfile default; cosmetic. |
| `ENV_VALIDATION: <warning>` or `ENV_VALIDATION: all checks passed` | `env_validator.validate_env_vars` | INFO on clean, WARNING per check that failed. RC2 canary. |
| `GCS_SYNC op=<dl/ul> outcome=<8 vals> duration_ms=… bytes=… detail="…"` | `database._download/_upload_db_to_gcs` | 8 outcomes: `ok`, `skipped`, `import_error`, `auth_error`, `forbidden`, `not_found`, `network_error`, `unknown_error`. |
| `LLM_CALL phase=<phase1/phase2/smoke/bucket_picker> outcome=<5 vals> duration_ms=…` | `gemini_client._log_llm_call` | 5 outcomes: `ok`, `auth_error`, `rate_limit`, `server_error`, `network_error`, `unknown_error`. |
| `OP_CALL method=… url=… outcome=<5 vals> duration_ms=…` | `openproject_client._log_op_call` | 5 outcomes: `ok`, `client_error`, `server_error`, `network_error`, `unknown_error`. |
| `PHASE2_TRUNCATED detections=… preview=…` | `gemini_client._clean_json_response` | Fires from BOTH Phase 1 and Phase 2 — the class name is historical. |
| `RAG_INDEX outcome=<4 vals> source=<3 vals>` | `bug_retriever.index` | Outcomes: ok, cache_hit, cache_stale, disabled. Source: gcs, recompute, none. |
| `RAG_RETRIEVE outcome=<5 vals> duration_ms=…` | `bug_retriever.retrieve` | Outcomes: ok, embed_error, short_brief, empty_corpus, index_unavailable. |
| `PHASE2_DEFAULT_STUFFED reasons=…` | `gemini_client._detect_default_stuffing` | When the LLM returns ≥2 of 4 placeholder markers. |
| `PHASE2_SLOW outcome=timeout duration_ms=50000 frames=N` | `gemini_client.enrich_with_media` | When `asyncio.wait_for` deadline trips. |
| `PRIORITY_AMBIGUOUS:` | `models.validate_priority` | When a string matches both HIGH and LOW whitelists. |

**Health endpoints:**
- `GET /health` — public, returns only `{status, database, gemini, timestamp}`.
- `GET /health/details` — requires `X-Internal-Token` or `Authorization: Bearer <token>`, returns full snapshot including `last_gcs_sync`, RAG state, build marker, and all subsystem details.

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
**Auth:** Per-user API keys via Basic auth (`apikey:<key>`). Keys are encrypted at rest using Fernet/AES-128 when `DB_ENCRYPTION_KEY` is set (see §Security).
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
  --memory 4Gi \
  --cpu 1 \
  --timeout 300 \
  --min-instances 1 \
  --max-instances 100 \
  --service-account qaautomation@artful-affinity-634.iam.gserviceaccount.com \
  --update-env-vars "BUILD_MARKER=<sha>,DEFAULT_OPENPROJECT_API_KEY=<key>,DEMO_SPACE_ID=<id>,RAG_ENABLED=true,RAG_TOPK=10,RAG_CACHE_GCS=true"
```

**New optional env vars (2026-06-05) — add to `--update-env-vars` as needed:**

| Env var | Purpose | Leave unset to… |
|---|---|---|
| `WEBHOOK_AUDIENCE` | Enable Google Chat OIDC JWT verification on inbound webhooks | Disable verification (dev/local) |
| `INTERNAL_API_TOKEN` | Gate `/logs` and `/health/details` endpoints | Allow unauthenticated access (not recommended in prod) |
| `DB_ENCRYPTION_KEY` | Fernet key for encrypting OpenProject API keys at rest | Store keys in plaintext |
| `TESTLINK_API_KEY` | Authenticate to TestLink API for corpus refresh | Skip TestLink fetch |
| `TESTLINK_RAG_ENABLED` | Set to `false` to disable Layer A entirely | Enabled by default |

### Critical deployment nuances

- `--no-cpu-throttling`: **Mandatory.** Cloud Run scales CPU to zero immediately after an HTTP response. Phase 2 uses `asyncio.create_task` to process media after the webhook ack returns, so without this flag the background task dies silently.
- `--memory 4Gi`: Required to load the 11,862-entry bug-corpus embeddings and 710 TestLink TC embeddings on startup without silent OOM errors, and for OpenCV video processing.
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

## Security

Added 2026-06-05. All security features degrade gracefully — leaving env vars unset simply disables the corresponding protection, which is acceptable in local dev.

### Webhook authentication

`_verify_webhook_auth()` in `main.py` validates the Google Chat OIDC JWT on every inbound webhook request.

- Set `WEBHOOK_AUDIENCE=https://qa-bugbot-542857204182.asia-south1.run.app` to enable in production.
- Leave `WEBHOOK_AUDIENCE` unset for local dev/testing — verification is skipped entirely.

### Protected endpoints

| Endpoint | Auth required | Returns |
|---|---|---|
| `GET /health` | None (public) | `{status, database, gemini, timestamp}` only |
| `GET /health/details` | `X-Internal-Token: <token>` or `Authorization: Bearer <token>` | Full system snapshot |
| `GET /logs` | Same as `/health/details` | Structured log tail |

Set `INTERNAL_API_TOKEN` to enable token gating. Leave unset to allow unauthenticated access (not recommended in production).

### Rate limiting

1 bug report per 5 seconds per sender (Google Chat user ID). Excess requests receive a friendly rejection message and are not processed. Configurable via the `RATE_LIMIT_WINDOW_SECONDS` constant in `main.py`.

### OpenProject API key encryption

When `DB_ENCRYPTION_KEY` is set (Fernet key), OpenProject API keys are encrypted at rest in SQLite using Fernet/AES-128. Generate a key with:

```python
from cryptography.fernet import Fernet
print(Fernet.generate_key().decode())
```

Store the key value in `DB_ENCRYPTION_KEY` — never commit it.

### Additional hardening (2026-06-05)

- 5,000-character text length cap on inbound messages
- Control-character sanitization on all user input before processing
- Raw `str(e)` exception text removed from all user-facing error messages
- CORS locked to `https://chat.googleapis.com`
- Attachment filenames sanitized before use in file operations
- `asyncio.get_event_loop()` replaced with `asyncio.get_running_loop()` throughout

---

## 10. Local vs Production Discrepancies (As of 2026-06-06)

This section explicitly documents what is currently running on Production versus what has been fixed in the Local environment and is waiting to be deployed.

| Feature / Issue | Production State | Local State |
|---|---|---|
| **RAG Architecture** | Uses massive 50-example static prompt (no RAG). | Uses Dual-Layer RAG (TestLink for flow + 11k Bug Corpus for structure). |
| **Bucket Routing (Device Fallback)** | Hallucinates "Seller Dashboard" when a tester provides a generic OS (e.g. "Crash on Android 14") because it fails to parse the OS format and falls back to the LLM. | Instantly routes to Android/iOS using `_OS_VERSION_RE` and `_has_strong_device_signal` without invoking the LLM fallback. |
| **Bucket Routing (Explicit Fallback)** | N/A | Fixed a logic ordering bug where device detection accidentally overrode explicit shorthand (e.g. "bucket: Photo Search"). Layer 2 (Free-text explicit) now correctly runs *before* Layer 3 (Device Fallback). |
| **LLM Guardrails** | No anti-hallucination guardrails; LLM frequently invents fake account IDs (e.g., `1002345678`) and guesses reproduction steps. | 9 explicit Anti-Hallucination rules injected into the prompt. Forces LLM to only use steps shown in video or TestLink. |
| **Phase 1 Latency** | ~4.4 seconds for Slack ACK. | < 0.5 seconds for Slack ACK (no LLM fallback needed for generic routing). |

---

## 11. Recent Changes Worth Knowing About (2026-05-25 → 2026-06-05)

### Security hardening (2026-06-05)

- Webhook JWT verification for Google Chat OIDC (`_verify_webhook_auth()`, controlled by `WEBHOOK_AUDIENCE`)
- Per-user rate limiting: 1 bug report per 5-second window per sender
- 5,000-character text length cap on inbound messages
- Control-character sanitization on user input
- OpenProject API keys encrypted at rest using Fernet/AES-128 (controlled by `DB_ENCRYPTION_KEY`)
- `/logs` and `/health/details` token-gated (controlled by `INTERNAL_API_TOKEN`)
- Raw `str(e)` removed from all user-facing error messages
- CORS locked to `https://chat.googleapis.com`
- Attachment filenames sanitized
- `asyncio.get_event_loop()` → `asyncio.get_running_loop()` throughout

### Prompt improvements (2026-06-05)

- `actual_behavior` schema: 3-sentence format (what user did + outcome + error text) — prevents copy-paste of title
- `expected_behavior` schema: must describe correct outcome, not a simple negation
- Rule 1 exception: login/OTP/onboarding bugs no longer forced to "Login as seller" as Step 1
- Rule 2 exception: notification/deep-link entry points skip manual navigation step
- Closed-vocabulary standard flows (Purchase Buy Lead, BMC message, Add product) — replaces open-ended domain knowledge invocation
- Training data quality filters at index time: skip HTML-artifact entries, unfilled template entries, entries without steps
- Static fallback: 50 → 10 examples (~12K tokens → ~2.5K tokens, ~1,800ms latency saving on cold start)
- `max_tokens` Phase 1: 2000 → 512
- `max_tokens` Phase 2: 6000 → 1024
- Phase 2 output template: `environment`/`bug_type`/`priority` injected from Phase 1 values (previously hardcoded as `"STAGE"`/`"Functional/Logical"`/`"Medium"`)

### TestLink knowledge base (2026-06-05)

- 710 sanity test cases fetched and indexed from TestLink suite 26691 (`https://testlink.intermesh.net`)
- Semantic retriever (`testlink_retriever.py`) prepends the single best-matching test case to the LLM prompt as "Layer A" (before bug-corpus few-shot examples)
- Gives the LLM exact screen names, CTA names, and intermediate screens it cannot infer from bug tickets alone
- Example: "Purchase Buy Lead" flow now includes the Subscription Plan screen sourced from TC AND-4714
- Kill-switch: `TESTLINK_RAG_ENABLED=false`; refresh corpus: `python scripts/fetch_testlink.py`

### RAG-Augmented Few-Shot Retrieval (2026-06-02)

- **Architecture:** Replaced the static 50-example few-shot prompt with a dynamic RAG retriever (`bug_retriever.py`) that uses `sentence-transformers/all-MiniLM-L6-v2` to fetch the top-K most semantically similar tickets from the corpus.
- **Cache Mechanism:** Embeddings are cached to `gs://qa-bugbot-data/embeddings.npz` and loaded on cold start to prevent ~15s recompute delays, verified via content hash.
- **Fallbacks:** 4 layers of fallback ensure the webhook never fails due to RAG (stale cache → recompute, download fail → recompute, embed error → static block, import error → static block).
- **Env Vars:** Controlled by `RAG_ENABLED` (master kill switch), `RAG_TOPK`, and `RAG_CACHE_GCS`.
- **Latency:** Decreased Phase 1 median latency by >1,500ms compared to the old static 50-example prompt.
- **`/health`:** Extended with a `.rag` sub-object detailing corpus size, model, cache source, and outcome.

### Production reliability deploy (May 2026)

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
- LLM prompt shrunk from 8,000 to ~1,500 base tokens (now ~3,100 base + dynamic few-shot = varies).
- Two-phase pipeline introduced (Phase 1 inline + Phase 2 async).
- `--no-cpu-throttling` made mandatory after FastAPI BackgroundTasks were silently killed by Cloud Run.
- `_active_background_tasks` set added to prevent Python GC from killing in-flight Phase 2 tasks.

---

## 12. Critical Things to NEVER Do

1. **Never use `--set-env-vars` with space-separated values.** RC2 root cause. Always comma-separated, or use `--env-vars-file env.yaml`.
2. **Never deploy without `--no-cpu-throttling`.** Phase 2 will silently die.
3. **Never deploy without `--memory 4Gi`.** The `sentence-transformers` RAG embedder will silently OOM during background initialization of the 11,862-entry corpus and 710 TestLink TC embeddings if given less memory.
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
15. **Never reduce `max_tokens` Phase 1 below 400.** Current maximum observed output is ~313 tokens; 512 is the safe floor.
16. **Never reduce `max_tokens` Phase 2 below 800.** Full 11-field structured output requires headroom.
17. **Never remove the `TESTLINK_RAG_ENABLED` env var.** It is the kill-switch if TestLink test cases cause wrong steps to be generated.
18. **Never commit the TestLink API key to version control.** Store only in env vars (`TESTLINK_API_KEY`).

---

## 13. How to Continue Development

If you are an LLM reading this:

1. Read `.kiro/specs/production-reliability-fixes/HANDOVER.md` next — that's the spec-level "current truth" doc with detailed live-state evidence.
2. Verify before trusting: `curl https://qa-bugbot-542857204182.asia-south1.run.app/health` for public status. For full system state (RAG, GCS sync, build marker), use `GET /health/details` with `Authorization: Bearer <INTERNAL_API_TOKEN>`.
3. Trust source files over markdown if anything seems inconsistent.
4. The current pipeline is well-instrumented (`LLM_CALL`, `OP_CALL`, `GCS_SYNC`, `ENV_VALIDATION`, `RAG_INDEX`, `RAG_RETRIEVE` log markers). Use them when debugging. Full log tail available at `GET /logs` (token-gated).
5. Tests are the contract. **236 unit tests** + 10 synthetic scenarios pin the current behavior. Run with `pytest tests/unit -q`.
6. The `service-account.json` file must exist locally at the repo root before any `--source .` deploy.
7. To test locally: use `ngrok` to tunnel webhooks to a local `uvicorn` instance.
8. To refresh the TestLink knowledge base: `python scripts/fetch_testlink.py` (requires `TESTLINK_API_KEY` in env). This re-fetches all 710 TCs from suite 26691 and regenerates `assets/testlink_cases.json`. Re-deploy or restart to pick up the new embeddings.
