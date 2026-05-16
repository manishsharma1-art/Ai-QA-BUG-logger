# QA Bug Logger Bot - System Context & Handover

This document is designed to provide immediate context for any LLM taking over development of this codebase. It summarizes the architecture, core logic, deployment strategy, and recent fixes to ensure smooth continuation of work.

## 1. System Overview
The **QA Bug Logger Bot** is a Google Chat integration that allows QA testers to report bugs using natural language and media (images/videos). The bot uses a two-phase LLM pipeline to analyze the report, extract structured data, and automatically create detailed tickets in the company's **OpenProject** system.

### Tech Stack
- **Framework**: FastAPI (Python)
- **Deployment**: Google Cloud Run
- **Database**: SQLite (`data/qa_bugbot.db`)
- **LLM**: `google/gemini-2.5-flash` via IndiaMART LLM Gateway
- **Project Tracking**: OpenProject API

---

## 2. Core Architecture & Logic

### Request Handling (`main.py`)
- Google Chat interacts with the bot via HTTP Webhooks using the **Google Workspace Add-on format** (`hostAppDataAction`).
- Webhook responses **must** occur within 30 seconds to avoid a timeout.
- **Two-Phase Processing Strategy**:
  - **Phase 1 (Inline)**: Analyzes the text brief synchronously using the LLM (~5-10s). If no media is attached, the ticket is created immediately.
  - **Phase 2 (Asynchronous)**: If media is attached, the bot replies instantly with the Phase 1 text results and launches an `asyncio.Task` (`_process_media_and_create_ticket`) to download the media, run Phase 2 visual analysis, and create the final ticket.

### AI Integration (`gemini_client.py`)
- Communicates with `imllm.intermesh.net/v1` using the OpenAI Python SDK.
- **Video Processing**: Uses OpenCV (`cv2`) to extract frames from video attachments.
- **Critical Limits**: To prevent LLM Gateway payload timeouts/rejections, video extraction is strictly limited to **1 frame per second, max 30 frames**. Frames are resized to **480px width** and compressed to **50% JPEG quality**.

### Ticket Management (`openproject_client.py`)
- Creates work packages via the OpenProject API.
- Implements exponential backoff retries to handle transient API failures.
- Maps custom fields (Bug Type, Environment, Priority, Platform) defined in `models.py`.

### Authentication & Media (`google_auth.py`)
- Uses `service-account.json` to authenticate with Google APIs.
- Lazy-loads credentials to securely download media attachments from Google Chat without exposing public URLs.

---

## 3. Deployment Configuration

The application is deployed via source to Google Cloud Run.
**Command:**
```bash
gcloud run deploy qa-bugbot \
  --source . \
  --region asia-south1 \
  --no-cpu-throttling \
  --memory 1Gi
```

### Critical Deployment Nuances
- `--no-cpu-throttling`: **Absolutely necessary.** Cloud Run normally scales CPU to zero immediately after an HTTP response. Since the bot uses `asyncio.Task` to process media *after* sending the initial webhook response, disabling CPU throttling ensures the background task actually completes instead of freezing silently.
- `--memory 1Gi`: Required to process up to 30 video frames in memory using OpenCV.

---

## 4. Current State & Recent Fixes (As of May 2026)

1. **Unreliable FastAPI BackgroundTasks**: Cloud Run was silently killing FastAPI `BackgroundTasks`. The code was entirely refactored to use inline Phase 1 processing and `asyncio.create_task` for Phase 2 media enrichment.
2. **Garbage Collection Fix**: Added a global `_active_background_tasks` set in `main.py` to prevent Python's garbage collector from destroying the `asyncio` task silently.
3. **LLM Payload Errors**: Sending 120 frames to the LLM Gateway caused silent failures. This was fixed by downscaling the video extraction to 30 frames max (1fps, 480px, 50% quality).
4. **Auth Issue / Missing Credentials**: Added a `.gcloudignore` file to prevent `gcloud run deploy` from skipping `service-account.json`. (Without this, the bot deployed successfully but couldn't download attachments or send async Chat messages).
5. **OpenProject 422 Errors ("Project can't be blank")**: Updated `OP_PROJECTS` in `config.py` to use OpenProject integer IDs (e.g. `3` for Android, `85` for iOS) instead of string slugs, matching OpenProject v3 API requirements.
6. **Automatic Media Attachments**: Updated `main.py` and `openproject_client.py` to automatically upload the raw Google Chat media directly to the created OpenProject ticket using the `/api/v3/work_packages/{id}/attachments` endpoint via `multipart/form-data`.

## 5. How to Continue Development
If you are an LLM reading this:
1. Familiarize yourself with the two-phase pipeline in `main.py`.
2. Do not attempt to use standard FastAPI `BackgroundTasks` for this Cloud Run deployment.
3. Be highly cautious about increasing payload sizes or LLM timeout settings in `gemini_client.py`.
4. Ensure `service-account.json` is present and NOT blocked by `.dockerignore` or `.gcloudignore`.
5. To test locally, use `ngrok` to tunnel webhook events to a local `uvicorn` instance.
