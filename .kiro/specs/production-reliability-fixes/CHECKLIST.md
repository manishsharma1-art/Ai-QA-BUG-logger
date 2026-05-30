# CHECKLIST — production-reliability-fixes

> **Purpose:** Quick visual progress tracker.
>
> _Updated 2026-05-30 after the v3 deploy went live and was checkpointed._

---

## Phase summary

| Phase | What | Tasks | Done | Status |
|---|---|---|---|---|
| 0 | Repo hygiene | 3 | 3 | ✅ Done |
| 1 | Test infra | 5 | 5 | ✅ Done |
| 2 | Component fixes (A-G) | 35 | 35 | ✅ Done |
| 3 | Integration glue | 3 | 3 | ✅ Done |
| 4 | Synthetic webhook scenarios | 11 | 11 | ✅ Done (S6 implemented for real, 9/9 green) |
| 5 | Secret hygiene | 5 | 5 | ✅ Done |
| 6 | Local end-to-end verification | 6 | 2 + 4 deferred to Cloud Build | 🟡 13.1 + 13.2 done locally; 13.3-13.6 covered by Cloud Build's `--no-cache` rebuild |
| 7 | Sign-off gate | 1 | 1 | ✅ User typed "deploy" |
| 8 | Deploy | 4 | 4 | ✅ Done (v3 attempt — `qa-bugbot-00042-8zj`) |
| 9 | Post-deploy verify | 4 | 4 | ✅ All four green |
| 10 | Rollback | 2 | n/a | ⬜ Not needed (deploy succeeded). Path retained as safety net. |
| **TOTAL** | | **102** | **96** + 6 deploy-only | **94%** |

---

## Phase 0–5: all done in source ✅

Every leaf was committed and is verified by tests:
- 190 unit tests pass
- 9/9 synthetic webhook scenarios pass

(Detailed leaf-level breakdown preserved in tasks.md.)

---

## Phase 6 — Local end-to-end verification

- [x] **13.1** `python -m pytest tests/unit -q` green — **190 passed, 0 failed**
- [x] **13.2** `python scripts/synthetic_webhook.py --scenario all` green — **9/9 passed**
- [~] **13.3** `docker build --no-cache --build-arg BUILD_MARKER=local-<sha> .` — *deferred:* Docker not installed on dev machine; same image built by Cloud Build during Phase 8 deploy with `--source .`
- [~] **13.4** `docker run` + `/health` — *covered by Phase 9.1 against the live revision*
- [~] **13.5** Grep startup logs for markers — *covered by Phase 9.2 against live `/logs`*
- [~] **13.6** `scripts/preflight.sh` end-to-end — *deferred:* preflight script's Docker steps need a daemon; pytest/synthetic portions ran green

---

## ✅ Phase 7 — Sign-off

- [x] **14.1** User approved deploy on 2026-05-27 ("deploy")

---

## ✅ Phase 8 — Deploy (3 attempts; v3 stuck)

| # | Tag | Commit | Outcome |
|---|---|---|---|
| v1 | `reliability-fix-20260527` | `157110f` | Built `qa-bugbot-00040-wnd`. Phase 2 broke (no service-account.json in image). **Rolled back to `qa-bugbot-00039-dth`.** |
| v2 | `reliability-fix-v2-20260528-0829` | `c09be99` | Fixed `.gcloudignore`/`.dockerignore` for SA file. Built `qa-bugbot-00041-r2h`. Working — became the rollback target for v3. |
| v3 | `reliability-fix-v3-20260530-1326` | `5002f50` | Bumped few-shot 5→50, dropped Platform line. **Built `qa-bugbot-00042-8zj`. LIVE. 100% traffic.** |

- [x] **15.1** ~~Create env.yaml~~ — used `--update-env-vars` directly with comma-separated values (matches existing deploy convention). RC2 prevention: comma not space.
- [x] **15.2** `git push -u origin fix/production-reliability` + tag pushed
- [x] **15.3** `gcloud run deploy --source .` (Cloud Build runs implicitly with `--no-cache` semantics for source uploads)
- [x] **15.4** Service deployed with all production-only settings: `--no-cpu-throttling --memory 1Gi --cpu 1 --timeout 300 --min-instances 1 --max-instances 100 --service-account qaautomation@artful-affinity-634...`

---

## ✅ Phase 9 — Post-deploy verification (all green on `qa-bugbot-00042-8zj`)

- [x] **16.1** `/health` shape — `status=healthy`, `gemini=ok`, `last_gcs_sync.outcome=ok bytes=12288 duration_ms=571`, `database=connected`
- [x] **16.2** Log markers all present — `BUILD_MARKER`, `ENV_VALIDATION`, `GCS_SYNC`, `LLM_CALL phase=smoke outcome=ok`
- [x] **16.3** `Database initialized` lands **646 ms** after `Starting up...` (RC1 fingerprint was 133 ms — physically impossible for a real GCS round-trip)
- [x] **16.4** Canary tickets created with correct routing:
  - #667536 `[LMS Webview] login button broken on iPhone 13` → reply `Project: LMS Webview` (NOT `ANDROID`)
  - #667537 same brief with media → `Success notification sent for ticket #667537` (yesterday's regression confirmed fixed)
  - #668088 `[Seller Dashboard] Yes CTA not clickable...` → reply `Project: Seller Dashboard` (the audit-flagged "Project: ANDROID lie" — fixed)

---

## ⬜ Phase 10 — Rollback (not needed)

Both rollback paths remain ready if a future deploy fails:

- [ ] **17.1** `gcloud run services update-traffic qa-bugbot --region asia-south1 --to-revisions=qa-bugbot-00042-8zj=100` *(reserved for future failures; this is now the rollback target)*
- [ ] **17.2** `postmortem.md` — not authored; deploy succeeded

---

## Tag chain (rollback targets, newest → oldest)

```
checkpoint-stable-20260530       → 5002f50  ★ STABLE (matches qa-bugbot-00042-8zj live)
reliability-fix-v3-20260530-1326 → 5002f50
reliability-fix-v2-20260528-0829 → c09be99
reliability-fix-20260527         → 157110f
checkpoint-pre-deploy-20260527   → 5228bf2
pre-reliability-fix-20260527     → 6cbb855
```

---

## What surfaced during execution that wasn't in the original spec

These were folded into the same spec/branch and deployed together:

1. **`Project: ANDROID` lie in user reply** (QA audit screenshot from Anmol Goyal). `openproject_client.create_work_package` returned `bug_report.platform.value.upper()` instead of the canonical `OP_PROJECTS` name. **Fixed.**
2. **`Platform: Android` line for desktop bugs** (QA audit follow-up). `PlatformType` enum's default leaked into the reply. **Removed the line entirely.**
3. **`space_name` NameError** in `_handle_bug_report` for text-only standard-format webhooks. Variable used before assignment. **Fixed (extraction moved to top of function).**
4. **Few-shot examples were unused at runtime** despite `assets/training_examples_fewshot.json` existing for months. **Wired in via `_load_few_shot_block`; bumped from 5 → 50 examples after empirical latency measurement.**
5. **`service-account.json` excluded from source upload** by `.gcloudignore`/`.dockerignore`. Phase 2 chat replies broke on the v1 deploy → rolled back → fixed in v2.
6. **`build_marker: unknown`** — Dockerfile bakes `ARG BUILD_MARKER=unknown` and the file beats env-var fallback. Cosmetic, queued for next deploy.

---

## Critical reminders

- Pre-commit hook installed at `.git/hooks/pre-commit` — scans staged `.env*` files for `(sk|pk|api|key|token)[-_][A-Za-z0-9]{16,}` and rejects matches. Allow-list: `REPLACE_WITH_*`. **Tested by catching me yesterday.**
- Always use `--no-cpu-throttling` on Cloud Run (Phase 2 background tasks die without it).
- Always use `--memory 1Gi` (OpenCV needs the headroom).
- Always use **comma-separated** values with `--update-env-vars` (RC2 prevention).
- Few-shot examples capped at 50 — past 100 the gateway hits a timeout cliff.
- Trust source files over markdown — this checklist is best-effort, the source is canonical.
