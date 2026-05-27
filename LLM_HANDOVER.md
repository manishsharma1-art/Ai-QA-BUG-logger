# LLM Handover — QA Bug Logger Bot

> **Purpose:** This document is written for any AI/LLM agent that takes over development or maintenance of this codebase. It describes the architecture, every critical design decision, all known pitfalls, and the current state of the system. Read this FIRST before making any changes.

---

## 1. What This System Does

**QA Bug Logger** is a production-deployed Google Chat bot that converts QA tester messages (text + screenshots + screen recordings) into structured OpenProject bug tickets — automatically, in under 30 seconds for text, under 2 minutes for video.

**Deployed at:** `https://qa-bugbot-mh76wysxxa-el.a.run.app`
**Cloud Run project:** `artful-affinity-634`, region `asia-south1`
**Service name:** `qa-bugbot`
**Current Revision:** `qa-bugbot-00038-mrz`
**Deploy command:** `gcloud run deploy qa-bugbot --source . --region asia-south1`
**Safe rollback:** `gcloud run services update-traffic qa-bugbot --region asia-south1 --to-revisions=qa-bugbot-00026-btk=100`

---

## 2. File Map (What Lives Where)

| File | Purpose | Key Functions |
|---|---|---|
| `main.py` | FastAPI app, webhook handler, two-phase pipeline, rejection detection, input validation | `webhook()`, `_handle_bug_report()`, `_process_media_and_create_ticket()`, `_is_rejection_report()` |
| `gemini_client.py` | LLM integration, small system prompt (bug analysis only), video frame extraction, content screening | `analyze_text_brief()`, `enrich_with_media()`, `_extract_video_frames()`, `_clean_json_response()` |
| `bucket_router.py` | **NEW** — Python-based bucket routing. Extracts [Tag] from message, fuzzy matches to project ID. NO LLM involved. | `extract_bucket_from_message()`, `_resolve_tag()`, `_detect_device_platform()` |
| `models.py` | Pydantic models with field validators for all enums. 25 platform types. | `ExtractedBugReport`, `PlatformType`, `BugType`, `PriorityLevel` |
| `openproject_client.py` | OpenProject v3 API: ticket creation (accepts project_id param), file attachment | `create_work_package(bug_report, api_key, project_id)`, `attach_file_to_work_package()` |
| `google_auth.py` | Google service account auth, Chat API message sending, attachment download | `send_message()`, `download_attachment()`, `is_available()` |
| `config.py` | Settings, 34 project mappings (OP_PROJECTS), category mappings (OP_BUCKET_CATEGORIES) | `get_settings()`, `OP_PROJECTS`, `OP_BUG_TYPES`, `OP_ENVIRONMENTS` |
| `database.py` | SQLite + GCS sync for persistent user registration | `get_user_by_chat_id()`, `create_or_update_user()`, `_download_db_from_gcs()`, `_upload_db_to_gcs()` |

---

## 3. Architecture — Two Key Separations

### A. Bucket Routing (Python) vs Bug Analysis (LLM)

**CRITICAL DESIGN DECISION (as of revision 00034+):**

Bucket routing is handled ENTIRELY in Python (`bucket_router.py`). The LLM NEVER decides which project a bug goes to. This was done because:
- The LLM prompt with 25+ bucket rules was too large → caused timeouts and truncated JSON
- Python regex + fuzzy matching is instant, deterministic, and always works
- Adding new projects = 1 line in config.py (no prompt changes)

```
User message: "[Photo Search IM] Irrelevant results for searched image. Chrome, Desktop"
                     │
                     ▼
┌─────────────────────────────────────────────┐
│  bucket_router.py (Python, instant)         │
│  1. Regex extracts [Photo Search IM]        │
│  2. Fuzzy matches → "Photo Search" → ID 461│
│  3. Returns (461, cleaned_text)             │
└─────────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────┐
│  gemini_client.py (LLM, 3-5 seconds)       │
│  Receives ONLY cleaned_text (no [tag])      │
│  Returns: title, steps, bug_type, priority  │
│  Does NOT return platform/bucket            │
└─────────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────┐
│  openproject_client.py                       │
│  create_work_package(report, key, project_id=461)│
│  Uses project_id from bucket_router          │
└─────────────────────────────────────────────┘
```

### B. Two-Phase Pipeline (for Google Chat webhook deadline)

Google Chat webhooks enforce a **30-second response deadline**. Video analysis takes 45–120s.

```
User sends message (text + optional media)
        │
        ▼
┌─────────────────────────────────────────────────────────────┐
│  PHASE 1 — Inline, synchronous (<25s)                       │
│  ├─ Bucket routing (Python, instant)                        │
│  ├─ Input validation (link-only, min-text, media-only)      │
│  ├─ Text analysis via LLM (analyze_text_brief, 3-5s)       │
│  ├─ Rejection detection on Phase 1 result                   │
│  └─ Returns HTTP response to Google Chat within 30s         │
│       ├─ No media → creates ticket inline, returns result   │
│       └─ Has media → returns "Processing..." ack message    │
└──────────────────────────┬──────────────────────────────────┘
                           │ asyncio.create_task (fire-and-forget)
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  PHASE 2 — Async background task (15-210s)                  │
│  ├─ Download media via Google Chat API                      │
│  ├─ OpenCV frame extraction (1fps, 480px, max 20 frames)    │
│  ├─ LLM multimodal analysis with inline content screening   │
│  ├─ 3-layer rejection detection (format + content + final)  │
│  ├─ Placeholder guard (blocks garbage tickets)              │
│  ├─ OpenProject ticket creation (with project_id)           │
│  ├─ File attachment upload (original HD files)              │
│  └─ Success/rejection notification via Chat API             │
└─────────────────────────────────────────────────────────────┘
```

---

## 4. Bucket Routing (`bucket_router.py`)

### How it works:
1. **Regex extract** `[tag]` from message: `re.search(r'\[([^\]]+)\]', text)`
2. **Exact match** against `OP_PROJECTS` keys (case-insensitive)
3. **Alias match** — 100+ aliases covering variations (e.g., "centralized header & footer" → "Desktop Header Footer")
4. **Fuzzy match** — `difflib.get_close_matches()` with 0.6 cutoff (handles typos like "KLMS" → "LMS Webview")
5. **Device detection** (if no tag) — Samsung/IQOO/Realme → Android, iPhone/iPad → iOS
6. **Default** — Android (project ID 3)

### Adding a new project:
1. Add to `OP_PROJECTS` in `config.py`: `"New Project": 123,`
2. Add aliases to `PROJECT_ALIASES` in `bucket_router.py`
3. Deploy. No prompt changes needed.

### Projects supported (34 total):
Android, iOS, LMS Webview, Msite, Desktop Search, Desktop PDP, Desktop Login, Desktop Homepage, Desktop Header Footer, Seller Dashboard, Seller BuyLeads, Desktop FCP, Desktop DIR, Buyer MY.IM, Clients Templates, WhatsApp, WebERP, Payments, Photo Search, MERP, GLAdmin, Contact Center, Desktop Lead Manager, Buyer Messages, Indic IM, Product Approval & AI Audit, BL and Enquiry forms, Google Product Ads, Catalog AI Auditor, Graph Search, PNS, Big Buyer, Tender, IndiaMART Affiliate

---

## 5. LLM System Prompt (Small & Focused)

**File:** `gemini_client.py` → `SYSTEM_PROMPT`
**Size:** ~1500 tokens (was 8000+ before — caused timeouts)
**Purpose:** Bug analysis ONLY. No bucket routing, no platform detection.

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
- `platform` — handled by bucket_router.py
- `category` — disabled for now

**Priority rules (in prompt):**
- 95% should be Medium
- High ONLY for crashes, complete login failure, payment broken, data loss
- Low for pure cosmetic issues

---

## 6. Key Design Decisions & Pitfalls

### NEVER DO:
1. **Never add bucket routing back to the LLM prompt.** It caused timeouts and was unreliable.
2. **Never remove `_active_background_tasks`.** Phase 2 tasks will silently die from GC.
3. **Never deploy without `--no-cpu-throttling`.** Phase 2 will silently die.
4. **Never add retries to Phase 1.** The 25s webhook deadline kills retry attempts mid-execution. Single attempt only.
5. **Never make `platform` field required in ExtractedBugReport.** LLM doesn't return it (it has a default).
6. **Never reduce video frame resolution below 480px.** Text becomes unreadable.
7. **Never remove the placeholder guard.** It prevents garbage tickets when both phases fail.

### WATCH OUT FOR:
1. **`platform` field default:** `ExtractedBugReport.platform` defaults to `PlatformType.ANDROID`. This is ONLY used for internal Pydantic validation — actual project routing uses `bucket_router.py` output.
2. **`cleaned_text` vs `text`:** After bucket routing, `cleaned_text` (tag stripped) goes to LLM. Original `text` is NOT used for analysis.
3. **GCS DB sync:** Uses `google-cloud-storage` library (not gsutil). Logger is `"qa_bugbot.database"` — check `/logs` endpoint for GCS errors.
4. **Phase 2 content screening prompt** is still large (inside `enrich_with_media`). This is acceptable because Phase 2 runs in background with 180s timeout.
5. **Pydantic `ValidationError`:** If LLM returns fields that don't match the model, it throws. The code catches this and uses QA's raw text as fallback (creates ticket with original text rather than failing).

---

## 7. Database Persistence (GCS Sync)

**Problem:** SQLite is inside the container → lost on every deployment.
**Solution:** Sync to/from `gs://qa-bugbot-data/qa_bugbot.db`

**Flow:**
- On startup: `_download_db_from_gcs()` restores registrations
- On registration: `_upload_db_to_gcs()` saves immediately
- On shutdown: `_upload_db_to_gcs()` final sync

**Bucket:** `gs://qa-bugbot-data`
**Service account access:** `qaautomation@artful-affinity-634.iam.gserviceaccount.com` has `roles/storage.objectAdmin`

**Debugging:** Check `/logs` for "Attempting to restore DB from GCS" and "Database restored from GCS (X bytes)" messages.

---

## 8. OpenProject Integration

**API:** OpenProject v3 REST API at `https://project.intermesh.net/api/v3/`
**Auth:** Per-user API keys via Basic auth (`apikey:<key>`)
**Project routing:** `create_work_package(bug_report, api_key, project_id=N)` — project_id comes from bucket_router

### Key fields:
| Field | How Set |
|---|---|
| Project | `project_id` param from bucket_router (numeric ID) |
| Type | Always "Product Bug" (ID 7) |
| Priority | From LLM: High→9, Medium→8, Low→7 |
| Bug Type (customField6) | From LLM: UI/UX→10, Functional→11, etc. |
| Environment (customField9) | From LLM: LIVE→21, STAGE→22 |
| Steps (customField4) | From LLM: numbered list |
| Category | **DISABLED** — was causing 500 errors when LLM returns invalid category names |

---

## 9. Deployment

```bash
gcloud run deploy qa-bugbot --source . --region asia-south1
```

**Config:** min 1 instance, 512Mi memory, 1 CPU, 300s timeout, `--no-cpu-throttling`

**Rollback:**
```bash
gcloud run services update-traffic qa-bugbot --region asia-south1 --to-revisions=REVISION_NAME=100
```

**Safe checkpoint:** `qa-bugbot-00026-btk` (before multi-bucket changes)

---

## 10. Current State (Last Updated: 2026-05-25)

- **Revision:** `qa-bugbot-00038-mrz`
- **Buckets:** 34 projects supported via Python routing
- **LLM prompt:** ~1500 tokens (small, fast, focused on bug analysis)
- **Phase 1 timing:** 3-5s typical (single attempt, 22s timeout)
- **Phase 2 timing:** 20-60s for media
- **Priority bias:** Fixed — 95% Medium (was incorrectly returning High)
- **Bucket routing:** Python-only (no LLM involvement)
- **DB persistence:** GCS sync via google-cloud-storage library
- **Known issue:** GCS sync logging visibility — check "qa_bugbot.database" logger

---

## 11. Quick Reference: Adding a New Project

1. Get the project ID from OpenProject API or URL
2. Add to `config.py` → `OP_PROJECTS`: `"Project Name": ID,`
3. Add aliases to `bucket_router.py` → `PROJECT_ALIASES`
4. Deploy
5. QA can now use `[Project Name]` tag in their messages
