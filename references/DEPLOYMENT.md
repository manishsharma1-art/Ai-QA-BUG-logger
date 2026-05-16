# 🚀 QA Bug Logger Bot — Deployment Guide

## Architecture Overview

```
Google Chat → Webhook (POST /webhook) → FastAPI (Cloud Run)
                                             ↓
                                    ┌────────┴────────┐
                                    ↓                 ↓
                              Gemini 2.5 Flash    OpenProject API
                              (AI Analysis)       (Create Ticket)
                                    ↓                 ↓
                                    └────────┬────────┘
                                             ↓
                                    Google Chat API
                                    (Send Result)
```

---

## Option 1: Google Cloud Run (Recommended)

### Prerequisites

- Google Cloud project with billing enabled
- `gcloud` CLI installed and authenticated
- Docker installed
- Chat API enabled in your GCP project

### Step 1: Prepare Service Account

```bash
# Create service account for the bot
gcloud iam service-accounts create qa-bugbot \
  --display-name="QA Bug Logger Bot"

# Grant Chat Bot permissions
# (Also configure in Google Chat API settings in Cloud Console)

# Download the key file
gcloud iam service-accounts keys create service-account.json \
  --iam-account=qa-bugbot@YOUR_PROJECT.iam.gserviceaccount.com
```

### Step 2: Build and Push Docker Image

```bash
# Build the image
docker build -t qa-bugbot .

# Tag for Google Container Registry
docker tag qa-bugbot gcr.io/YOUR_PROJECT_ID/qa-bugbot:latest

# Push to GCR
docker push gcr.io/YOUR_PROJECT_ID/qa-bugbot:latest
```

### Step 3: Deploy to Cloud Run

```bash
gcloud run deploy qa-bugbot \
  --image gcr.io/YOUR_PROJECT_ID/qa-bugbot:latest \
  --platform managed \
  --region asia-south1 \
  --allow-unauthenticated \
  --memory 512Mi \
  --cpu 1 \
  --min-instances 0 \
  --max-instances 10 \
  --timeout 300 \
  --no-cpu-throttling \
  --set-env-vars "GEMINI_API_KEY=your_key" \
  --set-env-vars "OPENPROJECT_BASE_URL=https://project.intermesh.net" \
  --set-env-vars "GEMINI_MODEL=gemini-2.5-flash"
```

### Step 4: Upload Service Account to Cloud Run

```bash
# Create a secret for the service account
gcloud secrets create qa-bugbot-sa --data-file=service-account.json

# Mount the secret in Cloud Run
gcloud run services update qa-bugbot \
  --update-secrets=/app/service-account.json=qa-bugbot-sa:latest
```

### Step 5: Configure Google Chat App

1. Go to [Google Cloud Console → APIs & Services → Google Chat API](https://console.cloud.google.com/apis/api/chat.googleapis.com)
2. Click **Configuration**
3. Set:
   - **App name:** QA Bug Logger
   - **Description:** AI-powered bug reporting bot
   - **App URL:** `https://qa-bugbot-XXXXX-el.a.run.app/webhook`
   - **App features:** Receive 1:1 messages, Join spaces
   - **Connection settings:** HTTP endpoint URL
   - **Visibility:** Everyone in your organization

### Step 6: Verify Deployment

```bash
# Check the health endpoint
curl https://qa-bugbot-XXXXX-el.a.run.app/health
```

Expected response:
```json
{
  "status": "healthy",
  "database": "connected",
  "gemini": "configured",
  "timestamp": "2026-05-11T12:00:00Z"
}
```

---

## Option 2: Local Development

### Setup

```bash
# Create virtual environment
python -m venv venv
venv\Scripts\activate  # Windows

# Install dependencies
pip install -r requirements.txt

# Copy and edit environment file
copy .env.example .env
# Edit .env with your values

# Run the server
python main.py
```

### Expose with ngrok (for webhook testing)

```bash
ngrok http 8080
```

Use the ngrok HTTPS URL as your Google Chat app webhook URL.

---

## Environment Variables Reference

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GEMINI_API_KEY` | ✅ Yes | — | Gemini API key from AI Studio |
| `GEMINI_MODEL` | No | `gemini-2.5-flash` | Gemini model name |
| `OPENPROJECT_BASE_URL` | No | `https://project.intermesh.net` | OpenProject instance URL |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | ✅ Yes | `service-account.json` | Path to service account JSON |
| `DATABASE_URL` | No | `sqlite+aiosqlite:///./data/qa_bugbot.db` | Database connection string |
| `PORT` | No | `8080` | Server port |

---

## Monitoring

### Logs

```bash
# Cloud Run logs
gcloud run services logs read qa-bugbot --limit=50

# Stream logs
gcloud run services logs tail qa-bugbot
```

### Key Log Messages

| Log | Meaning |
|-----|---------|
| `Message from X: ...` | Webhook received a message |
| `Bug report extracted: ...` | AI analysis complete |
| `Ticket created successfully: #XXXX` | OpenProject ticket created |
| `Bug processed in X.Xs` | Full pipeline time |
| `Error processing bug: ...` | Something went wrong |

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Bot doesn't respond | Check Cloud Run logs, verify webhook URL |
| "AI service not configured" | Set `GEMINI_API_KEY` env var |
| Attachment download fails | Check service account permissions for Chat API |
| OpenProject 401 error | User's API key is invalid or expired |
| OpenProject 422 error | Check field IDs in `config.py` |
| Slow response (>10s) | Video processing takes time, this is normal |

---

## Cost Estimation

| Service | Monthly Cost |
|---------|-------------|
| Cloud Run (1M requests) | ~$5 |
| Gemini 2.5 Flash (100K bugs) | ~$15 |
| Total | **~$20/month** |

vs. Manual cost: **~$6,000/month** (15 hours/day × $20/hour × 20 days)

**ROI: 300x return on investment**
