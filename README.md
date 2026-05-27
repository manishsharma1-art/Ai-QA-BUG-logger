# 🤖 QA Bug Logger Bot

AI-powered bug reporting from Google Chat to OpenProject.

**Saves 85%+ time** — What takes 10 minutes manually now takes under 1 minute.

## What It Does

1. QA tester sends a bug report in Google Chat (text + screenshots/videos)
2. **Gemini 2.5 Flash** AI analyzes the content
3. Structured bug ticket created automatically in **OpenProject**
4. Confirmation sent back to the tester with ticket link

## Quick Start

### 1. Prerequisites

- Python 3.11+
- Google Cloud project with Chat API enabled
- Service account JSON file
- Gemini API key
- OpenProject instance

### 2. Setup

```bash
# Clone and navigate to the project
cd QA_BUG_Logger

# Create virtual environment
python -m venv venv
venv\Scripts\activate  # Windows
# source venv/bin/activate  # Linux/Mac

# Install dependencies
pip install -r requirements.txt

# Configure environment
copy .env.example .env
# Edit .env with your actual values
```

### 3. Configure `.env`

```env
GEMINI_API_KEY=your_gemini_api_key
GEMINI_MODEL=gemini-2.5-flash
OPENPROJECT_BASE_URL=https://project.intermesh.net
GOOGLE_SERVICE_ACCOUNT_JSON=service-account.json
DATABASE_URL=sqlite+aiosqlite:///./data/qa_bugbot.db
PORT=8080
```

### 4. Run Locally

```bash
python main.py
# or
uvicorn main:app --host 0.0.0.0 --port 8080 --reload
```

### 5. Deploy to Google Cloud Run

```bash
# Build container
docker build -t qa-bugbot .

# Tag for GCR
docker tag qa-bugbot gcr.io/YOUR_PROJECT_ID/qa-bugbot

# Push to GCR
docker push gcr.io/YOUR_PROJECT_ID/qa-bugbot

# Deploy to Cloud Run
gcloud run deploy qa-bugbot \
  --image gcr.io/YOUR_PROJECT_ID/qa-bugbot \
  --platform managed \
  --region asia-south1 \
  --allow-unauthenticated \
  --set-env-vars GEMINI_API_KEY=your_key,OPENPROJECT_BASE_URL=https://project.intermesh.net
```

## Project Structure

```
QA_BUG_Logger/
├── main.py                  # FastAPI app, webhook, commands
├── config.py                # Configuration & field mappings
├── models.py                # Pydantic data models
├── database.py              # SQLite database (user registration)
├── gemini_client.py         # Gemini 2.5 Flash AI integration
├── openproject_client.py    # OpenProject REST API client
├── google_chat_client.py    # Google Chat API integration
├── requirements.txt         # Python dependencies
├── Dockerfile               # Container configuration
├── .env.example             # Environment variable template
├── .gitignore               # Git ignore rules
├── README.md                # This file
├── USER_GUIDE.md            # User documentation
└── DEPLOYMENT.md            # Deployment guide
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/register` | POST | User registration (REST) |
| `/webhook` | POST | Google Chat webhook |

## Chat Commands

| Command | Description |
|---------|-------------|
| `/register <api_key>` | Register with OpenProject |
| `/status` | Check registration status |
| `/help` | Show help message |

## OpenProject Field Mapping

| Field | Source | Filled By |
|-------|--------|-----------|
| Subject (title) | AI extracted | ✅ Bot |
| Description | AI formatted (markdown) | ✅ Bot |
| Steps to Reproduce (customField4) | AI extracted | ✅ Bot |
| Bug Type (customField6) | AI classified | ✅ Bot |
| Environment (customField9) | AI detected | ✅ Bot |
| Type | Always "Product Bug" (7) | ✅ Bot |
| Project | AI detected (android/iosnative) | ✅ Bot |
| Priority | AI classified (High/Med/Low) | ✅ Bot |
| Category | — | 👤 QA manually |
| Assignee | — | 👤 QA manually |
| Accountable | — | 👤 QA manually |
| Version | — | 👤 QA manually |

## Pre-commit hook (secret scanning)

Before your first commit on this repo, install the pre-commit hook that scans
staged `.env*` files for token-like values:

```bash
bash scripts/install-hooks.sh
```

That script copies `scripts/hooks/pre-commit` (committed) into
`.git/hooks/pre-commit` (gitignored) and marks it executable. If you prefer a
symlink, the equivalent one-liner is:

```bash
ln -sf ../../scripts/hooks/pre-commit .git/hooks/pre-commit && chmod +x .git/hooks/pre-commit
```

The hook rejects any staged `.env*` file containing a token-like prefix
(`sk-`, `pk-`, `api-`, `key-`, `token-` followed by 16+ alphanumeric chars)
unless the line matches a known placeholder pattern (`REPLACE_WITH_*`,
`<single-line-token>`, `<space-id>`, or other angle-bracketed placeholders).
On a clean staging area the hook is silent and exits 0; on a match it prints
the offending file and line and aborts the commit.

To bypass in an emergency (not recommended): `git commit --no-verify`.

## License

Internal use — IndiaMART InterMESH Ltd.
