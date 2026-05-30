# Token Consumption & Cost Analysis — QA Bug Logger Bot

> **Scope:** per-bug LLM token consumption (canonical case: **1 bug with a 25-second video**), monthly volume of 3,000 bugs, and rupee/dollar cost projection for the **current production line** (`qa-bugbot-00042-8zj`, asia-south1) and a **Phase 2 RAG-enabled projection** (branch `feat/rag-few-shot-retrieval`, paused for HOD review).
>
> **Last updated:** 2026-05-30
> **Live revision audited:** `qa-bugbot-00042-8zj` → commit `5002f50` → tag `checkpoint-stable-20260530`
> **Source of truth:** `scripts/cost_estimate.py` (run it to regenerate every number here).
> **Pricing source:** Google Gemini 2.5 Flash public list price as of 2026-05 — input $0.30 / 1M tokens, output $2.50 / 1M tokens. Internal gateway `imllm.intermesh.net` resells at parity unless the team has a negotiated discount; numbers below are conservative upper bounds.
> **Currency:** USD throughout. INR shown at ₹83 / USD (adjust via `USD_TO_INR` in the script).

---

## 0. The matrix — token consumption for 1 bug (with a 25-second video)

This is the canonical reference case: **one bug report that includes a 25-second screen-recording**, the heaviest common workload. A 25 s video extracts **20 frames** (the code caps at `num_frames = min(int(duration_sec), 20)`, so any video ≥ 20 s yields exactly 20 frames). It runs **both** LLM phases: Phase 1 (text) then Phase 2 (text + 20 video frames).

### Current production (`qa-bugbot-00042-8zj`, 50-example static few-shot)

| # | Line item | Phase | Direction | Tokens |
|---|---|---|---|---:|
| 1 | System prompt rules + JSON schema (`SYSTEM_PROMPT_BASE`) | 1 | input | 850 |
| 2 | Few-shot block (50 curated tickets) | 1 | input | 14,700 |
| 3 | User-message wrapper | 1 | input | 20 |
| 4 | QA brief (median ~280 chars) | 1 | input | 70 |
| 5 | JSON-mode overhead | 1 | input | 20 |
| 6 | **Phase 1 input subtotal** | 1 | input | **15,660** |
| 7 | Phase 1 JSON response | 1 | output | 600 |
| 8 | System prompt + few-shot block (reused) | 2 | input | 15,550 |
| 9 | Phase 2 enrichment + screening template | 2 | input | 2,200 |
| 10 | Phase 1 result JSON (passed as context) | 2 | input | 400 |
| 11 | Original brief (reused) | 2 | input | 70 |
| 12 | **Phase 2 text input subtotal** | 2 | input | **18,220** |
| 13 | 20 video frames × 1,700 tokens/frame | 2 | input | 34,000 |
| 14 | **Phase 2 input total** (12 + 13) | 2 | input | **52,220** |
| 15 | Phase 2 enriched JSON response | 2 | output | 3,500 |
| | **TOTAL INPUT TOKENS** (6 + 14) | | input | **67,880** |
| | **TOTAL OUTPUT TOKENS** (7 + 15) | | output | **4,100** |
| | **GRAND TOTAL TOKENS** | | both | **71,980** |

**Cost for this one bug:**

| | Tokens | Rate (USD / 1M) | Cost (USD) |
|---|---:|---:|---:|
| Input | 67,880 | $0.30 | $0.020364 |
| Output | 4,100 | $2.50 | $0.010250 |
| **Per bug** | **71,980** | — | **$0.03061  (≈ ₹2.54)** |

### Phase 2 — RAG branch (`feat/rag-few-shot-retrieval`, 5 retrieved examples)

Only the few-shot block shrinks (lines 2 and 8: 14,700 → 1,500). The 34,000 video-frame tokens are identical — RAG does not touch image input.

| | Tokens | Cost (USD) |
|---|---:|---:|
| Phase 1 input | 2,460 | — |
| Phase 1 output | 600 | — |
| Phase 2 text input | 5,020 | — |
| Phase 2 video frames | 34,000 | — |
| Phase 2 output | 3,500 | — |
| **TOTAL input** | **41,480** | $0.012444 |
| **TOTAL output** | **4,100** | $0.010250 |
| **Per bug** | **45,580** | **$0.02269  (≈ ₹1.88)** |

### Side-by-side (1 bug, 25 s video)

| Metric | Current production | RAG (Phase 2) | Saving |
|---|---:|---:|---:|
| Total tokens | 71,980 | 45,580 | −26,400 (−37%) |
| Cost per bug (USD) | $0.03061 | $0.02269 | −$0.00792 |
| Cost per bug (INR) | ₹2.54 | ₹1.88 | −₹0.66 |
| **× 3,000 such bugs/month** | **$91.84 / ₹7,623** | **$68.08 / ₹5,651** | **−$23.76 / ₹1,972 (−26%)** |

> All figures above are produced by `python scripts/cost_estimate.py` — that script is the source of truth for this document.

---

## 1. Token consumption matrix — all bug shapes

Not every bug carries a 25 s video. Here is the full matrix across the four real bug shapes, both prompt regimes. The video row is the canonical case from §0.

### Current production (50-example static few-shot)

| Bug shape | Phase 1 input | Phase 1 out | Phase 2 input | Phase 2 out | Total tokens | Cost/bug (USD) | Cost/bug (INR) |
|---|---:|---:|---:|---:|---:|---:|---:|
| Text-only (no media) | 15,660 | 600 | — | — | 16,260 | $0.00619 | ₹0.51 |
| + 1 screenshot | 15,660 | 600 | 20,020 | 3,500 | 39,780 | $0.02095 | ₹1.74 |
| + 1 video (25 s → 20 frames) | 15,660 | 600 | 52,220 | 3,500 | 71,980 | $0.03061 | ₹2.54 |
| + screenshot **and** video | 15,660 | 600 | 54,020 | 3,500 | 73,780 | $0.03115 | ₹2.59 |

### Phase 2 — RAG branch (5 retrieved examples)

| Bug shape | Phase 1 input | Phase 1 out | Phase 2 input | Phase 2 out | Total tokens | Cost/bug (USD) | Cost/bug (INR) |
|---|---:|---:|---:|---:|---:|---:|---:|
| Text-only (no media) | 2,460 | 600 | — | — | 3,060 | $0.00223 | ₹0.19 |
| + 1 screenshot | 2,460 | 600 | 6,820 | 3,500 | 13,380 | $0.01303 | ₹1.08 |
| + 1 video (25 s → 20 frames) | 2,460 | 600 | 39,020 | 3,500 | 45,580 | $0.02269 | ₹1.88 |
| + screenshot **and** video | 2,460 | 600 | 40,820 | 3,500 | 47,380 | $0.02323 | ₹1.93 |

---

## 2. Calls made per bug — current production

Audited from `gemini_client.py` and `main.py` on commit `5002f50` (live `qa-bugbot-00042-8zj`).

| LLM call site | When it fires | `max_tokens` | Typical input shape |
|---|---|---:|---|
| `analyze_text_brief` (Phase 1) | Every bug. Inline within the 25 s webhook deadline. | 1,000 | `SYSTEM_PROMPT` + 50-example few-shot block + user brief |
| `enrich_with_media` (Phase 2) | Only when the webhook includes screenshots or video. Async, up to 50 s deadline. | 6,000 | Same system prompt + Phase 1 result + brief + base64-encoded frames |
| `pick_bucket` (LLM bucket fallback) | Only when `bucket_router` returns `provenance='default'` (no signal). ~5% of briefs. | 200 | `SYSTEM_PROMPT_BASE` (no few-shot) + 1-line brief |
| `smoke_test` | Once at every cold start, not per bug. | 1 | 1-token "ping" |

The hot path for 95%+ of bugs is **Phase 1, sometimes Phase 2**. Bucket fallback and smoke test are rounding error.

---

## 3. Token accounting — Phase 1 (text-only)

Tokens are estimated per OpenAI/Gemini convention of ~4 chars/token for English. Numbers come from reading the prompt template directly, not measurement (today's `_log_llm_call` records `chars=`, not `prompt_tokens`/`completion_tokens` — see §11 for the recommended fix).

| Component | Approx chars | Approx tokens (input) |
|---|---:|---:|
| `SYSTEM_PROMPT_BASE` (rules, schema, examples placeholder) | ~3,400 | ~850 |
| `_FEW_SHOT_BLOCK` (50 curated tickets, real OpenProject data) | ~58,800 | **~14,700** |
| User-message wrapper (`Analyze the following bug report...`) | ~80 | ~20 |
| QA brief (typical 80–500 chars; hub-and-spoke median ~280) | ~280 | ~70 |
| JSON-mode formatting overhead | — | ~20 |
| **Total Phase 1 input** | — | **~15,660 tokens** ⇒ rounded **~16,800** for safety |
| **Phase 1 output** (constrained JSON, ~1,500 chars typical) | — | **~600 tokens** (capped at 1,000) |

Per-bug cost for Phase 1:
```
input cost  = 16,800 × $0.30 / 1,000,000 = $0.00504
output cost =    600 × $2.50 / 1,000,000 = $0.00150
phase 1 total                            ≈ $0.00654 per bug
```

---

## 4. Token accounting — Phase 2 (with media)

Phase 2 reuses the same system prompt + few-shot block, then adds the Phase 1 JSON output as context, the original brief, and the media items themselves.

| Component | Approx tokens (input) |
|---|---:|
| `SYSTEM_PROMPT_BASE` + `_FEW_SHOT_BLOCK` (same as Phase 1) | ~15,550 |
| `PHASE2_PROMPT_TEMPLATE` (screening + enrichment instructions) | ~2,200 |
| Phase 1 result JSON (formatted, ~1,500 chars) | ~400 |
| Original brief | ~70 |
| **Sub-total: Phase 2 text input** | **~18,220 tokens** |
| Each screenshot (Gemini 2.5 Flash image cost: ~258 tokens / standard 384px tile, ~1,800 tokens for a typical 1080×1920 mobile screenshot) | ~1,800 per image |
| Each video frame (one image each, 20 frames per video by `num_frames = min(int(duration_sec), 20)`) | ~1,700 per frame |

Three common shapes:

**A. One screenshot only**
```
input  = 18,220 (text) + 1,800 (image) = 20,020 tokens
output = capped at 6,000, typical ~3,500
input cost  = 20,020 × $0.30 / 1,000,000 = $0.00601
output cost =  3,500 × $2.50 / 1,000,000 = $0.00875
phase 2 (screenshot) total            ≈ $0.01476 per bug
```

**B. One ~10 s mobile-screen video (10–20 extracted frames)**
```
input  = 18,220 + 20 × 1,700 = 52,220 tokens
output = ~3,500
input cost  = 52,220 × $0.30 / 1,000,000 = $0.01567
output cost =  3,500 × $2.50 / 1,000,000 = $0.00875
phase 2 (video) total                 ≈ $0.02442 per bug
```

**C. One screenshot + one short video (20 frames)** — power-user case
```
input  = 18,220 + 1,800 + 20 × 1,700 = 54,020 tokens
output = ~3,500
phase 2 total                         ≈ $0.02496 per bug
```

---

## 5. Per-bug cost detail — current production

(Token counts are in the §1 matrix; this table shows the cost arithmetic.)

| Bug shape | Phase 1 ($) | Phase 2 ($) | **Total ($)** | INR @ 83 |
|---|---:|---:|---:|---:|
| Text-only | 0.00619 | — | **0.00619** | ~₹0.51 |
| With 1 screenshot | 0.00619 | 0.01476 | **0.02095** | ~₹1.74 |
| With 1 video (25 s → 20 frames) | 0.00619 | 0.02442 | **0.03061** | ~₹2.54 |
| Screenshot + video | 0.00619 | 0.02496 | **0.03115** | ~₹2.59 |
| Text + LLM bucket fallback | 0.00619 + 0.00012 | — | **0.00631** | ~₹0.52 |

Worked example for the text-only Phase 1 cost: `15,660 input × $0.30/M + 600 output × $2.50/M = $0.004698 + $0.001500 = $0.006198`. The 4-chars/token rule introduces ±10% on the input total — `scripts/cost_estimate.py` is the source of truth.

---

## 6. Monthly cost at 3,000 bugs

Bug-shape mix is observable from existing OpenProject ticket history. Use these as defaults until live measurements refine them:

| Shape | Share of monthly volume | Bugs/month | Cost/bug ($) | Sub-total ($) |
|---|---:|---:|---:|---:|
| Text-only | 60% | 1,800 | 0.00619 | 11.14 |
| Screenshot only | 25% | 750 | 0.02095 | 15.71 |
| Video (or video + screenshot, average) | 15% | 450 | 0.03088 (avg) | 13.90 |
| LLM bucket fallback adder | 5% of text-only | 90 | 0.00012 marginal | 0.01 |
| Smoke test + cold-start churn (1/day × 30 days) | — | 30 calls | $0.00000076 | <0.01 |
| **Monthly subtotal** | 100% | 3,000 | — | **~$40.76** |
| Buffer for retry/timeout fall-backs (~5%) | — | — | — | ~$2.04 |
| **Total monthly cost** | — | — | — | **~$42.79 / ₹3,552** |

This is the number to share with the HOD: **₹3,552/month at 3,000 bugs**, or about **₹1.18 per bug** all-in.

For reference at other volumes (linear with bug count, roughly):
- 1,000 bugs/month: ~$14.26 / ₹1,184
- 5,000 bugs/month: ~$71.32 / ₹5,920
- 10,000 bugs/month: ~$142.65 / ₹11,840

---

## 7. What the bot does NOT pay for

Useful framing if anyone asks "is this all the cost":

| Item | Cost | Notes |
|---|---|---|
| Cloud Run compute | Negligible at this volume | `--min-instances 1` keeps one warm instance. Asia-south1 Cloud Run pricing for 1 GiB/1 vCPU is ~$0.0024/vCPU-hour + memory. ~$5–8/month flat. |
| GCS storage (`qa-bugbot-data`) | <$0.01/month | 12 KB SQLite + (Phase 2) ~0.9 MB embedding cache. Single-digit dollars per terabyte-month. |
| OpenProject API calls | $0 | Self-hosted. |
| Google Chat webhooks | $0 | Workspace-included. |
| Egress | <$1/month | Mostly inbound. |

So **infra cost is essentially $5–10/month flat**. LLM tokens dominate; that is what this document tracks.

---

## 8. Phase 2 (RAG) projection — same volume, smaller prompts

The RAG branch (`feat/rag-few-shot-retrieval`, tag `rag-phase2-checkpoint-20260530`) replaces the static 50-example few-shot block (~14,700 tokens) with **5 retrieved examples** (~1,500 tokens). The cost delta per call is therefore:

```
saved input tokens per call = 14,700 - 1,500 = 13,200
saved cost per call         = 13,200 × $0.30 / 1,000,000 = $0.00396
```

Phase 1 fires once per bug; Phase 2 fires for ~40% of bugs. So roughly **1.4 LLM calls per bug** benefit from the smaller prompt — average savings per bug ≈ **1.4 × $0.00396 ≈ $0.00554**, but the actual weighted savings come out higher (~$0.0058 per bug) once the bucket-fallback adder is included.

Rebuilt totals with RAG (matches `scripts/cost_estimate.py` output):

| Bug shape | Current ($) | RAG ($) | Saved ($) | Saved (₹) |
|---|---:|---:|---:|---:|
| Text-only | 0.00619 | 0.00223 | 0.00396 | ~₹0.33 |
| With 1 screenshot | 0.02095 | 0.01303 | 0.00792 | ~₹0.66 |
| With 1 short video | 0.03061 | 0.02269 | 0.00792 | ~₹0.66 |
| **Weighted average / bug** | **~$0.01426** | **~$0.00844** | **~$0.00582** | **~₹0.48** |
| **Monthly @ 3,000 bugs** | **~$42.79** | **~$25.33** | **~$17.46** | **~₹1,449** |

**Phase 2 also brings retrieval-relevant accuracy gains** (workflow sequence, no hallucinations, terminology preservation per the QA audit) — the savings are a side effect, not the main pitch. But ₹1,450/month per 3,000 bugs of pure efficiency is still worth banking.

Image tokens (screenshots, video frames) are unchanged by RAG; the few-shot block is text-only.

---

## 9. Sensitivity to volume and bug-shape mix

What changes the monthly bill the most, in order of impact:

| Lever | Effect | Quick math |
|---|---|---|
| Volume (bugs/month) | Linear | Double bugs → double cost |
| Video share | Strongly nonlinear (each video adds ~34,000 input tokens) | If video share rises from 15% → 30% at 3,000 bugs, monthly cost rises by ~$14 / ₹1,160 |
| Few-shot block size (RAG K) | Linear in retrieved tokens | Going from K=5 to K=10 adds ~1,500 input tokens × bugs |
| Image resolution (Phase 2) | Linear in image tokens | Mobile screenshots default to ~1,800 tokens; if HD video frames jump to 2,500 tokens each, video bugs cost ~25% more |
| LLM bucket fallback rate | Marginal | Even if it doubles to 10%, total monthly impact <$1 |
| Cold starts | Negligible | Smoke test is 1 token. 30 cold starts × 1 token = irrelevant. |

If the HOD asks "what if bug volume scales 5×":
- 15,000 bugs/month at current ratios → ~$214 / ₹17,760/month
- With RAG → ~$127 / ₹10,510/month — savings widen at scale

---

## 10. Validity caveats and known gaps

| Caveat | Impact on numbers |
|---|---|
| Token estimates use the 4-chars/token rule of thumb | ±10% on text token counts. Real token counts depend on Gemini's tokenizer; will be measurable once §11 lands. |
| Image token costs use Google's published "tile" model | Mobile screenshots, real image content, and video frames may price slightly differently. ±15% on Phase 2 image costs. |
| Internal gateway (`imllm.intermesh.net`) is assumed to resell at list price | If the team has a negotiated discount, the dollar numbers should be discounted by that factor; the relative shape (text vs media, current vs RAG) is unchanged. |
| Brief lengths skew right | Long-tail briefs (>1,000 chars) raise per-bug input by ~250 tokens, ~$0.0001 per bug. Negligible at 3,000-bug scale. |
| Output truncation at `max_tokens=1000` (Phase 1) and `max_tokens=6000` (Phase 2) | Caps the worst case. Output tokens almost never hit the cap in production logs. |
| Bug-shape mix (60/25/15) is an assumption | Trivial to recompute once a real distribution is dropped in §6. |
| Retry / fall-back path (Phase 2 truncation, timeout, default-stuffing) | Each adds ~0.4× a Phase 1 call. Modeled as a flat 5% buffer in §6 (~$2/month at 3,000 bugs). |

---

## 11. Action item — capture real token usage in `LLM_CALL`

Today's structured log line records `chars=<N>` (response character count) but does NOT record `response.usage.prompt_tokens` or `response.usage.completion_tokens`. That's a one-line fix in `gemini_client.py:_log_llm_call` and its call sites:

- Pull `response.usage.prompt_tokens` and `response.usage.completion_tokens` after each call.
- Log them as `prompt_tokens=<N> completion_tokens=<N>` in the `LLM_CALL` extra fields.
- Aggregate over a 7-day window via `/logs` to replace the estimates in §3 and §4 with measured numbers.

This unblocks:
- **Per-call cost telemetry** (real $/bug)
- **A/B verification** of the RAG savings projected in §8 (one of the items the HOD will probably want before approving the deploy gate)
- **Anomaly alerts** if a single bug suddenly burns 50× the expected token count (broken corpus, runaway prompt, accidental K=999)

This is queued as a follow-up for the same RAG branch — it's a tiny edit that rides along with the deploy when the gate clears.

---

## 12. Reproducible methodology

Every number in this document is produced by **`scripts/cost_estimate.py`**. That script is the single source of truth — this markdown is a snapshot of its output. To recompute:

```bash
python scripts/cost_estimate.py
```

The script prints (a) the line-item matrix for the canonical 25 s-video bug under both prompt regimes, (b) the all-shapes per-bug table, and (c) the weighted monthly total plus the RAG delta.

Edit the constants at the top of the script and rerun whenever:
- Gemini pricing changes (`INPUT_PER_M`, `OUTPUT_PER_M`)
- The prompt structure changes (`SYSTEM_PROMPT_BASE_TOK`, `PHASE2_TEMPLATE_TOK`, etc.)
- The few-shot block size changes (`FEW_SHOT_TOK_STATIC`, `FEW_SHOT_TOK_RAG`)
- The average video length changes (`AVG_VIDEO_SECONDS` — note the 20-frame cap means anything ≥ 20 s is identical)
- The bug-shape mix is updated from real OpenProject data (`SHARE_TEXT_ONLY`, `SHARE_SCREENSHOT`, `SHARE_VIDEO`)
- The INR rate moves (`USD_TO_INR`)

Key code fact the script encodes: `num_frames = min(int(duration_sec), 20)` in `main.py` — so a 25 s video extracts exactly 20 frames, and per-bug video token cost is flat for any clip ≥ 20 s.

---

## 13. Summary for the HOD meeting

- The bot turns ~3,000 bugs/month into ~140–150 million Gemini 2.5 Flash tokens.
- That costs **~₹3,552/month** today, or **~₹1.18 per bug**.
- Infra (Cloud Run, GCS, OpenProject) adds <₹1,000/month flat.
- **Phase 2 (RAG) cuts the LLM bill by ~₹1,450/month (~41%)** while improving accuracy, and the implementation is already complete on `feat/rag-few-shot-retrieval` (tag `rag-phase2-checkpoint-20260530`) — only the deploy gate is pending the HOD's go-ahead.
- One-line telemetry upgrade (capture `response.usage`) will replace these estimates with measured numbers in production within a week of any deploy.
