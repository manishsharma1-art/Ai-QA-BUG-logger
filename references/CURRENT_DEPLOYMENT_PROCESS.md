# 📋 Current Deployment Process Analysis

## Deployment Information

### Current Service Details
- **Service Name:** `qa-bugbot`
- **Region:** `asia-south1`
- **Project ID:** `artful-affinity-634`
- **Service Account:** `qaautomation@artful-affinity-634.iam.gserviceaccount.com`
- **Current URL:** `https://qa-bugbot-542857204182.asia-south1.run.app`
- **Alternative URL:** `https://qa-bugbot-mh76wysxxa-el.a.run.app`

### Current Configuration
```yaml
Resources:
  CPU: 1000m (1 vCPU)
  Memory: 512Mi
  Timeout: 300 seconds (5 minutes)
  
Scaling:
  Min Instances: 1
  Max Instances: 100
  Concurrency: 80
  
Container:
  Port: 8080
  Image: asia-south1-docker.pkg.dev/artful-affinity-634/cloud-run-source-deploy/qa-bugbot
  
Environment Variables:
  - LLM_API_KEY: sk-KNy4qPAxAw0OEvgZuNyOeA
  - LLM_BASE_URL: https://imllm.intermesh.net/v1
  - LLM_MODEL: google/gemini-2.5-flash
  - OPENPROJECT_BASE_URL: https://project.intermesh.net
  - GOOGLE_SERVICE_ACCOUNT_JSON: service-account.json
```

### Recent Deployment History
```
Revision 10 (ACTIVE): 2026-05-13 07:15:44 UTC
Revision 09:          2026-05-13 07:00:43 UTC
Revision 08:          2026-05-13 06:50:49 UTC
Revision 07:          2026-05-13 06:26:12 UTC
Revision 06:          2026-05-13 05:51:50 UTC
```

**Note:** Multiple deployments today (5 revisions in ~2 hours) suggests active development/debugging.

---

## Deployment Method Analysis

### Method Used: Cloud Build from Source

Based on the service metadata, the current deployment uses **Cloud Build from source** (not Docker):

```yaml
annotations:
  run.googleapis.com/build-enable-automatic-updates: 'false'
  run.googleapis.com/build-id: 2e574cc9-6d3e-4d09-b6a8-17b459d67e69
  run.googleapis.com/build-source-location: gs://run-sources-artful-affinity-634-asia-south1/services/qa-bugbot/...
```

This means deployments are done using:
```bash
gcloud run deploy qa-bugbot --source .
```

**NOT** using Docker build/push/deploy workflow.

---

## Deployment Workflow (Current)

### Step 1: Prepare Code
```bash
# Navigate to project directory
cd C:\Users\Imart\Documents\QA_BUG_Logger

# Ensure .env file has correct values
# Ensure service-account.json exists
```

### Step 2: Deploy from Source
```bash
gcloud run deploy qa-bugbot \
  --source . \
  --region asia-south1 \
  --platform managed \
  --allow-unauthenticated \
  --memory 512Mi \
  --cpu 1 \
  --min-instances 1 \
  --max-instances 100 \
  --timeout 300 \
  --no-cpu-throttling \
  --set-env-vars "LLM_API_KEY=sk-KNy4qPAxAw0OEvgZuNyOeA" \
  --set-env-vars "LLM_BASE_URL=https://imllm.intermesh.net/v1" \
  --set-env-vars "LLM_MODEL=google/gemini-2.5-flash" \
  --set-env-vars "OPENPROJECT_BASE_URL=https://project.intermesh.net" \
  --set-env-vars "GOOGLE_SERVICE_ACCOUNT_JSON=service-account.json"
```

### What Happens:
1. **gcloud** uploads source code to Cloud Storage
2. **Cloud Build** automatically builds Docker image from Dockerfile
3. **Cloud Build** pushes image to Artifact Registry
4. **Cloud Run** deploys the new image
5. **Traffic** switches to new revision

---

## Key Files for Deployment

### Required Files
1. ✅ `Dockerfile` - Container build instructions
2. ✅ `.dockerignore` - Files to exclude from build
3. ✅ `requirements.txt` - Python dependencies
4. ✅ `service-account.json` - Google Chat API credentials
5. ✅ `.env` - Environment variables (local only)

### Deployment Scripts (Available but NOT currently used)
1. `deploy_fixes.sh` - Linux/Mac deployment script (Docker-based)
2. `deploy_fixes.bat` - Windows deployment script (Docker-based)

**Note:** These scripts use Docker build/push workflow, which is different from the current source-based deployment.

---

## Environment Variables

### Set via gcloud command:
```bash
LLM_API_KEY=sk-KNy4qPAxAw0OEvgZuNyOeA
LLM_BASE_URL=https://imllm.intermesh.net/v1
LLM_MODEL=google/gemini-2.5-flash
OPENPROJECT_BASE_URL=https://project.intermesh.net
GOOGLE_SERVICE_ACCOUNT_JSON=service-account.json
```

### NOT set (uses defaults from config.py):
- `DATABASE_URL` - Defaults to `sqlite+aiosqlite:///./data/qa_bugbot.db`
- `PORT` - Defaults to `8080`

---

## Service Account & Permissions

### Service Account
- **Email:** `qaautomation@artful-affinity-634.iam.gserviceaccount.com`
- **File:** `service-account.json` (in project root)

### Required Permissions
- Google Chat API access (for sending messages, downloading attachments)
- Cloud Run deployment permissions
- Cloud Build permissions

---

## Monitoring & Logs

### View Logs
```bash
# Recent logs
gcloud run services logs read qa-bugbot --region asia-south1 --limit 50

# Stream logs
gcloud run services logs tail qa-bugbot --region asia-south1

# Filter by severity
gcloud run services logs read qa-bugbot --region asia-south1 --log-filter="severity>=ERROR"
```

### Health Check
```bash
curl https://qa-bugbot-542857204182.asia-south1.run.app/health
```

---

## Differences: Documentation vs Reality

### Documentation Says (DEPLOYMENT.md):
```bash
# Build Docker image locally
docker build -t qa-bugbot .
docker tag qa-bugbot gcr.io/PROJECT_ID/qa-bugbot:latest
docker push gcr.io/PROJECT_ID/qa-bugbot:latest
gcloud run deploy qa-bugbot --image gcr.io/PROJECT_ID/qa-bugbot:latest
```

### Reality (Current Practice):
```bash
# Deploy from source (no local Docker build)
gcloud run deploy qa-bugbot --source .
```

**Why the difference?**
- Source-based deployment is simpler (no Docker installation needed)
- Cloud Build handles everything automatically
- Faster iteration during development
- No need to manage Docker images locally

---

## Deployment Best Practices (Current Setup)

### ✅ Advantages
1. **Simple:** Single command deployment
2. **Fast:** No local Docker build time
3. **Consistent:** Cloud Build ensures reproducible builds
4. **Automatic:** Image management handled by Google

### ⚠️ Considerations
1. **Build time:** Cloud Build takes 2-3 minutes
2. **Cost:** Cloud Build charges apply (minimal for this project)
3. **Dependencies:** Requires gcloud CLI configured
4. **Source upload:** Entire directory uploaded (respects .dockerignore)

---

## Recommended Deployment Command (For Fixes)

```bash
# From project root directory
gcloud run deploy qa-bugbot \
  --source . \
  --region asia-south1 \
  --platform managed \
  --allow-unauthenticated \
  --memory 512Mi \
  --cpu 1 \
  --min-instances 1 \
  --max-instances 100 \
  --timeout 300 \
  --no-cpu-throttling \
  --set-env-vars "LLM_API_KEY=sk-KNy4qPAxAw0OEvgZuNyOeA,LLM_BASE_URL=https://imllm.intermesh.net/v1,LLM_MODEL=google/gemini-2.5-flash,OPENPROJECT_BASE_URL=https://project.intermesh.net,GOOGLE_SERVICE_ACCOUNT_JSON=service-account.json"
```

**Or use the simplified version (keeps existing env vars):**
```bash
gcloud run deploy qa-bugbot \
  --source . \
  --region asia-south1 \
  --no-cpu-throttling
```

---

## Rollback Procedure

If the new deployment has issues:

```bash
# List recent revisions
gcloud run revisions list --service=qa-bugbot --region=asia-south1

# Rollback to previous revision (e.g., revision 09)
gcloud run services update-traffic qa-bugbot \
  --region asia-south1 \
  --to-revisions=qa-bugbot-00009-g9v=100
```

---

## Pre-Deployment Checklist

Before deploying the timeout fixes:

- [x] Code changes tested locally
- [x] LLM API key verified working
- [x] No syntax errors in Python files
- [x] service-account.json exists
- [x] .env file configured (for local testing)
- [x] Dockerfile unchanged (uses existing working version)
- [x] requirements.txt unchanged (no new dependencies)
- [ ] Backup current revision number: `qa-bugbot-00010-kzb`
- [ ] Notify QA team of deployment window
- [ ] Monitor logs after deployment

---

## Post-Deployment Verification

After deployment:

1. **Check health endpoint:**
   ```bash
   curl https://qa-bugbot-542857204182.asia-south1.run.app/health
   ```

2. **Test with simple bug report:**
   - Send text-only bug in Google Chat
   - Verify response within 10-15 seconds
   - Check OpenProject ticket created

3. **Monitor logs for errors:**
   ```bash
   gcloud run services logs tail qa-bugbot --region asia-south1
   ```

4. **Check processing times:**
   - Look for "Bug processed in X.Xs" messages
   - Should be <30s for text+images
   - Should be <60s for short videos

---

## Summary

### Current Deployment Method
✅ **Source-based deployment** using `gcloud run deploy --source .`

### NOT Using
❌ Docker build/push workflow (despite documentation)

### To Deploy Timeout Fixes
```bash
gcloud run deploy qa-bugbot --source . --region asia-south1 --no-cpu-throttling
```

### Estimated Deployment Time
- Upload source: ~30 seconds
- Cloud Build: ~2-3 minutes
- Deploy to Cloud Run: ~30 seconds
- **Total: ~3-4 minutes**

### Risk Level
🟢 **Low Risk**
- Can rollback instantly to previous revision
- No breaking changes in code
- Only optimization improvements
- Same dependencies

---

**Ready to deploy when you confirm!**
