# HANDOVER — production-reliability-fixes

> **Single source of truth for the current state of the work.** Read top to bottom before doing anything.
>
> _Updated by orchestration audit, after the prior LLM completed Phases 2–5._

---

## TL;DR — Where we are

| Item | Value |
|---|---|
| **Spec folder** | `.kiro/specs/production-reliability-fixes/` |
| **Branch** | `fix/production-reliability` |
| **HEAD** | `5228bf2` — `fix: restrict pytest to tests/ dir in preflight` (uncommitted: a `space_name`-NameError fix in `main.py` and a new `test_precommit_hook.py`) |
| **Rollback tag** | `pre-reliability-fix-20260527` → `6cbb855` (original `main`) |
| **Tasks completed** | **74 of 102** (Phases 0–5 fully; Phase 6 partially) |
| **Tasks remaining (local)** | **4** (13.3–13.6 — Docker-dependent) |
| **Tasks remaining (deploy)** | **9** (Phases 8–10, gated behind Phase 7 sign-off) |
| **Tests** | `pytest tests/unit -q` → **112 passed, 0 failed** |
| **Synthetic webhook** | `synthetic_webhook.py --scenario all` → **9/9 passed** |
| **Production revision** | `qa-bugbot-00039-dth` (asia-south1) — UNCHANGED |
| **Sign-off gate** | Phase 7 / task 14.1 — **HARD STOP** before any deploy |

---

## What changed since the last handover snapshot

The previous HANDOVER.md was a snapshot from before commit `06de0e6` (`fix: production reliability — Phases 2-5 complete`). It claimed only 10 of 102 leaves were done. That was wrong by the time the document was committed — that same commit shipped:

- `bucket_router.py` (+199 LOC: `BUCKET_TAG_RE`, `_extract_bucket_from_freetext`, `CROSS_KEYWORD_SINGLE_WORDS`, 3-layer flow)
- `models.py` (+106 LOC: `_HIGH_PRIORITY_RE`, `_LOW_PRIORITY_RE`, `validate_priority` rewrite, docstring)
- `database.py` (+275 LOC: `GcsSyncStatus`, `get_last_gcs_sync`, typed exception ladders for download + upload)
- `gemini_client.py` (+452 LOC: `PHASE2_PROMPT_TEMPLATE`, `Phase2TruncatedError`, `JsonCleanResult`, `_detect_default_stuffing`, `DEFAULT_STUFFING_MARKERS`, rewritten `enrich_with_media`)
- `env_validator.py` NEW (+135 LOC: `validate_env_vars`, `read_build_marker`)
- `openproject_client.py` (+118 LOC: `_log_op_call` wrapper)
- `Dockerfile` (+10 LOC: `ARG BUILD_MARKER` + `RUN echo > /app/BUILD_MARKER`)
- `tests/unit/` — 12 test modules covering all 7 components (now 112 tests)

Subsequent commits (`4149139`, `5228bf2`) tightened the preflight scripts.

This audit reconciled `tasks.md` against actual source state and refreshed both `HANDOVER.md` and `CHECKLIST.md`.

---

## What this audit also did

1. **Fixed a real bug in `main.py`** — `_handle_bug_report` referenced `space_name` before assignment in the standard Google Chat path. Any text-only bug report in that path would NameError. The fix moves the `message` / `space_name` / `thread_name` / `attachments` extraction to the top of the function. Verified with full regression: 112/112 pytest, 9/9 synthetic webhook scenarios.
2. **Wrote task 12.5** — `tests/unit/test_precommit_hook.py`, 2 tests using a throwaway git repo + Git Bash to verify the hook rejects `sk-fakefakefakefakefakefakeFAKE` and accepts `sk-REPLACE_WITH_…`.
3. **Reconciled `tasks.md`** — every `[~]` and `[-]` non-standard marker is gone. Each leaf is now `[x]` (done in source) or `[ ]` (genuinely open).
4. **Rewrote `CHECKLIST.md`** to reflect the real 74/102 = 72.5% completion.

---

## What's actually open

### Genuinely open *local* work

Four leaves, all blocked on a Docker daemon:

- **13.3** `docker build --no-cache --build-arg BUILD_MARKER=local-<sha> .`
- **13.4** `docker run` + `curl /health` returns `status=healthy`, `build_marker` non-null, `last_gcs_sync` populated
- **13.5** Grep container startup logs for `BUILD_MARKER`, `ENV_VALIDATION`, `GCS_SYNC` markers
- **13.6** `scripts/preflight.sh` / `.bat` end-to-end green (depends on 13.3–13.5)

> **Why blocked:** `docker --version` returns "command not found" on this dev machine. Two ways to clear them:
> 1. Install Docker Desktop, then run them locally.
> 2. Skip directly to Phase 8 — `gcloud builds submit --no-cache --substitutions=_BUILD_MARKER=<sha>` performs the equivalent build in Cloud Build, and Phase 9 (`/health` + log grep) covers the same observable invariants against the real revision.

### Phase 7 — sign-off gate

- **14.1** Present local test summary; STOP. Wait for the user to type "deploy".

### Deploy-only (Phases 8–10)

9 leaves total — strictly gated behind 14.1.

---

## Local verification snapshot (as of this revision)

```
$ git branch --show-current
fix/production-reliability

$ git log --oneline -3
5228bf2 fix: restrict pytest to tests/ dir in preflight
4149139 fix: use explicit python path in preflight
06de0e6 fix: production reliability - Phases 2-5 complete

$ git status --porcelain
 M main.py                                    (space_name NameError fix)
?? tests/unit/test_precommit_hook.py           (task 12.5 — 2 tests, both pass)

$ python -m pytest tests/unit -q
112 passed, 12 warnings in ~6 s

$ python scripts/synthetic_webhook.py --scenario all
[synthetic] summary: 9/9 passed, 0 failed
```

All Phase 1–5 invariants are exercised by tests and pass. Phase 6 partial, Phase 7 awaiting user.

---

## EXACT next steps for the operator

1. **Review the bug fix and the new test**:
   - `main.py` diff (one chunk in `_handle_bug_report`).
   - `tests/unit/test_precommit_hook.py` (new file).
2. **Decide on the Phase 6 Docker steps**:
   - Either run them locally with Docker Desktop, OR
   - Accept that Cloud Build covers them at Phase 8 and skip ahead.
3. **Phase 7 sign-off**: type "deploy" if local verification is acceptable, else iterate.
4. After "deploy":
   - 15.1 Build `env.yaml` from `.env` (single-line YAML scalars; not committed; see `.gitignore`).
   - 15.2 `git add -A && git commit -m "fix: production reliability (RC1..RC8)"` then `git tag reliability-fix-<YYYYMMDD>` then `git push -u origin fix/production-reliability && git push --tags`. The pre-commit hook from 12.2 will block any leaked secret.
   - 15.3 `gcloud builds submit --no-cache --substitutions=_BUILD_MARKER=$(git rev-parse --short HEAD) --tag <image> .`
   - 15.4 `gcloud run deploy qa-bugbot --image <image> --region asia-south1 --env-vars-file env.yaml --service-account qaautomation@artful-affinity-634.iam.gserviceaccount.com`
5. **Phase 9** verifies the deploy. **Phase 10** rolls back to `qa-bugbot-00026-btk` only if Phase 9 fails.

---

## Critical things to NEVER do

1. Never run `gcloud builds submit` or `gcloud run deploy` without explicit user approval at Phase 7.
2. Never `git push` until the user approves at Phase 7.
3. Never modify `requirements.txt` to add new runtime deps.
4. Never reduce video frame extraction below 20 frames.
5. Never silently repair truncated JSON — raise `Phase2TruncatedError`.
6. Never retry Phase 2 on truncation/timeout/default-stuffing — fall back to Phase 1.
7. Never strip `[Tag]` from the brief sent to the LLM.
8. Never commit a real token to `.env.example`.
9. Never use `gcloud run deploy --set-env-vars` with space-separated values.
10. Never deploy from a dirty working tree.
11. Never skip the env validator wiring in `main.py lifespan`.
12. Never deploy without `--no-cache` on the build.

---

## Production environment facts

- Cloud Run service: `qa-bugbot`, region `asia-south1`
- Active revision: `qa-bugbot-00039-dth` (untouched until Phase 8)
- Last known-good rollback revision: `qa-bugbot-00026-btk`
- Service account: `qaautomation@artful-affinity-634.iam.gserviceaccount.com`
- GCS bucket: `gs://qa-bugbot-data/qa_bugbot.db`
- LLM gateway: `https://imllm.intermesh.net/v1`, model `google/gemini-2.5-flash`
- OpenProject: `https://project.intermesh.net`
- Image registry: `asia-south1-docker.pkg.dev/artful-affinity-634/cloud-run-source-deploy/qa-bugbot`

---

## Glossary

- **Phase 1** = text-only LLM analysis (`analyze_text_brief`)
- **Phase 2** = media-enriched LLM analysis (`enrich_with_media`)
- **BUILD_MARKER** = startup log line proving new image shipped
- **GCS_SYNC** = structured log line for every download/upload attempt
- **PHASE2_TRUNCATED** = ERROR log when Phase 2 JSON is truncated
- **PHASE2_DEFAULT_STUFFED** = ERROR log when Phase 2 returns mostly placeholders
- **PHASE2_SLOW** = ERROR log when Phase 2 hits 50s asyncio timeout
- **PRIORITY_AMBIGUOUS** = WARNING log when both HIGH and LOW priority keywords match
- **ENV_VALIDATION** = WARNING/INFO log prefix from startup env validator
- **OP_CALL** = structured log line wrapping every OpenProjectClient HTTP call

---

## If anything in this document conflicts with `design.md` or `requirements.md`, the spec docs win.
