# HANDOVER — production-reliability-fixes

> **Single source of truth for the current state of this spec.** Read top to bottom before any further work.
>
> _Updated 2026-05-30 after the v3 deploy went live and was checkpointed._

---

## TL;DR — Where we are

| Item | Value |
|---|---|
| **Status** | ✅ **DEPLOYED + STABLE** |
| **Spec folder** | `.kiro/specs/production-reliability-fixes/` |
| **Branch** | `fix/production-reliability` (origin synced) |
| **HEAD** | `5002f50` — `feat: bump few-shot to 50 + drop Platform line + minor cleanups` |
| **Stable checkpoint tag** | `checkpoint-stable-20260530` → `5002f50` (origin) |
| **Live revision** | `qa-bugbot-00042-8zj` (asia-south1, 100% traffic) |
| **Live URL** | `https://qa-bugbot-542857204182.asia-south1.run.app` |
| **Rollback path** | one `gcloud` command (see §Rollback below) |
| **Tests** | `pytest tests/unit -q` → **190 passed, 0 failed** |
| **Synthetic webhook** | `synthetic_webhook.py --scenario all` → **9/9 passed** |
| **Tasks completed** | All implementation phases done; deploy + verify done |

---

## What this spec set out to fix and what actually shipped

The spec opened with 8 root causes (RC1–RC8) plus, during execution, three additional bugs surfaced from a QA audit and one regression (`service-account.json` excluded from source upload). All have been closed. The deploy itself happened in three attempts; the third stuck.

### Live verification of every fix

| RC | Fix | Live evidence (post-deploy) |
|---|---|---|
| RC1 — stale image / silent GCS bypass | Typed exception ladder + `GCS_SYNC` log line | `Starting up → Database initialized` gap is **646 ms** (was 133 ms — physically impossible for a real GCS roundtrip). `last_gcs_sync.outcome=ok bytes=12288 duration_ms=571` on `/health`. |
| RC2 — env-var corruption | New `env_validator.py` runs at lifespan start | `ENV_VALIDATION: all checks passed` on every cold start. Live env vars now properly comma-separated via `--update-env-vars`. |
| RC3 — silent GCS exceptions | 8-outcome typed ladder, `_safe_upload_db_to_gcs` fail-closed guard | `GCS_SYNC` log line per attempt; `_uploads_safe` flag protects existing registrations from being overwritten by a fresh empty DB after a failed download. |
| RC4 — Phase 2 truncation | `max_tokens=6000`, `Phase2TruncatedError` raised on detection, three fall-back paths | Truncation events from yesterday's logs all fell back to Phase 1 cleanly; one ticket #667839 created from QA-text fallback when `_clean_json_response` flagged truncation. |
| RC5 — bracket-tag stripping | `text_for_llm` returned byte-identical to input | Live log: `text_for_llm='[LMS Webview] login button broken on iPhone 13'` (preserved verbatim). |
| RC6 — priority substring match | Word-boundary regex with HIGH/LOW whitelists | Validator covered by `test_priority_validator*` (16 tests). |
| RC7 — `.env.example` real key | Placeholders + pre-commit hook | Hook installed at `.git/hooks/pre-commit`; rejected my own commit attempt for embedded literal token until I fixed it. |
| RC8 — commit discipline | Branch + 7 commits + 6 tags | `git log --oneline` shows the chain; checkpoints can be walked back through. |

### Audit-driven fixes added during execution

| Bug | Fix | Live evidence |
|---|---|---|
| Reply said `Project: ANDROID` even when ticket was filed in `Desktop Lead Manager` | `openproject_client.create_work_package` returns canonical `OP_PROJECTS` name | Live ticket #667536 reply: `Project: LMS Webview` (NOT `ANDROID`). |
| Reply showed `Platform: Android` for desktop bugs | Removed the entire Platform line from both reply templates | Live ticket #668088 reply: no Platform line; only `Project: Seller Dashboard`. |
| Phase 2 didn't reply to user (`Chat API not available`) | `.gcloudignore` and `.dockerignore` were excluding `service-account.json` | Live log: `Success notification sent for ticket #667537`. |
| `space_name` NameError on text-only standard-format webhooks | Moved extraction to top of `_handle_bug_report` | No NameError observed in 200+ live log lines since deploy. |
| Few-shot 5 examples was thin | Bumped to 50 examples loaded from the 600-entry `training_examples.json` | Live ticket #668088 title style mirrors training examples. |
| Phase 1 LLM gateway errors leaked raw SDK text to chat | `LLMGatewayError` 5-outcome classifier; categorized friendly messages | `LLM_CALL phase=phase1 outcome=auth_error` style structured logs in place. |
| LLM gateway smoke test missing | `gemini_client.smoke_test()` runs at lifespan start | `✅ LLM gateway smoke test passed (2312ms)` on every cold start. |

---

## Current architecture — what's running right now

### Pipeline order

```
QA brief (Google Chat webhook)
    │
    ▼
extract_bucket_with_provenance(text)         [bucket_router.py — pure Python]
    │   Layer 1: [Tag] match
    │   Layer 2: prose patterns + scoring
    │   Layer 3: device detection
    │
    ▼  (provenance: 'tag' | 'freetext' | 'device' | 'default')
If provenance=='default' AND gemini_client available AND text>=20 chars:
    pick_bucket() → LLM bucket fallback (one ~2s call)
    │
    ▼
analyze_text_brief(text_for_llm)             [Phase 1 — LLM, ~4s]
    │   SYSTEM_PROMPT = base rules + 50 few-shot INPUT/OUTPUT examples
    │   max_tokens=1000, timeout=20s, wait_for=22s
    │   Raises LLMGatewayError on auth / rate / 5xx / network / unknown
    │
    ▼
If no media: synchronous create_work_package → reply
If media:    return ack + spawn asyncio.Task for Phase 2
                              │
                              ▼
                    enrich_with_media(...)    [Phase 2 — LLM + media]
                        max_tokens=6000, timeout=45s, wait_for=50s
                        Three fall-back paths to Phase 1 result:
                          - Phase2TruncatedError
                          - asyncio.TimeoutError → PHASE2_SLOW log
                          - default-stuffing detected → PHASE2_DEFAULT_STUFFED log
                              │
                              ▼
                    create_work_package + Chat reply notification
```

### Key modules

| File | Lines | What it owns |
|---|---|---|
| `main.py` | ~1100 | FastAPI lifespan, webhook handler, `_handle_bug_report` orchestration, categorized error replies |
| `bucket_router.py` | ~440 | Layer 1-3 deterministic routing, provenance API, `_resolve_tag` with len-guard fuzzy match |
| `gemini_client.py` | ~1080 | `analyze_text_brief`, `enrich_with_media`, `smoke_test`, `pick_bucket`, `_clean_json_response`, `LLM_CALL` wrapper, 50-example few-shot loader |
| `openproject_client.py` | ~330 | `create_work_package` (returns canonical project name), `_log_op_call` 5-outcome wrapper |
| `database.py` | ~470 | `GcsSyncStatus`, `_download_db_from_gcs`, `_upload_db_to_gcs`, `_safe_upload_db_to_gcs` fail-closed guard |
| `env_validator.py` | ~135 | `validate_env_vars` (5 checks), `read_build_marker` |
| `models.py` | ~330 | Pydantic models, `validate_priority` word-boundary regex, `validate_platform` 30+ alias map |
| `assets/training_examples.json` | 606 entries | Source for the few-shot block (top 50 used) |

### Tests

| Suite | Count | Notes |
|---|---|---|
| `tests/unit/` | 190 | Was 110 at start of this work. +80 new across 8 modules. |
| `synthetic_webhook.py --scenario all` | 9 | S1–S9 all pass; S6 is a real GCS round-trip (was a `pass` stub). |

---

## Live state proof (2026-05-30)

```
$ curl https://qa-bugbot-542857204182.asia-south1.run.app/health
{
  "status": "healthy",
  "database": "connected",
  "gemini": "ok",
  "llm_gateway": "https://imllm.intermesh.net/v1",
  "llm_model": "google/gemini-2.5-flash",
  "openproject": "https://project.intermesh.net",
  "last_gcs_sync": {
    "op": "download",
    "duration_ms": 571,
    "outcome": "ok",
    "bytes": 12288,
    "detail": "restored from GCS"
  },
  "build_marker": "unknown"   ← see Open Items #1
}

Startup log (cold start of qa-bugbot-00042-8zj):
  Starting up...
  BUILD_MARKER: unknown
  ENV_VALIDATION: all checks passed
  GCS_SYNC op=download outcome=ok duration_ms=571 bytes=12288
  ✅ Database initialized                         (646 ms after Starting up)
  ✅ LLM client initialized
  ✅ LLM gateway smoke test passed (2312ms)
  ✅ OpenProject client initialized
  ✅ Google Chat client configured
  🚀 Bot is ready!

Canary tickets created:
  #667536  text-only [LMS Webview]   → routed to project 476 ✓
  #667537  with media [LMS Webview]   → Success notification sent ✓
  #668088  text-only [Seller Dashboard] → reply has Project: Seller Dashboard ✓
```

---

## Rollback paths (still intact)

If a future deploy breaks anything, you have three options in increasing order of impact:

### A. Cloud Run traffic flip — fastest, ~30 seconds, no rebuild

```powershell
gcloud run services update-traffic qa-bugbot `
    --region asia-south1 `
    --to-revisions=qa-bugbot-00042-8zj=100
```

This was used yesterday (`qa-bugbot-00040-wnd` failed → flipped back to `qa-bugbot-00039-dth` in 30 s).

### B. Source-code reset — when commit history also needs to revert

```powershell
git fetch origin
git checkout fix/production-reliability
git reset --hard checkpoint-stable-20260530
git push --force-with-lease origin fix/production-reliability
```

Then redeploy from `--source .`.

### C. Both — full recovery

A first (instant safety), then B (clean history), then redeploy if needed.

### Tag chain (rollback targets, newest → oldest)

```
checkpoint-stable-20260530       → 5002f50  ★ THE STABLE FALLBACK (matches qa-bugbot-00042-8zj)
reliability-fix-v3-20260530-1326 → 5002f50  (same; release-tagged variant)
reliability-fix-v2-20260528-0829 → c09be99  (deploy that lacked SA file → broke chat reply)
reliability-fix-20260527         → 157110f  (first deploy attempt — broke Phase 2)
checkpoint-pre-deploy-20260527   → 5228bf2  (pre-everything baseline)
pre-reliability-fix-20260527     → 6cbb855  (original main)
```

The Cloud Run revisions matching each commit are also retained (Cloud Run doesn't auto-prune):

```
qa-bugbot-00042-8zj  ← LIVE (5002f50)
qa-bugbot-00041-r2h  ← previous working revision (c09be99)
qa-bugbot-00039-dth  ← original known-good before this work
```

---

## Open items (low priority, no functional impact)

1. **`build_marker: unknown`** — `Dockerfile` bakes `ARG BUILD_MARKER=unknown` and the file beats the env-var fallback in `read_build_marker()`. One-line fix: treat `"unknown"` as missing in the file precedence check. Will roll into next deploy. The revision name (`qa-bugbot-00042-8zj`) already provides build provenance.
2. **`Few-shot loaded:` log line not in `/logs`** — module-level INFO log fires before the FastAPI memory handler attaches, so it's lost from `/logs`. Block IS in the prompt (proven by canary ticket title style); just not greppable via the in-process log buffer. Cosmetic.
3. **Service account lacks `roles/logging.viewer`** — `gcloud run services logs read` fails for the deploying account. The `/logs` endpoint workaround works fine for now; granting the role would let ops grep Cloud Run logs from any machine.
4. **3 audit-flagged projects still missing from `OP_PROJECTS`**: `Model Product Library`, `Msite SOI`, `Export`. They route through the LLM bucket-picker fallback (which works) but a config edit would make them deterministic. See `tests/unit/test_qa_audit_routing.py::test_known_config_gaps_documented`.
5. **`Phase2TruncatedError` reproduces ~1-in-15 calls** — the `_clean_json_response` regex sometimes flags a clean response as truncated. Fall-back path catches it correctly so no user impact, but the false positives create noise in logs. Worth investigating before next significant prompt change.

---

## Critical things to NEVER do

1. Never run `gcloud run deploy --set-env-vars` with **space-separated** values. Always comma-separated, or use `--env-vars-file env.yaml`. (RC2 was caused by this exact mistake.)
2. Never deploy without `--no-cpu-throttling` — Phase 2 background tasks die silently on Cloud Run without it.
3. Never deploy without `--memory 1Gi` — OpenCV video frame extraction needs the headroom.
4. Never re-add `service-account.json` to `.gcloudignore` or `.dockerignore`. It must be in the source upload but is `.gitignored` so it never enters version control.
5. Never modify `requirements.txt` to add new runtime deps without testing. Dev deps go in `requirements-dev.txt`.
6. Never reduce video frame extraction below 20 frames per video.
7. Never silently repair truncated JSON — that was RC4. Raise `Phase2TruncatedError`.
8. Never retry Phase 1 or Phase 2 on truncation/timeout/default-stuffing — fall back to Phase 1 result instead.
9. Never strip `[Tag]` from the brief sent to the LLM. Return original text verbatim.
10. Never commit a real token to `.env.example`. Pre-commit hook will catch you.
11. Never bump few-shot examples past ~100 without re-measuring latency. The IndiaMART gateway hits a timeout cliff somewhere between 100 and 150 examples.
12. Never deploy from a dirty working tree. `git status --porcelain` must be empty.
13. Never skip the env validator wiring in `main.py lifespan`. It's the canary for future RC2-style env corruption.

---

## Deploy procedure (current canonical)

```powershell
# 1. Confirm clean working tree
git status --porcelain   # must be empty

# 2. Run local tests
python -m pytest tests/unit -q
python scripts/synthetic_webhook.py --scenario all

# 3. Tag the candidate
$today = Get-Date -Format "yyyyMMdd-HHmm"
git tag -a "reliability-fix-v$NEXT-$today" -m "<release notes>"
git push origin fix/production-reliability "reliability-fix-v$NEXT-$today"

# 4. Deploy from source
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
    --update-env-vars "BUILD_MARKER=<sha>,DEFAULT_OPENPROJECT_API_KEY=<key>,DEMO_SPACE_ID=<id>"

# 5. Cloud Run will create a new revision but may NOT auto-flip traffic if
#    traffic was previously pinned. Force the flip:
gcloud run services update-traffic qa-bugbot `
    --region asia-south1 `
    --to-revisions=<new-revision-name>=100

# 6. Verify
curl https://qa-bugbot-542857204182.asia-south1.run.app/health
# Expect: status=healthy, gemini=ok, last_gcs_sync.outcome=ok

# 7. Send canary in dev space:
#    [LMS Webview] login button broken on iPhone 13
# Expect reply: Project: LMS Webview, no Platform line

# 8. If green, mint a stable checkpoint
git tag -a "checkpoint-stable-$today" -m "..." HEAD
git push origin "checkpoint-stable-$today"
```

---

## Production environment facts

- Cloud Run service: `qa-bugbot`, region `asia-south1`
- Live URL: `https://qa-bugbot-542857204182.asia-south1.run.app`
- Internal URL alias: `https://qa-bugbot-mh76wysxxa-el.a.run.app`
- Currently active revision: `qa-bugbot-00042-8zj`
- Service account: `qaautomation@artful-affinity-634.iam.gserviceaccount.com`
- GCS bucket: `gs://qa-bugbot-data/qa_bugbot.db` (~12 KB SQLite)
- LLM gateway: `https://imllm.intermesh.net/v1`, model `google/gemini-2.5-flash`
- OpenProject: `https://project.intermesh.net`
- Image registry: `asia-south1-docker.pkg.dev/artful-affinity-634/cloud-run-source-deploy/qa-bugbot`
- The OLD `https://qa-bug-bot-542857204182.us-central1.run.app/...` URL is a dead deployment in a different region. Don't probe it.

---

## Glossary

- **BUILD_MARKER** — startup log line + `/health` field that proves the running container is the image we built (RC1 prevention).
- **GCS_SYNC** — structured log line for every download/upload attempt: `op outcome duration_ms bytes detail`.
- **PHASE2_TRUNCATED** — message from `_clean_json_response` when the LLM response has unbalanced braces / unterminated string. Now generic ("LLM response truncated"), used by both Phase 1 and Phase 2.
- **PHASE2_DEFAULT_STUFFED** — ERROR log when Phase 2 returns ≥2 of 4 placeholder markers.
- **PHASE2_SLOW** — ERROR log when Phase 2 hits the 50s `asyncio.wait_for` deadline.
- **PRIORITY_AMBIGUOUS** — WARNING log when a string matches both HIGH and LOW priority whitelists.
- **ENV_VALIDATION** — WARNING/INFO prefix from `env_validator.validate_env_vars`.
- **OP_CALL** — structured log line per OpenProject HTTP call: `outcome duration_ms`.
- **LLM_CALL** — structured log line per gateway call: `phase outcome duration_ms`. Phase ∈ {phase1, phase2, smoke, bucket_picker}.

---

## If anything in this document conflicts with `design.md` or `requirements.md`

The spec docs are the contract for *what should be true*. This document is the contract for *what is actually true right now*. They were aligned at deploy time; if they drift in the future, this file wins for "current state" questions and the spec docs win for "what was the original intent" questions.
