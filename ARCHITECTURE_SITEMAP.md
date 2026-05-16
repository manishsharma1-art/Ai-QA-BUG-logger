# QA Bug Logger — Architecture & Site Map

This document serves as the official **Site Map and Technical Blueprint** for the QA Bug Logger project. 

> **🤖 FOR AI AGENTS**: Read this document first to locate the exact file you need to modify. Do not blindly `ls` or `cat` unrelated files to conserve tokens.

---

## 1. Application Entry Points & Routing
The core application flow and web server definition.

*   `main.py`
    *   **Purpose**: The FastAPI application entry point. Handles incoming HTTP webhook requests from Google Chat.
    *   **Key Functions**:
        *   `post_message()`: Parses the incoming Google Chat JSON webhook.
        *   Phase 1 Execution (Inline): Validates user registration and calls the LLM for text parsing.
        *   Phase 2 Execution (Async): Uses `asyncio.create_task` (with garbage collection protection via `_active_background_tasks`) to process media asynchronously.
        *   `/logs`: A custom diagnostic endpoint that dumps the recent memory logs.
    *   **Edit Here If**: You need to change the API routing, the Google Chat JSON response envelope format, or the Phase 1 / Phase 2 task execution logic.

## 2. Artificial Intelligence (LLM) Integration
The brain of the operation where prompts and media extraction live.

*   `gemini_client.py`
    *   **Purpose**: Handles all interactions with the Gemini 2.5 Flash gateway (`imllm.intermesh.net`).
    *   **Key Functions**:
        *   `extract_bug_details()`: Extracts structured data from text (Phase 1). Contains the core **System Prompt** defining how the AI should format "Actual Behavior", "Expected Behavior", and "Steps to Reproduce".
        *   `enrich_with_media()`: Handles Phase 2. Extracts frames from MP4 videos (1 frame/sec, max 30 frames, 480px) and sends them to Gemini for visual analysis.
    *   **Edit Here If**: You need to alter the LLM Prompts, change the few-shot examples, adjust the video frame-rate sampling, or change the LLM endpoint/timeout configurations.

## 3. External API Clients
How the bot communicates with third-party platforms.

*   `openproject_client.py`
    *   **Purpose**: Handles ticket creation and attachment uploads to the company's OpenProject system.
    *   **Key Functions**: 
        *   `create_work_package()`: Maps the LLM's `ExtractedBugReport` into OpenProject's specific JSON payload format.
        *   `attach_file_to_work_package()`: Uses `multipart/form-data` to upload videos/images to the created ticket.
    *   **Edit Here If**: You need to map a new OpenProject field, change how the Markdown description is structured on the ticket, or fix `422` OpenProject API validation errors.

*   `google_auth.py`
    *   **Purpose**: Uses `service-account.json` to authenticate with the Google Chat API.
    *   **Key Functions**: 
        *   `download_attachment()`: Fetches the raw bytes of a video/image sent by the user.
        *   `send_message()`: Sends asynchronous replies back to the Google Chat thread (e.g., the final "Success" message).
    *   **Edit Here If**: The bot fails to download attachments or fails to send async messages.

## 4. Configuration & Data Models
Centralized definitions and constants.

*   `config.py`
    *   **Purpose**: Pydantic settings and OpenProject ID mappings.
    *   **Key Variables**:
        *   `OP_PROJECTS`: Maps string platforms ("Android") to OpenProject Integer IDs (`3`).
        *   `OP_PRIORITIES`, `OP_BUG_TYPES`: Maps UI strings to OpenProject Integer IDs.
    *   **Edit Here If**: You add a new platform (e.g., "Windows App") or OpenProject changes its custom field IDs. If OpenProject rejects a payload with "Project can't be blank", this is where the mapping is broken.

*   `models.py`
    *   **Purpose**: Pydantic definitions for the data exchanged between the LLM and the rest of the application.
    *   **Key Classes**: `ExtractedBugReport` (defines the exact JSON schema the LLM is forced to return).
    *   **Edit Here If**: You want the LLM to extract a new piece of information (e.g., adding an `AppVersion` field or a `BrowserType` enum).

*   `database.py`
    *   **Purpose**: SQLite (`aiosqlite`) management for user mapping.
    *   **Key Functions**: Maps a Google Chat User ID to their specific OpenProject API Key.

## 5. Deployment & Environment Settings
Files controlling the Cloud Run infrastructure.

*   `Dockerfile`: Standard Python 3.11 slim container definition. Exposes `$PORT`.
*   `.gcloudignore`: Controls what files are uploaded to Cloud Run. **Crucial**: It explicitly allows `service-account.json` to upload (overriding `.gitignore`).
*   `.gitignore`: Controls what is tracked by Git. Excludes `.env`, `venv/`, and `service-account.json`.
*   `requirements.txt`: Python package dependencies.

## 6. Official Documentation & Quality Control
Guides for users, maintainers, and LLMs.

*   `AUDIT_CHECKLIST.md`: The official scorecard for QA testers to evaluate the bot's accuracy.
*   `LLM_HANDOVER.md`: A chronological history of major architectural shifts and bugs encountered (vital context for AI agents).
*   `AI_BugLogger_Quality_Audit_Sheet.xlsx`: A generated Excel tracker for QAs to log their test scores.

---
### 🛠️ Quick Action Guide for AI Agents
*   **"I want to change how the ticket looks in OpenProject"** -> Go to `openproject_client.py` -> `_format_description()`.
*   **"The AI is ignoring my text instructions"** -> Go to `gemini_client.py` -> Update the System Prompt.
*   **"We added a new platform called 'Desktop'"** -> Update `models.py` (add to Enum) and `config.py` (map to OpenProject ID).
*   **"The bot isn't responding in Google Chat at all"** -> Check `main.py` -> `post_message()` payload structure.
