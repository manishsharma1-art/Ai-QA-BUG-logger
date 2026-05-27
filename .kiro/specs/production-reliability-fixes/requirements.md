# Requirements Document

## Introduction

The QA Bug Logger Bot (`qa-bugbot`, `asia-south1`) was found to be degraded in production
across deployment, observability, LLM correctness, and bucket-tag routing. Live diagnostics
documented in the design doc identified **eight independent root causes** (RC1–RC8) which
were grouped into **six themes** in
`.kiro/specs/production-reliability-fixes/design.md`:

1. Deployment hygiene (RC1 stale image, RC2 corrupted env vars, RC7 leaked example secret,
   RC8 commit discipline).
2. Observability of GCS sync (RC3 silent exceptions).
3. Phase 2 LLM pipeline correctness (RC4 truncated JSON / placeholder steps).
4. Bucket router robustness (RC5 strips and over-matches the `[Tag]`).
5. Priority validator robustness (RC6 substring match misclassifies priorities).
6. Local-first verification (preflight + three test tiers gating every deploy).

This requirements document derives the user-visible requirements for the fix from the
finalized design. It introduces no new behavior beyond what is already specified in the
design doc and re-uses the exact log line formats, keyword lists, regex shapes, and
test cases defined there.

The requirements are addressed to three stakeholder roles:

- **QA tester** — submits bug reports via Google Chat and expects accurate, well-routed
  tickets with real reproduction steps.
- **Operations / on-call engineer** — needs greppable diagnostic logs to triage failures
  without GCP console access.
- **Developer / contributor** — needs a deterministic local verification flow that gates
  every deploy.

## Glossary

- **Phase 1** — Text-only LLM analysis of the QA tester's brief (`analyze_text_brief`),
  fast (~5–10s), single attempt, no retries.
- **Phase 2** — Media-enriched LLM analysis (`enrich_with_media`) that combines the Phase 1
  result, the original brief, and extracted video frames / screenshots.
- **GCS** — Google Cloud Storage. Persistent storage at `gs://qa-bugbot-data/qa_bugbot.db`
  used to survive container restarts of the SQLite registration database.
- **`BUILD_MARKER`** — A startup log line of the form `BUILD_MARKER: <git-sha-or-build-time>`
  emitted once by `lifespan()` and exposed via `/health.build_marker`. Proves the new image
  shipped (counter-measure for RC1).
- **EARS** — Easy Approach to Requirements Syntax. Uses keywords WHERE, WHILE, WHEN, IF,
  THEN, THE, SHALL.
- **Bucket tag** — A bracketed token at the start of the QA brief (e.g. `[LMS Webview]`,
  `[Msite]`) that selects the OpenProject project the ticket is filed under.
- **`cleaned_text` / `text_for_llm`** — The text returned by `extract_bucket_from_message`
  to be passed to the LLM. After this fix, this is **byte-identical** to the user's input
  (the bucket tag is no longer stripped).
- **`PRIORITY_AMBIGUOUS`** — Audit log warning emitted when both a HIGH and a LOW priority
  keyword appear in the same string; tie-breaker resolves to MEDIUM.
- **`GCS_SYNC`** — Structured log line emitted on every GCS sync attempt:
  `GCS_SYNC op=<download|upload> outcome=<ok|skipped|import_error|auth_error|forbidden|not_found|network_error|unknown_error> duration_ms=<n> bytes=<n> detail="..."`.
- **`PHASE2_TRUNCATED`** — ERROR-level log line emitted when `_clean_json_response` detects
  that the Phase 2 LLM response is truncated (open braces / open brackets / unterminated
  string). Should never fire at `max_tokens=6000` in normal operation.
- **`PHASE2_DEFAULT_STUFFED`** — ERROR-level log line emitted when `_detect_default_stuffing`
  finds that a Phase 2 response is mostly placeholder values; signals LLM gateway degradation.
- **`PHASE2_SLOW`** — ERROR-level log line of the form
  `PHASE2_SLOW outcome=timeout duration_ms=<n> frames=<n>` emitted when Phase 2 exceeds the
  50s `asyncio.wait_for` ceiling. Triggers the same fall-back-to-Phase-1 contract as
  `Phase2TruncatedError` and `PHASE2_DEFAULT_STUFFED`.
- **`_extract_bucket_from_freetext`** — Pure-Python helper in `bucket_router.py` that runs
  between the explicit `[Tag]` regex and the device-detection fallback. Implements the
  `bucket - X` / `bucket: X` shorthand, multi-word phrase scoring, and weighted single-word
  alias scoring described in design Theme 4.5. Does NOT call the LLM.
- **`CROSS_KEYWORD_SINGLE_WORDS`** — Constant set in `bucket_router.py` of single words
  (`login`, `home`, `homepage`, `search`, `page`, `screen`, `app`, `android`, `ios`, `user`,
  `buyer`, `seller`) that are too generic to single-handedly select a bucket; receive
  weight 1 in the free-text scoring pass instead of the default 5.
- **`ENV_VALIDATION`** — Greppable WARNING/INFO log prefix emitted by the startup env-var
  validator (`ENV_VALIDATION: <message>` or `ENV_VALIDATION: all checks passed`).
- **`OP_CALL`** — New structured log line wrapper added around `OpenProjectClient` HTTP
  calls: `OP_CALL outcome=… duration_ms=…`.
- **`Phase2TruncatedError`** — Exception raised by `_clean_json_response` on detected
  truncation. Caught by `enrich_with_media`, which then falls back to the Phase 1 result.
- **`_last_gcs_sync`** — Module-level state in `database.py` holding the most recent
  `GcsSyncStatus` snapshot. Surfaced through `/health.last_gcs_sync`.
- **Bot** — The `qa-bugbot` Cloud Run service, considered as a whole. The deployed FastAPI
  application that accepts Google Chat webhooks and creates OpenProject tickets.
- **Bucket router** — `bucket_router.py` module, specifically `extract_bucket_from_message`
  and `_resolve_tag`.
- **Env validator** — The `validate_env_vars(settings)` function added in Theme 1.2.
- **Preflight script** — `scripts/preflight.sh` (and `.bat` for Windows) that runs every
  local check before any deploy.
- **Sign-off gate** — Phase B of the rollout plan: the user must explicitly say "deploy"
  before any image is built or pushed. No deploy happens without this.
- **Synthetic webhook scenarios** — `scripts/synthetic_webhook.py` Tier 2 scenarios
  S1–S8 defined in design §6.

## Requirements

### Requirement 1: Reliable bucket-tag routing

**User Story:** As a QA tester, I want the bucket tag in my brief (e.g. `[LMS Webview]`,
`[Msite]`) to route my bug to the correct OpenProject project even when I make a typo, and
I want unrelated bracketed text (e.g. `[step 3]`) in my message body to be ignored for
routing, so that my tickets land in the right project without manual triage.

#### Acceptance Criteria

1. WHEN a Google Chat message text begins (after optional whitespace) with a bracketed token
   matching the regex `^\s*\[([A-Za-z][A-Za-z0-9 &/\-]{1,40})\]\s*`, THEN THE bucket router
   SHALL treat that token as a candidate bucket tag and attempt to resolve it to an
   OpenProject project id.
2. IF the message text does not begin with a token matching the bucket tag regex,
   THEN THE bucket router SHALL NOT treat any later bracketed text in the message as a
   bucket tag and SHALL fall through to device-platform detection on the original text.
3. WHEN a candidate bucket tag exactly matches a key of `OP_PROJECTS` (case-sensitive or
   case-insensitive), THEN THE bucket router SHALL resolve to that project id.
4. WHEN a candidate bucket tag exactly matches a key of `PROJECT_ALIASES`, THEN THE bucket
   router SHALL resolve to the project id of the aliased project name.
5. WHEN a candidate bucket tag does not match any exact alias, THE bucket router SHALL
   perform an alias-substring match where the alias appears within the candidate tag AND
   the alias is at least 3 characters long.
6. THE bucket router SHALL NOT perform the inverse substring match (candidate tag appearing
   inside an alias).
7. WHEN exact and substring matching both fail, THE bucket router SHALL perform a fuzzy
   match against project names and aliases using `difflib.get_close_matches` with a cutoff
   of `0.78`.
8. IF the lowercased candidate tag has length less than 2, THEN THE bucket router SHALL
   return `None` and SHALL NOT attempt any further resolution step.
9. WHERE the message text contains a bucket tag, THE bucket router SHALL preserve the
   original text byte-identically when returning `text_for_llm` to the caller (the
   tag SHALL NOT be stripped from the brief sent to the LLM).
10. WHEN no candidate bucket tag is found OR the candidate tag fails to resolve to any
    project id, THEN THE bucket router SHALL fall back to device-platform detection on
    the original text and SHALL return that detected project id together with the original
    text.
11. WHEN the input message is `[LMS Webview] flickering` (test case T-BR-1), THEN THE
    bucket router SHALL resolve to OpenProject project `LMS Webview` (id 476) AND SHALL
    return `text_for_llm` equal to `[LMS Webview] flickering`.
12. WHEN the input message is `[LMS Webveiw] flickering` (test case T-BR-2, edit distance
    2 typo), THEN THE bucket router SHALL resolve to OpenProject project `LMS Webview`
    via fuzzy match AND SHALL return `text_for_llm` byte-identical to the input.
13. WHEN the input message is `[lms] login broken` (test case T-BR-3), THEN THE bucket
    router SHALL resolve to OpenProject project `LMS Webview` via the `lms` alias AND
    SHALL return `text_for_llm` byte-identical to the input.
14. WHEN the input message is `Login fails [step 3]` (test case T-BR-4), THEN THE bucket
    router SHALL return `None` for the candidate tag, SHALL fall back to device detection,
    SHALL select the Android default project, AND SHALL return `text_for_llm` byte-identical
    to the input.
15. WHEN the input message is `[2024-05-12] crash` (test case T-BR-5), THEN THE bucket
    router SHALL reject the candidate tag at the regex stage (digit-leading content),
    SHALL fall back to device detection, AND SHALL return `text_for_llm` byte-identical
    to the input.
16. WHEN the input message is `[L] crash` (test case T-BR-6), THEN THE bucket router SHALL
    return `None` (the lowercased tag fails the length-2 guard or fails the alias len ≥ 3
    rule), SHALL fall back to device detection, AND SHALL return `text_for_llm`
    byte-identical to the input.
17. WHEN the input message is `[home] page broken` (test case T-BR-7), THEN THE bucket
    router SHALL return `None` (no exact alias `home`, fuzzy 0.78 cutoff blocks the weak
    match against `homepage`), SHALL fall back to device detection, AND SHALL return
    `text_for_llm` byte-identical to the input.
18. WHEN the input message is `[Desktop Homepage] hero broken` (test case T-BR-8), THEN
    THE bucket router SHALL resolve to OpenProject project `Desktop Homepage` (id 50) AND
    SHALL return `text_for_llm` byte-identical to the input.
19. WHEN the input message is `[Header & Footer] logo cropped` (test case T-BR-9), THEN
    THE bucket router SHALL resolve to OpenProject project `Desktop Header Footer`
    (id 44) AND SHALL return `text_for_llm` byte-identical to the input.
20. WHEN the input message is `[Random Garbage Tag] something` (test case T-BR-10), THEN
    THE bucket router SHALL return `None` (no exact, no substring, no fuzzy match passes
    cutoff 0.78), SHALL fall back to device detection, AND SHALL return `text_for_llm`
    byte-identical to the input.
21. WHEN no `[Tag]` matches at the start of the message, THE bucket router SHALL invoke
    `_extract_bucket_from_freetext(text)` to attempt free-text bucket extraction before
    falling back to device detection.
22. WHEN the message contains the pattern `bucket\s*[-:]?\s*<name>` (case-insensitive),
    THE bucket router SHALL extract `<name>` and pass it through `_resolve_tag`. WHEN
    `_resolve_tag` returns a project id, THAT project id SHALL win.
23. WHEN the message contains a multi-word OpenProject project name as a whole-word phrase
    (e.g. `LMS Webview`, `Desktop Homepage`, `Photo Search`), THE bucket router SHALL
    assign that project a score of 10 in the free-text scoring pass.
24. WHEN the message contains a multi-word alias as a whole-word phrase, THE bucket router
    SHALL assign the aliased project a score of 8.
25. WHEN the message contains a single-word alias that is NOT in the
    `CROSS_KEYWORD_SINGLE_WORDS` set, THE bucket router SHALL assign the aliased project
    a score of 5.
26. WHEN the message contains a single-word alias that IS in the
    `CROSS_KEYWORD_SINGLE_WORDS` set (e.g. `login`, `home`, `search`, `page`, `screen`,
    `app`, `android`, `ios`), THE bucket router SHALL assign the aliased project a score
    of 1.
27. WHEN the free-text scoring pass produces a single highest-scoring project, THE bucket
    router SHALL return that project id.
28. WHEN the free-text scoring pass produces multiple projects tied at the highest score
    AND that score is less than 10 (i.e. ambiguous low-confidence match), THE bucket
    router SHALL return `None` and SHALL fall back to device detection.
29. WHEN the input message is `bucket - LMS webview, login button not working` (test case
    T-BR-11), THE bucket router SHALL resolve to LMS Webview (476).
30. WHEN the input message is `Flickering on LMS Webview chat screen, iPhone 13` (test
    case T-BR-13), THE bucket router SHALL resolve to LMS Webview (476) AND SHALL NOT
    default to iOS despite the iPhone device.
31. WHEN the input message is `Photo Search bug on Android` (test case T-BR-14), THE
    bucket router SHALL resolve to Photo Search (461) AND SHALL NOT default to Android
    despite the Android keyword.
32. WHEN the input message is `App hangs on login screen, Samsung S23, Android 14` (test
    case T-BR-16), THE bucket router SHALL resolve to Android (3) via device detection
    because no explicit or free-text bucket mention is present.
33. WHEN the input message is `BL webview crash on Android, Samsung S23` (test case
    T-BR-20), THE bucket router SHALL resolve to Android (3) because webview category
    names (BL_Webview, LMS_Webview, BMC_WEBVIEW) are sub-categories of the Android
    project, not separate buckets.

### Requirement 2: Persistent registration with structured GCS sync observability

**User Story:** As a QA tester, I want my OpenProject API key registration to survive
container restarts and new deployments. As an on-call engineer, I want to see exactly why
a GCS sync failed (auth, forbidden, network, not_found, unknown) without opening the GCP
console, so that I can triage registration loss in seconds.

#### Acceptance Criteria

1. WHEN the database is initialized at startup, THE bot SHALL invoke
   `_download_db_from_gcs()` AND SHALL tolerate any failure outcome by allowing
   SQLAlchemy to create a fresh local database.
2. WHEN `_download_db_from_gcs()` is called, THE bot SHALL emit exactly one structured
   log line of the form
   `GCS_SYNC op=download outcome=<outcome> duration_ms=<n> bytes=<n> detail="..."`
   where `<outcome>` is one of
   `ok | skipped | import_error | auth_error | forbidden | not_found | network_error | unknown_error`.
3. WHEN `_upload_db_to_gcs()` is called, THE bot SHALL emit exactly one structured log
   line of the form
   `GCS_SYNC op=upload outcome=<outcome> duration_ms=<n> bytes=<n> detail="..."`
   using the same outcome enumeration as download.
4. IF the `google-cloud-storage` package cannot be imported, THEN THE bot SHALL set
   `outcome=import_error`, SHALL update `_last_gcs_sync`, AND SHALL emit the structured
   `GCS_SYNC` log line (i.e. SHALL NOT silently swallow the `ImportError`).
5. IF `google.auth.exceptions.DefaultCredentialsError` is raised during a GCS call,
   THEN THE bot SHALL set `outcome=auth_error`.
6. IF `google.api_core.exceptions.Forbidden` is raised during a GCS call, THEN THE bot
   SHALL set `outcome=forbidden`.
7. IF `google.api_core.exceptions.NotFound` is raised during a GCS call OR the target
   blob does not exist on download, THEN THE bot SHALL set `outcome=not_found`
   (for raised exceptions) or `outcome=skipped` (for blob-not-exists on download).
8. IF a `TimeoutError`, `ConnectionError`, or `OSError` is raised during a GCS call,
   THEN THE bot SHALL set `outcome=network_error`.
9. IF any other exception is raised during a GCS call, THEN THE bot SHALL set
   `outcome=unknown_error` AND SHALL include `type(e).__name__: str(e)` in `detail`.
10. THE `_download_db_from_gcs()` and `_upload_db_to_gcs()` functions SHALL NOT re-raise
    any exception to the caller.
11. THE bot SHALL maintain a module-level `_last_gcs_sync` value that is set to the most
    recent `GcsSyncStatus` snapshot after every download or upload attempt.
12. THE `/health` endpoint SHALL expose `last_gcs_sync` as a serialized `GcsSyncStatus`
    snapshot (or `None` if no sync has been attempted yet).
13. WHERE `last_gcs_sync.outcome` is anything other than `ok` or `skipped`, THE
    `/health` endpoint SHALL report `status=degraded`.
14. WHEN a user successfully registers via `create_or_update_user`, THE bot SHALL invoke
    `_upload_db_to_gcs()` immediately after commit so that the registration is persisted
    to GCS within the same request.
15. WHEN the application shuts down (`close_database`), THE bot SHALL invoke
    `_upload_db_to_gcs()` once before disposing the engine.
16. WHILE GCS is unreachable, THE bot SHALL continue accepting webhooks and SHALL serve
    requests from the in-memory / local-SQLite state, with `/health` reporting
    `status=degraded` until a successful sync occurs.

### Requirement 3: Phase 2 LLM correctness — no placeholder tickets

**User Story:** As a QA tester, I want my video-attached bug to produce a ticket with
real reproduction steps derived from the video frames, not a placeholder like
"See attached media for reproduction steps". As an on-call engineer, I want loud ERROR
logs when Phase 2 misbehaves and automatic fall-back to Phase 1 so the tester always gets
a usable ticket.

#### Acceptance Criteria

1. THE Phase 2 prompt SHALL list all 11 fields (`is_valid`, `title`, `actual_behavior`,
   `expected_behavior`, `steps_to_reproduce`, `device`, `operating_system`, `environment`,
   `app_version`, `bug_type`, `priority`) as MANDATORY in the exact order specified in
   design Theme 3.1.
2. THE Phase 2 prompt SHALL instruct the LLM to use the literal string `Not specified`
   (or `["Not specified"]` for `steps_to_reproduce`) for genuinely unknown values AND
   SHALL forbid the placeholder string `See attached media for reproduction steps`,
   empty arrays, and `null` values for required fields.
3. THE Phase 2 prompt SHALL include the QA tester's original brief verbatim, including any
   `[Tag]` prefix preserved by Requirement 1.
4. THE Phase 2 LLM call SHALL be made with `max_tokens=6000`.
5. WHEN `_clean_json_response` is called on a Phase 2 response, THE bot SHALL strip any
   surrounding markdown fences before counting braces / brackets / unterminated strings.
6. IF `_clean_json_response` detects any of: open braces (`count('{') > count('}')`),
   open brackets (`count('[') > count(']')`), or an unterminated string,
   THEN THE bot SHALL log `PHASE2_TRUNCATED detections=<list> preview="<last 200 chars>"`
   at ERROR level AND SHALL raise `Phase2TruncatedError`.
7. THE `_clean_json_response` function SHALL NOT silently rebuild truncated JSON by
   appending closing braces, closing brackets, or closing quote characters AND SHALL NOT
   attempt any other form of JSON reconstruction; the only response to detected truncation
   is to log and raise.
8. WHEN `enrich_with_media` catches `Phase2TruncatedError`, THE bot SHALL log a fall-back
   message at ERROR level AND SHALL immediately return the Phase 1 result instead of the
   Phase 2 result, without any further parse, repair, or recovery attempt.
9. THE bot SHALL NOT retry the Phase 2 LLM call after a `Phase2TruncatedError`.
10. THE `_detect_default_stuffing(report)` function SHALL return `is_stuffed=True` if and
    only if at least 2 of the following conditions hold:
    (a) `steps_to_reproduce` equals or is a subset of the placeholder set
    `{"See attached media for reproduction steps", "Review attached media"}`;
    (b) `actual_behavior` equals `"See attached media for details."`;
    (c) `expected_behavior` equals `"Expected normal behavior."`;
    (d) `device == "Not specified"` AND `operating_system == "Not specified"` AND
    `app_version == "Not specified"`.
11. WHEN `_detect_default_stuffing` returns `is_stuffed=True` for a Phase 2 report,
    THEN THE bot SHALL log `PHASE2_DEFAULT_STUFFED reasons=<labels>` at ERROR level
    AND SHALL return the Phase 1 result instead of the Phase 2 result.
12. WHEN the Phase 2 fall-back path is taken (truncation or default-stuffing), THE bot
    SHALL still create exactly one OpenProject ticket using the Phase 1 result so that
    the tester always receives a ticket.
13. THE `_detect_default_stuffing` function SHALL be a pure function with no side effects.
14. THE Phase 2 LLM call SHALL be made with `client_timeout=45s` and an outer
    `asyncio.wait_for(..., timeout=50s)` ceiling.
15. IF Phase 2 exceeds the 50s asyncio ceiling, THEN THE bot SHALL log
    `PHASE2_SLOW outcome=timeout duration_ms=50000 frames=<n>` at ERROR level AND SHALL
    fall back to the Phase 1 result (same contract as `Phase2TruncatedError`).
16. THE bot SHALL NOT retry the Phase 2 LLM call after a `PHASE2_SLOW` timeout.
17. THE Phase 2 SLO SHALL be: text-only bugs complete in 5–10s end-to-end, photo bugs in
    10–20s, video bugs (up to 20 frames) in 15–30s, hard ceiling 50s.

### Requirement 4: Accurate priority classification

**User Story:** As a QA tester, I want the bug priority to reflect the keywords I actually
use: HIGH for words like `hangs`, `crashes`, `stuck`, `blank screen`, `unresponsive`; LOW
for words like `intermittent`, `sometimes`, `rarely`, `minor`, `cosmetic`. As an on-call
engineer, I want ambiguous combinations like "intermittent crash" to default to MEDIUM
with a `PRIORITY_AMBIGUOUS` audit log so I can review them later.

#### Acceptance Criteria

1. WHEN the priority validator receives a non-string or empty value, THE validator SHALL
   return `PriorityLevel.MEDIUM`.
2. WHEN the lowercased trimmed input equals `"high"`, `"medium"`, or `"low"` exactly,
   THEN THE validator SHALL return the corresponding `PriorityLevel` value via the
   fast-path branch.
3. WHEN the input does not match the fast path, THE validator SHALL apply the HIGH
   word-boundary regex over the case-folded input. The HIGH whitelist SHALL contain
   exactly: `high`, `broken`, `completely failing`, `data loss`, `fatal`, `severe`,
   `crash`, `crashes`, `crashing`, `hang`, `hangs`, `hanging`, `stuck`, `stuck on`,
   `freezes`, `frozen`, `not responsive`, `unresponsive`, `not responding`,
   `blank screen`, `white screen`, `black screen`.
4. WHEN the input does not match the fast path, THE validator SHALL also apply the LOW
   word-boundary regex over the case-folded input. The LOW whitelist SHALL contain
   exactly: `low`, `minor`, `cosmetic`, `trivial`, `nit`, `intermittent`,
   `intermittently`, `sometimes`, `occasionally`, `rarely`, `slight misalignment`,
   `slightly`.
5. IF both the HIGH regex and the LOW regex match the same input, THEN THE validator
   SHALL return `PriorityLevel.MEDIUM` AND SHALL log
   `PRIORITY_AMBIGUOUS: both HIGH and LOW keywords matched in <input> — defaulting to MEDIUM`
   at WARNING level.
6. WHEN only the HIGH regex matches, THEN THE validator SHALL return `PriorityLevel.HIGH`.
7. WHEN only the LOW regex matches, THEN THE validator SHALL return `PriorityLevel.LOW`.
8. WHEN neither regex matches, THEN THE validator SHALL return `PriorityLevel.MEDIUM`.
9. THE validator SHALL match HIGH and LOW keywords on word boundaries (`\b`), so that
   `"highlighted bug"` SHALL NOT resolve to HIGH and `"Medium-High"` SHALL resolve to
   MEDIUM (no boundary-`high` token).
10. THE validator SHALL produce the following outputs for the canonical behaviour table
    rows from design §5.1:
    `"High" → HIGH`, `"Medium" → MEDIUM`, `"Low" → LOW`,
    `"Medium-High" → MEDIUM`, `"highlighted bug" → MEDIUM`,
    `"app crashes constantly" → HIGH`, `"data loss observed" → HIGH`,
    `"slight misalignment" → LOW`, `"minor cosmetic issue" → LOW`,
    `"app hangs on login screen" → HIGH`, `"stuck on OTP screen" → HIGH`,
    `"blank screen after tap" → HIGH`, `"app is not responding" → HIGH`,
    `"intermittent crash" → MEDIUM` (with `PRIORITY_AMBIGUOUS` log),
    `"screen freezes intermittently" → MEDIUM` (with `PRIORITY_AMBIGUOUS` log),
    `"sometimes crashes on payment" → MEDIUM` (with `PRIORITY_AMBIGUOUS` log),
    `"rarely happens, cosmetic" → LOW`.

### Requirement 5: Deployment hygiene — env-var validation, build marker, env-vars file

**User Story:** As an on-call engineer, I want a startup validator that warns me when env
vars look corrupted (whitespace, embedded `=`, empty required values). As a developer, I
want a `BUILD_MARKER` log line at startup and a corresponding `/health.build_marker`
field so I can confirm the new image actually shipped. As a developer, I want every deploy
to use `--env-vars-file env.yaml` so the RC2 space-separator footgun is structurally
impossible. Every deploy is gated on the user sign-off in Phase B of the rollout plan.

#### Acceptance Criteria

1. WHEN the FastAPI lifespan startup runs, THE bot SHALL invoke `validate_env_vars(settings)`
   exactly once after `get_settings()` and before the rest of bring-up.
2. THE env validator SHALL NEVER raise an exception AND SHALL NEVER mutate the `settings`
   object.
3. THE env validator SHALL return a `list[str]` of warning messages.
4. THE env validator SHALL log every returned warning at WARNING level prefixed by
   `ENV_VALIDATION:` so the warnings are greppable in `/logs`.
5. WHEN the env validator finds no issues, THE env validator SHALL log
   `ENV_VALIDATION: all checks passed` at INFO level so that the wired-up validator can
   be confirmed in production.
6. THE env validator SHALL flag any required setting whose value is empty.
7. THE env validator SHALL flag any string value that contains literal whitespace, `\n`,
   or `\r`.
8. THE env validator SHALL flag any value that contains an embedded `=` followed by an
   `UPPER_SNAKE` token (the `KEY1=valKEY2=val` corruption signature from RC2).
9. THE env validator SHALL flag `LLM_API_KEY` if it does not start with the expected
   gateway prefix `sk-`.
10. THE env validator SHALL flag `DEMO_SPACE_ID` if it does not look like a Google Chat
    space id (alphanumeric plus `-` and `_`).
11. WHEN the lifespan startup runs, THE bot SHALL emit exactly one log line of the form
    `BUILD_MARKER: <git-sha-or-build-time>` so that the deployed image identity is
    greppable in `/logs`.
12. THE `/health` endpoint SHALL expose the same value as `build_marker` (a non-empty
    string after a successful startup).
13. WHERE the deploy uses environment variables, THE deploy command SHALL use
    `gcloud run deploy ... --env-vars-file env.yaml` AND SHALL NOT use
    `--set-env-vars` with space-separated values.
14. THE `env.yaml` template SHALL contain exactly one entry per env var, each value as a
    single-line YAML scalar with no trailing whitespace and no embedded `=` or newline.
15. WHEN any deploy is initiated, THE rollout SHALL gate the build/push on user sign-off
    at Phase B of the rollout plan; no `gcloud builds submit` SHALL run before the user
    explicitly says "deploy".
16. WHERE `/health.build_marker` does not match the sha emitted by the latest known
    deploy, THE on-call engineer SHALL treat the deploy as failed AND SHALL roll back
    to revision `qa-bugbot-00026-btk` per Phase G of the rollout plan.

### Requirement 6: Secret hygiene — no leaked keys in repo

**User Story:** As a developer, I want `.env.example` to ship with placeholders only, and
I want a pre-commit hook that rejects any `.env*` file containing token-like prefixes
outside the placeholder pattern, so that real gateway keys never enter the repo again.

#### Acceptance Criteria

1. THE `.env.example` file SHALL contain only placeholder values for sensitive fields,
   specifically `LLM_API_KEY=sk-REPLACE_WITH_YOUR_GATEWAY_TOKEN`,
   `DEFAULT_OPENPROJECT_API_KEY=REPLACE_WITH_DEMO_SPACE_API_KEY`, and
   `DEMO_SPACE_ID=REPLACE_WITH_GOOGLE_CHAT_SPACE_ID`.
2. THE `.env.example` file SHALL NOT contain any real gateway token, real OpenProject API
   key, or real Google Chat space id.
3. THE `.gitignore` file SHALL exclude `.env` and `*.env`-style files while permitting
   `.env.example` as a deliberate exception.
4. THE `.dockerignore` file SHALL exclude both `.env` and `.env.example`.
5. THE `.gcloudignore` file SHALL exclude `.env`.
6. WHERE Phase C of the rollout plan is executed, THE developer SHALL install a
   pre-commit hook that scans staged `.env*` files.
7. WHEN the pre-commit hook scans a staged `.env*` file, THE hook SHALL match the regex
   `\b(sk|pk|api|key|token)[-_][A-Za-z0-9]{16,}\b` against the file contents.
8. IF the regex matches a line AND that line does not match an allow-listed placeholder
   pattern (`REPLACE_WITH_*`, `<single-line-token>`, or similar), THEN THE pre-commit
   hook SHALL abort the commit AND SHALL print which line tripped the check.
9. WHEN a staged `.env*` file contains only placeholder forms, THE pre-commit hook SHALL
   allow the commit to proceed.

### Requirement 7: Local-first verification gating every deploy

**User Story:** As a developer, I want a `scripts/preflight.sh` (and `.bat` for Windows)
that runs every check before any deploy, three test tiers (unit / synthetic webhook /
manual integration) that all pass locally before any image is built, and an explicit
sign-off gate after Phase B so that no deploy escapes local verification.

#### Acceptance Criteria

1. THE repository SHALL include a runnable script at `scripts/preflight.sh` (with a
   `.bat` variant for Windows) that executes the local verification sequence.
2. WHEN `scripts/preflight.sh` runs, THE script SHALL execute the following steps in
   order: `git status --porcelain` (fail on dirty tree if about to deploy), invoke the
   env validator on the current settings, run `python -m pytest -q` (Tier 1), run
   `python scripts/synthetic_webhook.py --scenario all` (Tier 2),
   run `docker build -t qa-bugbot:local --no-cache .`, run
   `docker run -p 8080:8080 --env-file .env qa-bugbot:local`, and verify
   `curl localhost:8080/health` returns `status==healthy` with `last_gcs_sync` and
   `build_marker` populated.
3. THE Tier 1 unit suite SHALL include tests covering:
   `test_validate_env_vars_detects_corruption`,
   `test_validate_env_vars_clean_input_passes`,
   `test_download_db_each_outcome`,
   `test_upload_db_each_outcome`,
   `test_clean_json_response_clean_input_unchanged`,
   `test_clean_json_response_raises_on_truncation`,
   `test_enrich_with_media_falls_back_to_phase1_on_truncation`,
   `test_enrich_with_media_falls_back_to_phase1_on_default_stuffing`,
   `test_detect_default_stuffing_all_paths`,
   `test_priority_validator_word_boundary`,
   `test_priority_validator_ambiguous_logs_warning`,
   `test_phase2_token_budget_invariance`,
   `test_extract_bucket_regex`,
   `test_resolve_tag_fuzzy_threshold`,
   `test_extract_bucket_preserves_original_text`.
4. THE Tier 2 script `scripts/synthetic_webhook.py` SHALL implement scenarios S1 through
   S8 as defined in design §6 Tier 2 (empty brief + photo, `[LMS Webview]` brief,
   `[step 3]` brief, 20-frame video, photo-only, registration-after-restart, RC2 env
   corruption reproduction, truncated Phase 2 fall-back).
5. THE Tier 2 script SHALL exit with a non-zero status code on any scenario failure.
6. WHILE Tier 2 runs, THE Tier 2 script SHALL boot the FastAPI app via
   `httpx.ASGITransport` AND SHALL mock `OpenProjectClient.create_ticket`,
   `GeminiClient.client.chat.completions.create`, and `google.cloud.storage.Client`.
7. THE Tier 3 integration smoke test SHALL be manual and opt-in (Phase F of rollout)
   AND SHALL NOT be part of CI.
8. IF either Tier 1 or Tier 2 fails locally, THEN THE rollout SHALL NOT advance to
   Phase C (commit checkpoint), Phase D (build/deploy), or beyond.
9. WHERE Tier 1 and Tier 2 both succeed, THE rollout SHALL still require all other
   rollout gates (Phase B sign-off, Phase C commit checkpoint with pre-commit hook
   passing, and the Phase E `BUILD_MARKER` / `/health` checks) to pass before any
   subsequent phase advances; Tier-success alone SHALL NOT auto-advance the rollout.
10. WHEN Phase B (user sign-off) has not occurred, THEN THE rollout SHALL NOT advance to
    Phase D (build/deploy).
11. WHERE any check in Phase E or Phase F fails after deploy, THE rollback SHALL target
    Cloud Run revision `qa-bugbot-00026-btk` via
    `gcloud run services update-traffic qa-bugbot --to-revisions qa-bugbot-00026-btk=100`,
    AND THE rollback SHALL be prepared (rollback target identified and command staged)
    rather than executed automatically; an operator SHALL run the rollback command
    explicitly.

### Requirement 8: Structured observability for every external service call

**User Story:** As an on-call engineer, I want every external service call (GCS, LLM,
OpenProject) to emit a structured log line with outcome and duration so that I can grep
`/logs` to triage failures without GCP console access.

#### Acceptance Criteria

1. WHEN the bot performs a GCS download attempt OR a GCS upload attempt, THE bot SHALL
   emit exactly one structured log line of the form
   `GCS_SYNC op=<download|upload> outcome=<…> duration_ms=<n> bytes=<n> detail="..."`
   per attempt (per Requirement 2). WHERE a single startup or registration flow performs
   both a download and an upload, each attempt SHALL emit its own single `GCS_SYNC` line
   with its own `op=` value (one for `op=download`, one for `op=upload`).
2. WHEN the bot completes a Phase 1 LLM call, THE bot SHALL emit a log line containing
   `Phase 1 LLM response` and the response preview (existing behaviour, preserved).
3. WHEN the bot completes a Phase 2 LLM call, THE bot SHALL emit a log line containing
   `Phase 2 LLM response` and the response preview (existing behaviour, preserved).
4. WHEN the bot makes any HTTP call through `OpenProjectClient`, THE bot SHALL wrap the
   call to emit a structured log line of the form
   `OP_CALL outcome=<ok|client_error|server_error|network_error|unknown_error> duration_ms=<n>`.
5. THE structured log lines `GCS_SYNC`, `Phase 1 LLM response`, `Phase 2 LLM response`,
   and `OP_CALL` SHALL each be greppable as a single line in `/logs`.
6. THE bot SHALL emit exactly one structured `GCS_SYNC` line per sync attempt (not zero,
   not multiple) at the end of that attempt; THE bot SHALL NOT restrict `GCS_SYNC`
   emission to a strictly "in-progress" window, so synthetic-test or smoke-test code
   paths that emit `GCS_SYNC` outside an active live sync (e.g. when replaying a captured
   status snapshot) SHALL still be permitted to log a single well-formed `GCS_SYNC` line.
7. THE Tier 2 synthetic webhook scenarios SHALL each assert that at least one of the
   relevant structured log lines (GCS_SYNC, Phase 1, Phase 2, OP_CALL) appears in the
   captured logs for the scenario.

## Out of Scope

The following are explicitly NOT in this spec and SHALL NOT be addressed by this fix:

- **Architectural changes**: FastAPI, SQLAlchemy with aiosqlite, the OpenAI-compatible
  LLM gateway abstraction, and the two-phase (text-then-media) pipeline structure all
  remain as-is.
- **No new external runtime dependencies** in `requirements.txt`. `hypothesis` may be
  added to a dev-only `requirements-dev.txt`.
- **No move to Cloud SQL or any alternate persistence backend**. SQLite + GCS sync stays.
- **No reduction of the video frame extraction budget**. The 20-frames-per-video extraction
  in `_extract_video_frames` remains; `max_tokens=6000` is sized for this budget.
- **No rotation of the company gateway key** (`LLM_API_KEY`). The leaked example value
  was a company-issued gateway token, not a customer-facing or production-data secret;
  rotation is not required (per Resolved Q3 in the design doc). The fix is to ship
  placeholders in `.env.example` and add the pre-commit hook only.
- **No LLM model swap**. The bot stays on `google/gemini-2.5-flash` via the IndiaMART
  LLM gateway at `https://imllm.intermesh.net/v1`.
- **No retry of Phase 2 on truncation or default-stuffing**. The fall-back is to use the
  Phase 1 result (per Resolved Q2 in the design doc); a retry loop would mask the
  upstream regression.
- **No bucket disambiguation via LLM call**. Free-text bucket extraction is purely
  Python/regex/scoring; we do NOT call the LLM gateway for routing decisions (would add
  2–3s of latency and cost).

## Verification Mapping

The table below maps each requirement to the design Theme(s) and Property/Error
scenario(s) that implement it. This makes the traceability from design → requirements
explicit before tasks are derived.

| Requirement | Theme(s) | Property/Error scenario(s) |
|---|---|---|
| Requirement 1 — Reliable bucket-tag routing | Theme 4 (4.1, 4.2, 4.3, 4.4 test cases T-BR-1..10) + new Theme 4.5/4.6/4.7 free-text extraction layer | Property 3 (typo tolerance + brief preservation); Error E6 (regex reject), Error E7 (no resolution → device fallback) |
| Requirement 2 — Persistent registration with structured GCS sync observability | Theme 2 (2.1 download, 2.2 upload, 2.3 `/health` extension) | Property 2 (registration survives restarts); Property 5 (every external call emits a log line); Error E1 (download fail), Error E2 (upload fail) |
| Requirement 3 — Phase 2 LLM correctness — no placeholder tickets | Theme 3 (3.1 prompt, 3.2 `max_tokens=6000`, 3.3 `Phase2TruncatedError`, 3.4 `_detect_default_stuffing`) | Property 1 (non-default critical fields); Property 6 (token budget invariance); Error E4 (truncation → fall-back), Error E5 (default-stuffing → fall-back) + new Property 7 (latency budget) + Error E5.1 (timeout) |
| Requirement 4 — Accurate priority classification | Theme 5 (5.1 word-boundary regex, behaviour table, `PRIORITY_AMBIGUOUS` log) | Property 4 (priority defaults to Medium unless HIGH whitelist fires; tie-breaker → MEDIUM with audit log) |
| Requirement 5 — Deployment hygiene — env vars + stale image prevention | Theme 1 (1.1 `--env-vars-file`, 1.2 env validator, `BUILD_MARKER`, `/health.build_marker`) | Error E3 (env-var corruption detected), Error E8 (stale image deploy detected via `BUILD_MARKER` mismatch) |
| Requirement 6 — Secret hygiene — no leaked keys in repo | Theme 1 (1.3 `.env.example` placeholders, pre-commit hook) | Resolved Q3 in design (RC7 resolution; no rotation required, placeholder + hook is sufficient) |
| Requirement 7 — Local-first verification gating every deploy | Theme 6 (Tier 1 unit, Tier 2 synthetic webhook, Tier 3 manual smoke); Theme 1.4 (`scripts/preflight.sh`) | Rollout Phases A (local verification), B (sign-off gate), C (commit checkpoint), D (deploy), G (rollback) |
| Requirement 8 — Structured observability for every external service call | Theme 2 (`GCS_SYNC` line); Theme 3 (existing `Phase 1/2 LLM response` lines); new `OP_CALL` wrapper around `OpenProjectClient` | Property 5 (every external call emits a log line) |
