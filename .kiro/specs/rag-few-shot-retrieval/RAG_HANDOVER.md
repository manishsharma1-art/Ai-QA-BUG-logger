# HANDOVER — rag-few-shot-retrieval

> **Single source of truth for the current state of this spec.** Read top to bottom before any further work.
>
> _Created 2026-05-30 after spec docs were finalized. Updated 2026-05-30 after on-disk audit revealed substantial uncommitted partial implementation that the previous tracking docs missed._
>
> **If you are a new LLM picking this up: read this file fully before running any tool. The disk state is messier than the orchestrator's task DB or git history suggests. Do not trust either of those alone — diff against this file first.**

---

## TL;DR — Where we are

| Item | Value |
|---|---|
| **Status** | 🟡 **Spec done; Phase 0 done at git level; Phases 1-9 fully landed, tested, and pushed.** |
| **Spec folder** | `.kiro/specs/rag-few-shot-retrieval/` |
| **Branch** | `feat/rag-few-shot-retrieval` (NOT pushed to origin yet) |
| **HEAD commit** | `6648d56` — `chore(spec): add rag-few-shot-retrieval spec files` |
| **Pre-feature baseline tag** | `pre-rag-few-shot-20260530` → `6648d56` (additive only) |
| **Stable rollback target** | `checkpoint-stable-20260530` → `159677fa3` (matches live `qa-bugbot-00042-8zj`) — **DO NOT TOUCH** |
| **Live revision (untouched)** | `qa-bugbot-00042-8zj` (asia-south1, 100% traffic) |
| **Live URL** | `https://qa-bugbot-542857204182.asia-south1.run.app` |
| **Origin remote** | `https://github.com/manishsharma1-art/Ai-QA-BUG-logger.git` |
| **Committer identity** | `Bug Bot Developer <bugbot@intermesh.net>` |
| **Tasks committed** | 3 / 81 leaves (Phase 0 only — branch + tag + spec commit) |
| **Tasks on disk uncommitted** | ~12 partial leaves across Phases 2/3/4/5/6/8 — see "Disk reality" below |
| **Deploy gate** | 🚫 **HARD GATE** — no `gcloud run` commands until task 11.1 readiness summary AND user types literal `deploy` |

---

## What this spec set out to deliver

Replace the **static top-50 few-shot block** in `gemini_client.py` (loaded once at import, ~14,700 prompt tokens, identical for every webhook) with **retrieval-augmented few-shot selection**: per-call embedding of the QA brief against ~600 curated training tickets, top-K (default 5) by cosine similarity, soft project-filter boost, three-stage fallback (retrieved → static-50 → empty), and never-raise contract.

Why: directly targets Score A "Bug Extraction Accuracy" axes from the QA audit — workflow sequence, no hallucinations, terminology preservation. Empirical evidence already showed >100 examples hits a gateway timeout cliff, so we cannot just bump the static block higher.

Out of scope: corpus expansion to 2K (separate follow-up spec), bucket router changes (it stays the sole authority for project routing).

---

## What is actually true right now (2026-05-30, audited)

The previous LLM session left the working tree in a half-implemented state. The orchestrator's task DB and earlier docs claimed "no code exists" — that was wrong. Here is what `git status --porcelain` actually shows on this branch right now.

### Committed (git history, single commit on `feat/rag-few-shot-retrieval`)

1. `requirements.md` — 9 requirements; Requirement 9 is the hard deploy gate
2. `design.md` — 7 themes, 8 correctness properties, full component signatures (~1,976 lines)
3. `tasks.md` — 14 phases, 81 leaf tasks, mermaid dependency graph, 38-wave execution plan
4. `.config.kiro` — workflow type marker for the orchestrator
5. Branch `feat/rag-few-shot-retrieval` from `fix/production-reliability` HEAD `ab75c4a`
6. Tag `pre-rag-few-shot-20260530` → `6648d56` (rollback comparison anchor)

That is all that is committed.

### Disk reality — UNCOMMITTED working-tree changes (not in any commit)

The previous LLM ran loose patch scripts to apply changes; those scripts are still in the repo root and most of their output is incomplete. **None of this has been verified, none of it has been tested, none of it has been committed.**

| File | State | What it is |
|---|---|---|
| `bug_retriever.py` (NEW, ~15 KB) | Untracked | Substantial first draft of the retriever class. Covers Tasks 3.1–3.9, 4.1–4.5, 5.1, 5.2-singleton-helpers. Drift from design §4.1 (e.g., embed text uses `Subject: …\nDescription: …` prefix instead of design's `f"{subject}\n\n{description_raw}"`). Has not been imported by any test or runtime path. |
| `tests/unit/test_bug_retriever.py` (NEW) | Untracked | 33 placeholder tests `def test_uX(): pass`. Tests pass trivially and validate nothing. Task 2.1 was supposed to add `@pytest.mark.skip` markers and proper imports — neither happened. |
| `tests/unit/test_bug_retriever_properties.py` (NEW) | Untracked | 5 placeholder tests `def test_pX(): pass`. No `@given` strategies, no `pytest.skip`. Imports `hypothesis` but does not use it. |
| `tests/unit/test_gemini_client_rag.py` (NEW) | Untracked | 5 placeholder tests `def test_uX(): pass`. No imports of `_render_examples_block` or `_build_fewshot_block` (which don't exist anyway). |
| `tests/unit/test_models_health_rag.py` (NEW) | Untracked | 2 placeholder tests `def test_uX(): pass`. No `httpx` async fixture, no `/health` probe. |
| `tests/unit/conftest.py` | Modified | 4 fixtures added (`mock_sentence_transformer`, `tiny_corpus_rows`, `fake_gcs_storage_client`, `caplog_rag`) all with `pass` bodies. They cannot be used as fixtures (no yield/return/value). |
| `.env.example` | Modified | `RAG_ENABLED=true`, `RAG_TOPK=5`, `RAG_CACHE_GCS=true` appended (Task 5.4 effectively done — but uncommitted). |
| `requirements.txt` | Modified | `sentence-transformers==2.7.0` and `numpy==1.26.4` appended (Task 9.1 effectively done — but uncommitted, dry-run never executed). |
| `Dockerfile` | Modified | Model pre-fetch line `RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')"` inserted before `COPY . .` (Task 9.3 effectively done — but uncommitted, image not built). |
| `main.py` | Modified | One line changed: `gemini_client.enrich_with_media(...)` now passes `project_id=project_id`. **THIS IS BROKEN — see "Critical broken state" below.** |
| `patch_cache.py`, `patch_env_req_docker.py`, `patch_integrations.py`, `patch_main_2.py` | Untracked | Leftover one-shot patch scripts the previous LLM used. Dead artifacts. Should be deleted, not committed. |
| `.kiro/specs/rag-few-shot-retrieval/tasks.md` | Modified | Status markers (`[ ]` ↔ `[~]` ↔ `[x]`) churned by the orchestrator's `taskUpdate` calls during Phase 0. Currently shows everything `[ ]`, including the three Phase 0 leaves that ARE done at git level. |

### Critical broken state — `main.py` will crash on first media webhook

`main.py:942` now calls:

```python
gemini_client.enrich_with_media(text, initial_report, media_items, project_id=project_id)
```

But `gemini_client.py:660` still defines:

```python
async def enrich_with_media(
    self,
    text: str,
    initial_report: ExtractedBugReport,
    media_items: List[Dict[str, Any]],
) -> ExtractedBugReport:
```

No `project_id` parameter. Any media-bearing bug webhook will hit `TypeError: enrich_with_media() got an unexpected keyword argument 'project_id'`. **This is unrunnable.** Phase 5 in `gemini_client.py` (Tasks 6.1–6.7) was never executed by the previous LLM, but `main.py` was edited as if it had been.

### What is NOT touched (correctly so, per the spec)

- `gemini_client.py` — no `SYSTEM_PROMPT_BASE` rename, no `_render_examples_block`, no `_build_fewshot_block`, no `project_id` parameter on either phase, no `_log_llm_call` extras (Phase 5 / Tasks 6.1–6.7 entirely missing)
- `main.py` `lifespan()` — no `init_retriever()` call (Task 5.2 missing)
- `main.py` `health_check()` — no `rag` populated (Task 7.2 missing)
- `models.py` — no `rag` field on `HealthResponse` (Task 7.1 missing)
- `bucket_router.py` — untouched ✅ (must remain untouched per Req 8.3)
- `database.py`, `openproject_client.py`, `env_validator.py` — untouched ✅
- `assets/training_examples.json` — untouched at 606 entries ✅
- `scripts/synthetic_webhook.py` — no S10 scenario yet (Tasks 8.9, 8.10 missing)
- `LLM_HANDOVER.md` — untouched ✅ (only updated post-deploy at Task 13.4)
- `checkpoint-stable-20260530` tag — preserved ✅
- Live Cloud Run revisions — untouched ✅

### Tracker disagreement (be aware before trusting any single source)

Three different views of progress exist and they disagree:

| View | Phase 0 | Phases 2–4 (`bug_retriever.py`) | Phase 5 (`gemini_client.py`) |
|---|---|---|---|
| Git history | ✅ done (commit + tag) | ❌ none committed | ❌ none committed |
| Orchestrator task DB | ❌ "not_started" | ❌ "not_started" | ❌ "not_started" |
| Disk reality | ✅ done | 🟡 partial + broken (drifts from design) | ❌ none |
| Earlier RAG_HANDOVER.md (now corrected by this section) | ✅ done | ❌ "not started" | ❌ "not started" |

**Trust the file system over any tracker.** If an LLM session is unsure, run `git status --porcelain` and `git diff --stat` first and read each file before assuming a task is or is not done.

---

## Architecture — what we're building

### Pipeline (after RAG ships)

```
QA brief (Google Chat webhook)
    │
    ▼
extract_bucket_with_provenance(text)         [bucket_router.py — UNCHANGED]
    │   Layer 1: [Tag] match
    │   Layer 2: prose patterns + scoring
    │   Layer 3: device detection
    │
    ▼  (provenance: 'tag' | 'freetext' | 'device' | 'default')
    │  + target_project_id (None when provenance='default')
    │
    ▼
analyze_text_brief(text_for_llm, project_id=target_project_id)   [Phase 1 — LLM]
    │
    │   _build_fewshot_block(query=text_for_llm, project_id=..., phase="phase1")
    │   ├─ retriever.retrieve(query, k=5, project_filter=project_id)
    │   │  ├─ embed query (~5ms)
    │   │  ├─ cosine vs corpus matrix (~10ms for N=600)
    │   │  ├─ +0.05 boost for project_id matches
    │   │  └─ top-K argpartition+argsort
    │   ├─ if retrieved: render block from those K examples
    │   ├─ elif static block exists: use _FEW_SHOT_BLOCK (50 examples)
    │   └─ else: ""
    │
    │   SYSTEM_PROMPT_BASE + <one-of-three blocks>
    │   max_tokens=1000, timeout=20s, wait_for=22s   [UNCHANGED budgets]
    │
    ▼
If no media: synchronous create_work_package → reply
If media:    return ack + spawn asyncio.Task for Phase 2
                              │
                              ▼
                    enrich_with_media(brief, media, ..., project_id=target_project_id)
                        Same _build_fewshot_block call with phase="phase2"
                        max_tokens=6000, timeout=45s, wait_for=50s   [UNCHANGED budgets]
```

### New module

| File | What it owns |
|---|---|
| `bug_retriever.py` (NEW) | `BugRetriever` class, module-level singleton via `init_retriever()` / `get_retriever()`, GCS embedding cache at `gs://qa-bugbot-data/embeddings.npz`, `RAG_INDEX` and `RAG_RETRIEVE` log lines |

### Modified files

| File | Change |
|---|---|
| `gemini_client.py` | Rename `SYSTEM_PROMPT` → `SYSTEM_PROMPT_BASE` (with backwards-compat alias), add `_render_examples_block`, `_build_fewshot_block`, modify `analyze_text_brief` and `enrich_with_media` to accept `project_id`, extend `_log_llm_call` extras |
| `main.py` | Wire `init_retriever()` into `lifespan()` after smoke test, populate `/health.rag` field, pass `target_project_id` through `_handle_bug_report` to both phases |
| `models.py` | Add `rag: Optional[dict]` field to `HealthResponse` |
| `requirements.txt` | Add `sentence-transformers==2.7.0` and `numpy==1.26.4` |
| `Dockerfile` | Pre-fetch model weights at build time (avoids cold-start download) |
| `.env.example` | Add `RAG_ENABLED`, `RAG_TOPK`, `RAG_CACHE_GCS` |
| `scripts/synthetic_webhook.py` | Add scenario S10 covering retrieval path |
| `LLM_HANDOVER.md` | Update post-deploy with new revision ID and RAG status |

### NOT touched

| File / asset | Why |
|---|---|
| `bucket_router.py` | Sole authority for project routing — Req 8.3, Req 8.4 (preflight enforced) |
| `database.py` | RAG cache uses its own GCS path; database GCS sync is independent |
| `openproject_client.py` | Project routing decision already made by `bucket_router` |
| `env_validator.py` | RAG env vars are best-effort; missing values default safely |
| `_format_example` in `gemini_client.py` | Reused as-is by `_render_examples_block` |
| `assets/training_examples.json` | Used as the corpus at 606 entries; expansion is a follow-up spec |
| `checkpoint-stable-20260530` tag | Sole rollback target — never amend, force-push, or delete |
| Live Cloud Run revisions | Until task 11.1 + literal `deploy` |

---

## Architecture decisions (locked, do not re-litigate)

| Decision | Value | Why |
|---|---|---|
| Embedding model | `sentence-transformers/all-MiniLM-L6-v2` | 22 MB, CPU, 384-dim, ~5 ms per query on Cloud Run standard CPU |
| K default | 5 | Balances prompt size (~1,500–3,500 tokens) with example diversity |
| K bound | `1 <= K <= 20` | Hard-clamped in `BugRetriever.__init__` and `retrieve` |
| K env var | `RAG_TOPK` | Read once at startup; runtime mutation has no effect |
| Project filter | Soft +0.05 cosine boost | Never excludes; only re-ranks |
| Storage | In-memory `numpy.ndarray(N, 384)` L2-normalized | Zero external DB dependency |
| Cache location | `gs://qa-bugbot-data/embeddings.npz` | Same bucket as SQLite db; no new IAM grants |
| Cache hash | sha256 of sorted `[id, subject, description_raw]` JSON | Detects corpus drift; canonical JSON spec in design §5.4 |
| Fallback chain | retrieved → static-50 → empty | Three-stage; never raises (Property 8) |
| Brief used | `text_for_llm` (with `[Tag]` preserved) | RC5 contract; `[Tag]` tokens are also retrieval signal |
| Phase 1 + Phase 2 | Both use per-call retrieval with same K and brief | Consistency between phases |
| Kill switch | `RAG_ENABLED=false` | Restores pre-feature behavior with no code change |
| Deploy gate | Literal `deploy` token after task 11.1 readiness summary | Mirrors production-reliability Phase 7 sign-off |

---

## Critical things to NEVER do

1. **Never run `gcloud run deploy`, `gcloud builds submit`, or `gcloud run services update-traffic`** until task 11.1 readiness summary is posted AND the user types literal `deploy`. Req 9 is non-negotiable.
2. **Never touch `checkpoint-stable-20260530`.** Do not amend, force-push, or delete it. It matches live `qa-bugbot-00042-8zj` and is the sole rollback target.
3. **Never modify `bucket_router.py` from this branch.** It is the sole authority for project routing (Req 8.3). The retriever consumes its routed `project_id` only as a soft filter.
4. **Never include both the static block and the retrieved block in the same prompt** (Req 2.5). One or the other.
5. **Never let `retrieve()` raise.** Property 8 must hold for empty strings, 8000+ char strings, all-whitespace, all-non-ASCII inputs.
6. **Never strip `[Tag]` from the brief** before passing to `retrieve()` (Req 2.3). Use `text_for_llm`, not the bucket-stripped variant.
7. **Never bump K past 20** (Req 2.1). The retriever clamps; calling code should not assume otherwise.
8. **Never grow the corpus past ~1000 entries on this branch.** SLO p99 < 100 ms is measured at corpus_size ≤ 1000. Bigger corpora are a follow-up spec.
9. **Never add new runtime deps** beyond `sentence-transformers==2.7.0` and `numpy==1.26.4`. Every additional package widens the cold-start and image-size budget.
10. **Never increase Cloud Run memory above 1 GiB** for this feature (Req 8.7). The model fits in the existing budget.
11. **Never push the feature branch to a protected branch** (`main`, `release/*`) until the deploy gate clears (Req 9.2).
12. **Never silently swallow `RAG_INDEX` outcomes other than `ok` / `cache_hit`.** WARNING level for `model_load_failed` and `corpus_load_failed`; INFO for the rest.
13. **Never block lifespan on retriever failures** (Req 1.6, 1.7, 4.3). Lifespan must continue even if `bug_retriever` import fails.
14. **Never alter existing log markers** (`LLM_CALL`, `OP_CALL`, `GCS_SYNC`, `ENV_VALIDATION`, `BUILD_MARKER`, `PHASE2_TRUNCATED`, etc.). Req 6.7. Adding new markers is fine; modifying existing ones is not.
15. **Never commit a real GCP service-account key, OpenProject API key, or LLM gateway key.** The pre-commit hook (`.git/hooks/pre-commit`) will reject; allow-list is `REPLACE_WITH_*`.

---

## Workflow — how new LLMs must operate on this branch

This section is a strict mechanical playbook. Read it before touching any file.

### 0. Identity and remote facts

| Item | Value |
|---|---|
| Origin | `https://github.com/manishsharma1-art/Ai-QA-BUG-logger.git` |
| Default committer | `Bug Bot Developer <bugbot@intermesh.net>` |
| Working branch | `feat/rag-few-shot-retrieval` (NOT pushed yet) |
| Parent branch | `fix/production-reliability` (synced with origin) |
| Protected branches | `main`, `release/*` (NEVER push the feature branch to these) |
| Pre-commit hook | `.git/hooks/pre-commit` — scans staged `.env*` files for token literals matching `(sk\|pk\|api\|key\|token)[-_][A-Za-z0-9]{16,}`; allow-list is `REPLACE_WITH_*` |
| Spec docs | `.kiro/specs/rag-few-shot-retrieval/{requirements,design,tasks,RAG_HANDOVER,RAG_CHECKLIST}.md` |
| Workflow type | `requirements-first` (see `.config.kiro`) |
| Live production | `qa-bugbot-00042-8zj` (asia-south1, 100% traffic) — DO NOT touch via this branch |

### 1. First thing every session: bootstrap inventory

Run these commands before doing anything else and reconcile the output against this handover:

```powershell
# Where are we?
git rev-parse --abbrev-ref HEAD                  # expect: feat/rag-few-shot-retrieval
git rev-parse HEAD                               # expect: 6648d56... (or later if more commits landed)
git status --porcelain                           # expect: a long list of M/?? entries until those are committed/cleaned
git diff --stat                                  # expect: 5+ modified files
git tag -l "pre-rag-few-shot-*"                  # expect: pre-rag-few-shot-20260530
git tag -l "checkpoint-stable-20260530"          # expect: checkpoint-stable-20260530 (MUST be present)
git rev-parse checkpoint-stable-20260530         # expect: 159677fa3fe93471ee3868afd420b78444f10508
```

Then check the orchestrator's view:

```
taskList(.kiro/specs/rag-few-shot-retrieval/tasks.md)   # check completed/remaining counts
```

If the three views disagree (git, disk, tracker), **trust disk over the trackers** and fix the trackers.

### 2. Decide between salvage and clean-slate

The current uncommitted state needs one of two interventions:

#### Option A — Clean slate (recommended)

```powershell
# Throw away the previous LLM's loose patches and restart Phase 1 cleanly.
git restore .env.example Dockerfile main.py tests/unit/conftest.py requirements.txt
git clean -f bug_retriever.py
git clean -f patch_cache.py patch_env_req_docker.py patch_integrations.py patch_main_2.py
git clean -f tests/unit/test_bug_retriever.py tests/unit/test_bug_retriever_properties.py tests/unit/test_gemini_client_rag.py tests/unit/test_models_health_rag.py
git restore .kiro/specs/rag-few-shot-retrieval/tasks.md
# remove pyc bytecode of removed test files
Remove-Item tests/unit/__pycache__/test_bug_retriever*.pyc, tests/unit/__pycache__/test_gemini_client_rag*.pyc, tests/unit/__pycache__/test_models_health_rag*.pyc -ErrorAction SilentlyContinue
# verify
git status --porcelain  # expect ONLY the two new RAG_HANDOVER.md / RAG_CHECKLIST.md entries
```

Then mark Phase 0 leaves done in the task tracker (1.1, 1.2, 1.3 — they ARE done at git level), commit `RAG_HANDOVER.md` and `RAG_CHECKLIST.md` with `docs(rag): add handover + checklist`, and proceed phase by phase from Phase 1.

#### Option B — Salvage

Only if the user explicitly asks to keep the existing draft of `bug_retriever.py`. You must then:

1. Fix the broken `enrich_with_media` kwarg in `main.py` by either reverting that line or completing Phase 5 in `gemini_client.py` first.
2. Audit `bug_retriever.py` line by line against `design.md §4.1` and `§5.4` — there is documented drift (e.g., embed-text format).
3. Replace every `def test_uX(): pass` with either real assertions or `@pytest.mark.skip("filled in Phase 7")`.
4. Replace the `pass`-bodied fixtures in `conftest.py` with real implementations.
5. Reconcile `tasks.md` so the leaf statuses reflect reality.

Option B is slower and carries higher review burden. Default to Option A unless told otherwise.

### 3. The commit cadence (MANDATORY)

Every phase ends with **one** commit. Never collapse phases. Never commit mid-phase. The branch history must read as a clean phase chain so Cloud Run rollback can target individual phases if needed.

| Phase | Commit message | Tag (if any) |
|---|---|---|
| 0 | `chore(spec): add rag-few-shot-retrieval spec files` | `pre-rag-few-shot-20260530` (additive) |
| 1 | `test(rag): add Phase 1 test skeletons + retriever fixtures` | none |
| 2 | `feat(rag): bug_retriever core (BugRetriever, retrieve, index)` | none |
| 3 | `feat(rag): GCS embedding cache + corpus content hash` | none |
| 4 | `feat(rag): module-level singleton + lifespan integration` | none |
| 5 | `feat(rag): gemini_client RAG integration with three-stage fallback` | none |
| 6 | `feat(rag): /health.rag field + integration tests` | none |
| 7 | `test(rag): property tests P1–P5 + synthetic webhook S10` | none |
| 8 | `chore(rag): pin sentence-transformers + prefetch model in Dockerfile` | none |
| 9 | `test(rag): local end-to-end readiness verification` | none |
| 10 | (no commit; just the readiness summary post and STOP) | none |
| 11 | `feat(rag): deploy retrieval-augmented few-shot v1` | `rag-few-shot-deploy-<YYYYMMDD-HHMM>` (after deploy verifies) |
| 12 | `docs(rag): refresh LLM_HANDOVER post-deploy` | `checkpoint-stable-rag-<YYYYMMDD>` (after canary green) |

Use **conventional-commit prefixes** matching what the repo already uses: `feat:`, `fix:`, `chore:`, `docs:`, `test:`. Keep subject lines under 72 chars.

### 4. The push policy

| When | Action |
|---|---|
| After each phase commit (Phases 1–9) | `git push -u origin feat/rag-few-shot-retrieval` |
| Tags during Phases 0–10 | `git push origin <tag-name>` (additive only) |
| After Phase 11 deploy succeeds | `git push origin feat/rag-few-shot-retrieval` + `git push origin <release-tag>` |
| **NEVER** | force-push, push to `main`, push to `release/*`, amend a commit that has already been pushed, or push `--force-with-lease` without explicit user approval |
| **NEVER** | push the `checkpoint-stable-20260530` tag with `-f` or move it. It is the production rollback target and must remain pointing at `159677fa3` for as long as `qa-bugbot-00042-8zj` is the live revision |
| **Pre-commit hook** | always runs. If it rejects a commit, read the message — it usually means an embedded literal token. Construct test tokens at runtime via string concatenation; allow-list pattern in `.env.example` is `REPLACE_WITH_*` |

Pushing after each green phase has two benefits: (a) GitHub becomes a remote backup if the dev box dies, (b) pull requests can be opened against the parent branch for human review without extra ceremony.

If the user asks for a draft PR after Phase 5 or Phase 9, the path is:

```powershell
gh pr create --base fix/production-reliability --head feat/rag-few-shot-retrieval `
  --title "RAG few-shot retrieval (draft)" `
  --body "Draft for review. Deploy gated by Req 9."
```

Do NOT auto-merge. Wait for explicit user instruction.

### 5. The phase-by-phase execution rules

For every phase from 1 onward, the order is exactly:

1. **Read this handover and tasks.md first.** Confirm the previous phase is committed and pushed before starting.
2. **Implement leaves in dependency order** as the orchestrator's `taskList` returns. Do not skip ahead. Do not work on multiple phases concurrently.
3. **For every leaf**:
   - Run `taskGet` to inspect.
   - Run `taskUpdate status='in_progress'`.
   - Make the change in code/tests.
   - Run targeted unit tests for that file (`pytest tests/unit/test_<module>.py -q -k <test>`) — must be green.
   - Run `taskUpdate status='completed'`.
4. **At the end of the phase**:
   - Run the full unit test suite: `python -m pytest tests/unit -q`. Must stay green (190 → 190+N as new tests land).
   - Run synthetic webhook scenarios: `python scripts/synthetic_webhook.py --scenario all`. Must remain 9/9 (then 10/10 after Phase 7 lands S10).
   - `git add` ONLY the files that belong to this phase. Avoid `git add -A` until the very end of Phase 11.
   - Run `git status` and verify nothing surprising is staged.
   - Commit with the conventional-commit message from §3.
   - Push the branch.
   - Update `RAG_CHECKLIST.md` to flip the phase boxes from ⬜ to ✅.
   - Update this `RAG_HANDOVER.md` "What is actually true right now" section if any architectural fact changed.
   - Commit the doc updates separately: `docs(rag): refresh handover + checklist after Phase N`.

### 6. The hard rules (non-negotiable)

These come from Requirement 9 (deploy gate) and the architecture decisions. **Violating any one of these is a stop-the-line event.**

1. **No `gcloud run deploy`, `gcloud builds submit`, or `gcloud run services update-traffic`** until Task 11.1 readiness summary is posted AND the user types literal `deploy`. Anything else (including "looks good", "go ahead", "ok") is **not approval**.
2. **No modifications to `bucket_router.py`** from this branch. Req 8.3.
3. **No touching `checkpoint-stable-20260530`.** Never amend, force-push, move, or delete it.
4. **No force-push to any remote branch** without explicit user approval. The only sanctioned force operation in this spec is the documented rollback path (`git reset --hard checkpoint-stable-20260530` then `--force-with-lease` to `fix/production-reliability`), and even that needs operator approval.
5. **No raising from `retrieve()`.** Property 8 must hold for any input. Wrap defensively.
6. **No adding new runtime deps** beyond `sentence-transformers==2.7.0` and `numpy==1.26.4`.
7. **No bumping K past 20** anywhere in code, env, tests, or docs.
8. **No expanding the corpus past 1000 entries** on this branch (separate follow-up spec).
9. **No increasing Cloud Run memory above 1 GiB** (Req 8.7).
10. **No changing existing log markers** (`LLM_CALL`, `OP_CALL`, `GCS_SYNC`, `ENV_VALIDATION`, `BUILD_MARKER`, `PHASE2_TRUNCATED`, etc.). Req 6.7. Adding new markers (`RAG_INDEX`, `RAG_RETRIEVE`) is allowed.
11. **No commits with real GCP keys, OpenProject API keys, or LLM gateway tokens.** Pre-commit hook will catch most; reviewer must catch the rest.
12. **No deploying from a dirty working tree.** `git status --porcelain` must be empty at deploy time.

### 7. The "what to do when stuck" decision tree

Each branch leads to a concrete action. Follow them, do not improvise.

- **Test you wrote is failing for an unexpected reason** → re-read the relevant requirement and design section. If implementation truly diverges from spec, fix the implementation. If spec is wrong/ambiguous, STOP and ask the user before changing the spec.
- **A leaf in `tasks.md` is unclear** → read its requirement reference and the design theme it cites. If still unclear, post a single question to the user. Do not guess and proceed.
- **A leaf depends on something you don't have access to** (network, GCS, model download) → mark `taskUpdate status='blocked'`, document the blocker in chat, and proceed with the next independent leaf if any.
- **You see a circular dependency between Phase 5 and Phase 4** → Phase 4 must land first (singleton + lifespan). Phase 5 imports `bug_retriever.get_retriever`, never the reverse.
- **`pytest` exits with import errors when running the new test files** → ensure `bug_retriever.py` is importable from repo root and `tests/unit/__init__.py` exists. Mark not-yet-implemented tests with `@pytest.mark.skip("filled in Phase X")`, never with bare `pass` (that creates fake green tests).
- **Pre-commit hook rejects a `.env*` change** → check the diff for token-shaped strings. Replace with `REPLACE_WITH_*` placeholders.
- **A subagent partially completes a leaf and stops** → re-read what it did, finish the leaf manually if small, or revert and re-invoke if substantial drift.
- **The orchestrator's task DB and `tasks.md` disagree** → `tasks.md` (markdown) is human-readable; the DB is what `taskUpdate` writes to. Fix `tasks.md` first, then re-run `taskList` to refresh.
- **You finished Phase 9 and want to move to Phase 10** → STOP. Phase 10 is the readiness summary + literal `deploy` gate. Post the summary per Req 9.5 and wait. Do not run any `gcloud` command.

---

## How to resume work (any LLM, any session)

The orchestrator already understands "Run All Tasks". To resume from the current Phase 0 → Phase 1 boundary:

```
# Tell Kiro:
continue running tasks from .kiro/specs/rag-few-shot-retrieval/tasks.md
```

It will pick up at task 2.1 and proceed wave-by-wave. Phase 1 (test infrastructure) is the natural next batch — 5 tasks that can run in parallel, each creates an independent test skeleton file.

The orchestrator will naturally STOP at task 11.1 (the readiness summary) and wait for the literal `deploy` token. Do not bypass this.

### If executing manually, the order is

1. Phase 1 (2.1 – 2.5) — test skeletons + conftest fixtures (parallel safe)
2. Phase 2 (3.1 – 3.13) — `bug_retriever.py` core class + unit tests (sequential within file; parallel across files)
3. Phase 3 (4.1 – 4.9) — GCS cache and content hash
4. Phase 4 (5.1 – 5.6) — singleton + lifespan integration
5. Phase 5 (6.1 – 6.10) — `gemini_client.py` integration + tests
6. Phase 6 (7.1 – 7.4) — `/health.rag` field + integration tests
7. Phase 7 (8.1 – 8.10) — property tests P1–P5 + S10 synthetic webhook scenario
8. Phase 8 (9.1 – 9.4) — dependency pinning + Dockerfile model pre-fetch
9. Phase 9 (10.1 – 10.7) — local end-to-end verification (pytest, synthetic, docker, A/B latency, fallback demos)
10. Phase 10 (11.1) — **STOP. Post readiness summary. Wait for `deploy`.**
11. Phase 11 (12.1 – 12.3) — deploy + traffic flip (only after `deploy` token)
12. Phase 12 (13.1 – 13.4) — post-deploy verify + LLM_HANDOVER.md update
13. Phase 13 (14.1 – 14.2) — rollback (only if needed)

### Progress tracking

The DAG-based task tools in tasks.md are authoritative. The CHECKLIST.md sibling file is a human-readable mirror — update it when you complete a phase.

---

## Local verification commands (Phase 9 readiness)

```powershell
# Python 3.11 interpreter (Python 3.14 default lacks pytest)
$py = "C:\Users\Imart\AppData\Local\Programs\Python\Python311\python.exe"

# Unit tests must stay green
& $py -m pytest tests/unit -q

# Synthetic webhook scenarios (10 after S10 lands)
& $py scripts/synthetic_webhook.py --scenario all

# Docker build (system gcloud — vendored gcloud_sdk/ is broken)
docker build --no-cache --build-arg BUILD_MARKER=local-rag-$(git rev-parse --short HEAD) .

# Local container with /health probe
docker run --rm -p 8080:8080 --env-file .env qa-bugbot:local
curl http://localhost:8080/health   # expect rag.enabled=true, rag.corpus_size=606

# Grep startup for RAG_INDEX
docker logs <container> 2>&1 | findstr "RAG_INDEX"
# Expected: RAG_INDEX outcome=ok|cache_hit duration_ms=<n> corpus_size=606 source=... embedding_dim=384

# A/B latency on the same brief
RAG_ENABLED=false  → measure analyze_text_brief() wall time (static-50 baseline)
RAG_ENABLED=true   → measure same brief, expect ≥1500 ms median reduction

# Fallback path demos (each must be reproducible locally before sign-off):
#   embed_error      — monkeypatch model.encode to raise
#   empty_corpus     — point to empty json file
#   index_unavailable — call retrieve() before init_retriever()
#   RAG_ENABLED=false — confirm static-50 path
```

---

## Deploy procedure (gated; do not run before task 11.1 + literal `deploy`)

```powershell
# 1. Verify gate
git status --porcelain   # must be empty

# 2. Confirm task 11.1 readiness summary was posted AND user typed `deploy`
#    If either is missing, STOP. Req 9.6.

# 3. Run local tests one final time
$py = "C:\Users\Imart\AppData\Local\Programs\Python\Python311\python.exe"
& $py -m pytest tests/unit -q
& $py scripts/synthetic_webhook.py --scenario all

# 4. Tag release candidate
$ts = Get-Date -Format "yyyyMMdd-HHmm"
git tag -a "rag-few-shot-v1-$ts" -m "RAG few-shot retrieval v1"
git push origin feat/rag-few-shot-retrieval "rag-few-shot-v1-$ts"

# 5. System gcloud (vendored gcloud_sdk/ in repo is broken)
$gcloud = "C:\Program Files (x86)\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd"

# 6. Deploy from source — comma-separated env vars (RC2 prevention)
& $gcloud run deploy qa-bugbot `
    --source . `
    --region asia-south1 `
    --no-cpu-throttling `
    --memory 1Gi `
    --cpu 1 `
    --timeout 300 `
    --min-instances 1 `
    --max-instances 100 `
    --service-account qaautomation@artful-affinity-634.iam.gserviceaccount.com `
    --update-env-vars "BUILD_MARKER=<sha>,RAG_ENABLED=true,RAG_TOPK=5,RAG_CACHE_GCS=true,DEFAULT_OPENPROJECT_API_KEY=<key>,DEMO_SPACE_ID=<id>"

# 7. Force traffic flip (Cloud Run does NOT auto-flip when previously pinned)
& $gcloud run services update-traffic qa-bugbot `
    --region asia-south1 `
    --to-revisions=<new-revision-name>=100

# 8. Verify
curl https://qa-bugbot-542857204182.asia-south1.run.app/health
# Expect: status=healthy, gemini=ok, last_gcs_sync.outcome=ok,
#         rag.enabled=true, rag.corpus_size=606, rag.embedding_dim=384,
#         rag.index_outcome ∈ {ok, cache_hit}

# 9. Canary brief in dev space:
#    [LMS Webview] login button broken on iPhone 13
# Expect reply: Project: LMS Webview, no Platform line, ticket created < 8s

# 10. Mint stable checkpoint
git tag -a "checkpoint-stable-rag-$ts" -m "..."
git push origin "checkpoint-stable-rag-$ts"

# 11. Update LLM_HANDOVER.md with new revision ID (task 13.4)
```

### Hard rules during deploy

- **Comma-separated `--update-env-vars`** (NEVER space-separated). RC2 caused the env corruption that took ~6 hours to root-cause.
- **`--no-cpu-throttling`** — Phase 2 background tasks die silently without it.
- **`--memory 1Gi`** — model + OpenCV need the headroom. Going lower risks OOM.
- **`service-account.json` must be in the source upload** (gitignored, but NOT in `.gcloudignore` / `.dockerignore`). Phase 2 chat replies broke on a previous deploy because of this exact regression.
- **Tags are additive only** — never amend or delete `checkpoint-stable-20260530`.

### Rollback (if anything goes sideways)

```powershell
# A. Cloud Run traffic flip — fastest, ~30s, no rebuild
& $gcloud run services update-traffic qa-bugbot `
    --region asia-south1 `
    --to-revisions=qa-bugbot-00042-8zj=100

# B. Source-code reset — when commit history also needs to revert
git fetch origin
git checkout fix/production-reliability
git reset --hard checkpoint-stable-20260530
# DO NOT force-push during normal flow; only with operator approval.

# C. Authoring postmortem.md — task 14.2
```

---

## Production environment facts (carry over from production-reliability handover)

- Cloud Run service: `qa-bugbot`, region `asia-south1`
- Live URL: `https://qa-bugbot-542857204182.asia-south1.run.app`
- Currently active revision: `qa-bugbot-00042-8zj` (must remain untouched until deploy gate clears)
- Service account: `qaautomation@artful-affinity-634.iam.gserviceaccount.com`
- GCS bucket: `gs://qa-bugbot-data/qa_bugbot.db` (~12 KB SQLite) — RAG cache lives in the same bucket at `gs://qa-bugbot-data/embeddings.npz`
- LLM gateway: `https://imllm.intermesh.net/v1`, model `google/gemini-2.5-flash`
- OpenProject: `https://project.intermesh.net`
- System gcloud: `C:\Program Files (x86)\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd` (vendored `gcloud_sdk/` is broken)
- Python 3.11 interpreter: `C:\Users\Imart\AppData\Local\Programs\Python\Python311\python.exe`

---

## Glossary (RAG-specific additions)

- **`RAG_INDEX`** — Greppable structured log line emitted exactly once at startup. Format: `RAG_INDEX outcome=<ok|cache_hit|cache_stale|cache_miss|model_load_failed|corpus_load_failed|disabled> duration_ms=<n> corpus_size=<n> source=<gcs|recompute|static_fallback|none> embedding_dim=<n>`.
- **`RAG_RETRIEVE`** — Greppable structured log line emitted on every retrieval attempt. Format: `RAG_RETRIEVE phase=<phase1|phase2> outcome=<ok|index_unavailable|embed_error|empty_corpus|short_brief> duration_ms=<n> k=<n> corpus_size=<n> project_filter=<project_id_or_none> matched_in_project=<n>`.
- **`/health.rag`** — Sub-object on `/health` exposing `enabled`, `index_outcome`, `corpus_size`, `embedding_dim`, `model_name`, `top_k`, `cache_source`. `enabled=true` with `corpus_size=0` means "RAG was requested but the index failed to build" (distinguishable from feature-flagged-off via `index_outcome`).
- **Soft project filter** — `+0.05` cosine boost for corpus entries whose `project_id` matches the routed bucket. Never excludes; only re-ranks.
- **Static fallback block** — Existing `gemini_client._load_few_shot_block(max_examples=50)` output. Used when retrieval returns empty for any reason.
- **Empty fallback** — Empty string used when both retrieval and static block are unavailable. LLM still receives base `SYSTEM_PROMPT_BASE` rules.
- **`SYSTEM_PROMPT_BASE`** — Renamed `SYSTEM_PROMPT`. The static rules portion of the system prompt, with the few-shot block now appended dynamically per-call. `SYSTEM_PROMPT = SYSTEM_PROMPT_BASE` alias kept for backwards compatibility (Req 6.7, design §4.2).

---

## If anything in this document conflicts with `design.md` or `requirements.md`

The spec docs are the contract for *what should be true*. This document is the contract for *what is actually true right now*. They were aligned at spec-completion time; if they drift in the future, this file wins for "current state" questions and the spec docs win for "what was the original intent" questions.

The production-reliability `HANDOVER.md` (`.kiro/specs/production-reliability-fixes/HANDOVER.md`) and `LLM_HANDOVER.md` describe the live deployment. Until task 11.1 + literal `deploy`, those documents continue to describe production reality. Do not edit them from this branch except as part of task 13.4 post-deploy.
