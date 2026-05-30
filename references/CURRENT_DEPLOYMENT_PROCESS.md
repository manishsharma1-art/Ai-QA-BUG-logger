# 📋 Current Deployment Process

> _Updated 2026-05-30 after the v3 reliability deploy went live. The canonical deploy reference._

---

## Service Details (live)

| | Value |
|---|---|
| **Service Name** | `qa-bugbot` |
| **Region** | `asia-south1` |
| **Project ID** | `artful-affinity-634` |
| **Service Account** | `qaautomation@artful-affinity-634.iam.gserviceaccount.com` |
| **Live URL** | `https://qa-bugbot-542857204182.asia-south1.run.app` |
| **Internal alias URL** | `https://qa-bugbot-mh76wysxxa-el.a.run.app` |
| **Current Revision** | `qa-bugbot-00042-8zj` (100% traffic) |
| **Stable git checkpoint** | `checkpoint-stable-20260530` → commit `5002f50` |

The OLD `https://qa-bug-bot-542857204182.us-central1.run.app/...` URL is a dead deployment in a different region. Don't probe it.

---

## Production Configuration

```yaml
Resources:
  CPU:          1 (1000m)
  Memory:       1Gi              # was 512Mi; bumped for OpenCV video processing
  Timeout:      300s
  CPU throttling: false           # MANDATORY — Phase 2 background tasks die without this
  CPU boost:    true              # for fast cold starts

Scaling:
  Min instances: 1               # avoids cold-start hits during demos
  Max instances: 100
  Concurrency:   80

Container:
  Port:  8080
  Image: asia-south1-docker.pkg.dev/artful-affinity-634/cloud-run-source-deploy/qa-bugbot

Environment Variables (set via --update-env-vars on each deploy):
  LLM_API_KEY:                  <gateway token, in .env, NEVER in repo>
  LLM_BASE_URL:                 https://imllm.intermesh.net/v1
  LLM_MODEL:                    google/gemini-2.5-flash
  OPENPROJECT_BASE_URL:         https://project.intermesh.net
  GOOGLE_SERVICE_ACCOUNT_JSON:  service-account.json
  DATABASE_URL:                 sqlite+aiosqlite:///./data/qa_bugbot.db
  PORT:                         8080
  DEFAULT_OPENPROJECT_API_KEY:  <demo space fallback key, NEVER in repo>
  DEMO_SPACE_ID:                <Google Chat space ID, NEVER in repo>
  BUILD_MARKER:                 <git short sha — set per deploy>
```

**Critical:** `--update-env-vars` value MUST be **comma-separated**, not space-separated. The space-separator concatenates `DEMO_SPACE_ID=...` into the API key value (this was RC2 in the production-reliability spec).

---

## Deploy Method: Cloud Build from Source

Cloud Run's `--source .` flag runs Cloud Build implicitly. There is NO separate `gcloud builds submit` step in this project's workflow. The Dockerfile in the repo root drives the build.

Service metadata that confirms this:
```yaml
run.googleapis.com/build-source-location:
  gs://run-sources-artful-affinity-634-asia-south1/services/qa-bugbot/...
```

---

## Deploy Workflow (Canonical)

### 1. Pre-deploy checks (local)

```powershell
cd C:\Users\Imart\Documents\QA_BUG_Logger

# Working tree clean
git status --porcelain   # MUST be empty

# Tests green
python -m pytest tests/unit -q                               # expect 190 passed
python scripts/synthetic_webhook.py --scenario all          # expect 9/9 passed

# .env has the right values
# service-account.json exists at repo root (gitignored, but uploaded with --source)
```

### 2. Tag the candidate

```powershell
$today = Get-Date -Format "yyyyMMdd-HHmm"
$next  = "v?"   # next release version
git tag -a "reliability-fix-$next-$today" -m "<release notes>"
git push origin fix/production-reliability "reliability-fix-$next-$today"
```

### 3. Deploy from source

```powershell
$sha = git rev-parse --short HEAD

gcloud run deploy qa-bugbot `
    --source . `
    --region asia-south1 `
    --no-cpu-throttling `
    --memory 1Gi `
    --cpu 1 `
    --timeout 300 `
    --min-instances 1 `
    --max-instances 100 `
    --service-account qaautomation@artful-affinity-634.iam.gserviceaccount.com `
    --update-env-vars "BUILD_MARKER=$sha,DEFAULT_OPENPROJECT_API_KEY=<key>,DEMO_SPACE_ID=<id>"
```

Cloud Build phase takes ~3-5 minutes. The deploy will print the new revision name (e.g. `qa-bugbot-00042-8zj`) in its final line.

### 4. Force traffic flip if needed

A new revision is created with **0% traffic** when traffic was previously pinned to a specific revision. Force it:

```powershell
gcloud run services update-traffic qa-bugbot `
    --region asia-south1 `
    --to-revisions=<new-revision-name>=100
```

### 5. Verify

```powershell
# /health: status=healthy, gemini=ok, last_gcs_sync.outcome=ok
curl https://qa-bugbot-542857204182.asia-south1.run.app/health

# Logs: BUILD_MARKER, ENV_VALIDATION, GCS_SYNC, LLM_CALL all present
gcloud run services logs read qa-bugbot --region asia-south1 --limit 200 |
    Select-String -Pattern "BUILD_MARKER|ENV_VALIDATION|GCS_SYNC|LLM_CALL"
```

Or query `/logs` directly (works without `roles/logging.viewer`):
```powershell
curl https://qa-bugbot-542857204182.asia-south1.run.app/logs
```

### 6. Send the canary bug

In the dev Google Chat space:
```
[LMS Webview] login button broken on iPhone 13
```

Expected reply:
- `Project: LMS Webview` (NOT `ANDROID`)
- `Bug Type: Functional/Logical`
- `Priority: Medium` (95% rule; "broken" alone isn't a crash)
- No `Platform:` line (intentional)
- View URL points at OpenProject ticket
- Processed in ~4-5 seconds

### 7. Mint a stable checkpoint (only if green)

```powershell
git tag -a "checkpoint-stable-$today" -m "<release context>" HEAD
git push origin "checkpoint-stable-$today"
```

---

## Rollback

### Cloud Run traffic flip — fastest, ~30s, no rebuild

```powershell
gcloud run services update-traffic qa-bugbot `
    --region asia-south1 `
    --to-revisions=qa-bugbot-00042-8zj=100
```

This revision (`qa-bugbot-00042-8zj`) is the current stable target. If you've deployed past this and want to revert: pick the most recent revision before the deploy that broke things from `gcloud run revisions list --service qa-bugbot --region asia-south1`.

### Source-code rollback

```powershell
git fetch origin
git checkout fix/production-reliability
git reset --hard checkpoint-stable-20260530
git push --force-with-lease origin fix/production-reliability
```

Then redeploy from `--source .`.

---

## Deploy gotchas (each one cost us a deploy attempt)

1. **`service-account.json` must be in the source upload.** Don't add it to `.gcloudignore` or `.dockerignore`. It's already in `.gitignore`.
2. **`--update-env-vars` requires comma separation.** Spaces concatenate values into the previous key. RC2.
3. **Cloud Run does NOT auto-flip traffic** when traffic was previously pinned. Always run `update-traffic` after `deploy` if you've previously rolled back.
4. **The vendored `gcloud_sdk/` in the repo is broken** (missing Python deps). Use a system gcloud install (`C:\Program Files (x86)\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd`).
5. **Pre-commit hook may reject test files** that contain literal-looking secrets (e.g. `sk-fakefake...`). Construct such strings at runtime in tests.

---

## Image build details

| | Value |
|---|---|
| Base image | `python:3.11-slim` |
| Build steps | `apt install gcc`, `pip install -r requirements.txt`, `COPY . .`, `mkdir /app/data` |
| Build arg | `BUILD_MARKER` (defaults to `unknown` — rolls into `read_build_marker()` cosmetic open issue) |
| Health check | `python -c "import httpx; r = httpx.get('http://localhost:8080/health'); assert r.status_code == 200"` |
| CMD | `uvicorn main:app --host 0.0.0.0 --port 8080` |

---

## Recent deploy history

| Revision | Date | Commit | Outcome |
|---|---|---|---|
| `qa-bugbot-00042-8zj` | 2026-05-30 | `5002f50` | ★ Stable. Few-shot 50, no Platform line, all RC1-RC8 closed. **CURRENT.** |
| `qa-bugbot-00041-r2h` | 2026-05-28 | `c09be99` | Working. Few-shot 5. Became rollback target for v3. |
| `qa-bugbot-00040-wnd` | 2026-05-27 | `157110f` | Failed: `service-account.json` excluded from source. Phase 2 chat replies broke. Rolled back to 00039. |
| `qa-bugbot-00039-dth` | 2026-05-26 | (pre-spec) | Pre-reliability state. Used as rollback target after v1 failed. |
| `qa-bugbot-00038-mrz` | 2026-05-25 | (pre-spec) | Earlier pre-reliability state. |
| `qa-bugbot-00026-btk` | 2026-04-?? | (pre-spec) | Historical "safe checkpoint" cited in old docs. Older than 00039. |

---

## Tag chain (rollback targets, newest → oldest)

```
checkpoint-stable-20260530       → 5002f50  ★ STABLE — matches qa-bugbot-00042-8zj
reliability-fix-v3-20260530-1326 → 5002f50
reliability-fix-v2-20260528-0829 → c09be99
reliability-fix-20260527         → 157110f
checkpoint-pre-deploy-20260527   → 5228bf2
pre-reliability-fix-20260527     → 6cbb855  (original main HEAD)
```
