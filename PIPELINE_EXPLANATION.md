# 🧠 System Architecture & Pipeline Flow
*A Stakeholder & Developer Guide to the QA Bug Logger Bot*

This document breaks down the end-to-end technical pipeline of the AI-Powered QA Bug Logger. It explains exactly what happens under the hood from the moment a QA engineer hits "send" to the moment an OpenProject ticket is created.

---

## 🏗️ 1. The High-Level Architecture Stack

Our system is built on a modern, serverless, and AI-first technology stack:

*   **Ingestion:** Google Chat API (Webhooks)
*   **Web Server:** FastAPI (Python 3.11)
*   **Hosting:** Google Cloud Run (Serverless, scales to zero)
*   **Authentication:** Google Workspace Service Account (`service-account.json`)
*   **Media Processing:** OpenCV (`cv2`)
*   **AI Engine:** Gemini 2.5 Flash (via IndiaMART LLM Gateway)
*   **Database:** SQLite (`aiosqlite`) for user mapping
*   **Output / Tracking:** OpenProject v3 REST API

---

## 🔄 2. The Two-Phase Pipeline Flow

The biggest technical challenge we solved was the **Google Chat 30-Second Webhook Timeout**. AI video analysis takes time, but if our server doesn't respond to Google Chat within 30 seconds, the bot crashes. 

To solve this, we architected a **Two-Phase Asynchronous Pipeline** using Python's `asyncio` and custom Google Cloud Run configurations.

### Phase 1: Immediate Validation & Text Parsing (Synchronous)
1. **Trigger:** A QA tester sends a message (e.g., *"Cart crashes on iOS"*) and attaches an MP4 video in Google Chat.
2. **Ingestion:** Google Chat fires an HTTP POST webhook to our FastAPI `main.py` endpoint.
3. **Validation:** The system checks if the user is registered in our SQLite database.
4. **Text Analysis:** The text payload is sent to Gemini 2.5 Flash to establish initial context.
5. **Immediate Response:** Within ~5 seconds, the FastAPI server returns a `200 OK` to Google Chat with the message: *"Processing your media asynchronously..."*. 
*Result: We beat the 30-second timeout.*

### Phase 2: Media Enrichment & Ticket Creation (Asynchronous)
*The moment Phase 1 finishes, a detached background task (`_process_media_and_create_ticket`) takes over.*

1. **Secure Download:** `google_auth.py` uses the service account to securely download the raw video file from Google Chat's internal servers.
2. **Intelligent Video Pruning (OpenCV):** 
   * Sending full videos to LLMs causes payload size failures.
   * `gemini_client.py` uses OpenCV to intelligently slice the video.
   * It extracts exactly **1 frame per second** (capped at a maximum of 30 frames).
   * It resizes these frames to 480px width and compresses them to 50% JPEG quality.
3. **Multimodal AI Reasoning:** The compressed frames and the original text are sent back to Gemini 2.5 Flash. The AI visually "watches" the video to deduce the exact steps to reproduce, the operating system, and the severity.
4. **Data Normalization:** The AI's JSON output is mapped to strict corporate IDs (e.g., mapping "iOS" to OpenProject ID `85`).
5. **Ticket Generation:** `openproject_client.py` fires a REST API call to create the Work Package.
6. **Media Attachment:** The original raw video is uploaded to the newly created ticket via a `multipart/form-data` API call.
7. **Final Notification:** The bot sends an asynchronous message back to the Google Chat thread: *"✅ Ticket #1234 Created Successfully."*

---

## 📊 3. Visual Pipeline Flow

You can use this Mermaid diagram in your presentations to explain the flow visually:

```mermaid
graph TD
    A[QA Engineer in Google Chat] -->|Text + Video| B(FastAPI Server / Webhook)
    
    subgraph Phase 1: Synchronous Webhook ( < 5 Seconds )
        B --> C{Registered User?}
        C -->|Yes| D[Initial Text Context Parsing]
        D --> E[Reply to Chat: 'Processing...']
    end
    
    subgraph Phase 2: Asynchronous Worker ( 15 - 45 Seconds )
        E --> F[Download Media via Google Auth]
        F --> G[OpenCV Frame Pruning]
        G -->|1fps / Max 30 Frames| H((Gemini 2.5 Flash))
        H -->|JSON: Steps, OS, Priority| I[Map to OpenProject IDs]
        I --> J[REST: Create Work Package]
        J --> K[REST: Attach Raw Video]
    end
    
    K --> L[Async Reply to Chat: 'Success! Link attached']
```

---

## ⚙️ 4. Critical Cloud Infrastructure Details

To make this pipeline work, we had to implement specific infrastructure constraints:

1. **Garbage Collection Immunity:** Standard FastAPI `BackgroundTasks` are silently killed by Python's Garbage Collector. We store our Phase 2 tasks in a global `_active_background_tasks` set to protect them during execution.
2. **Cloud Run CPU Throttling:** By default, Google Cloud Run drops CPU usage to zero the exact millisecond Phase 1 finishes. We deployed with the `--no-cpu-throttling` flag. This allows our Phase 2 background task to actually execute the heavy OpenCV and AI logic while the HTTP connection is already closed.
3. **Memory Provisioning:** Because OpenCV holds image frames in memory, we provisioned the container with `1Gi` of RAM to prevent Out-Of-Memory (OOM) crashes during concurrent bug reports.
