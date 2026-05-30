"""
Reproducibility script for TOKEN_COST_ANALYSIS.md.

Run from repo root:
    python scripts/cost_estimate.py

Recomputes per-bug and per-month cost projections under both the current
production prompt (50-example static few-shot) and the RAG branch's smaller
prompt (5 retrieved examples). Adjust the constants at the top whenever:
  - Gemini pricing changes
  - The prompt structure changes
  - The few-shot block size changes (RAG K, static count)
  - The bug-shape mix is refreshed from real OpenProject data

This script does NOT call any LLM. It is pure arithmetic.
"""
from dataclasses import dataclass


# ─────────────────────────────────────────────
# Editable constants
# ─────────────────────────────────────────────

# Gemini 2.5 Flash list price (USD per 1M tokens), as of 2026-05.
INPUT_PER_M = 0.30
OUTPUT_PER_M = 2.50
USD_TO_INR = 83.0

# Component sizes (audited from gemini_client.py at commit 5002f50).
SYSTEM_PROMPT_BASE_TOK = 850
FEW_SHOT_TOK_STATIC = 14_700      # 50 examples — current production
FEW_SHOT_TOK_RAG = 1_500          # 5 retrieved examples — Phase 2 branch
PHASE2_TEMPLATE_TOK = 2_200
P1_RESULT_JSON_TOK = 400
USER_BRIEF_TOK = 70               # median; long tail adds ~250 tok
USER_WRAPPER_TOK = 20             # "Analyze the following bug report..." wrapper
JSON_MODE_OVERHEAD_TOK = 20

# Phase 2 image tokens.
SCREENSHOT_TOK = 1_800            # typical 1080×1920 mobile screenshot
VIDEO_FRAME_TOK = 1_700           # per extracted video frame

# Video frame extraction: num_frames = min(int(duration_sec), 20) in main.py.
# A 25-second video therefore hits the 20-frame CAP (any video >= 20s = 20 frames).
AVG_VIDEO_SECONDS = 25
VIDEO_FRAMES_PER_BUG = min(int(AVG_VIDEO_SECONDS), 20)   # = 20

# Output caps.
P1_OUTPUT_TOK = 600               # capped at max_tokens=1000
P2_OUTPUT_TOK = 3_500              # capped at max_tokens=6000

# Bug-shape mix at 3,000 bugs/month (assumption — refresh from real data).
MONTHLY_VOLUME = 3_000
SHARE_TEXT_ONLY = 0.60
SHARE_SCREENSHOT = 0.25
SHARE_VIDEO = 0.15
RETRY_BUFFER = 0.05               # 5% buffer for fall-back / retry cases


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def cost_usd(input_tok: int, output_tok: int) -> float:
    """Cost of one LLM call in USD."""
    return (
        input_tok * INPUT_PER_M / 1_000_000
        + output_tok * OUTPUT_PER_M / 1_000_000
    )


@dataclass
class PromptCost:
    name: str
    p1_input: int
    p1_output: int
    p2_input: int
    p2_output: int
    has_phase2: bool

    @property
    def cost_per_bug(self) -> float:
        c = cost_usd(self.p1_input, self.p1_output)
        if self.has_phase2:
            c += cost_usd(self.p2_input, self.p2_output)
        return c


def make_shapes(few_shot_tok: int) -> dict[str, PromptCost]:
    """Build the four canonical bug shapes at a given few-shot block size."""
    p1_input = (
        SYSTEM_PROMPT_BASE_TOK
        + few_shot_tok
        + USER_BRIEF_TOK
        + JSON_MODE_OVERHEAD_TOK
    )
    p2_text_base = (
        SYSTEM_PROMPT_BASE_TOK
        + few_shot_tok
        + PHASE2_TEMPLATE_TOK
        + P1_RESULT_JSON_TOK
        + USER_BRIEF_TOK
    )
    return {
        "text_only": PromptCost(
            "text_only",
            p1_input, P1_OUTPUT_TOK,
            0, 0,
            has_phase2=False,
        ),
        "screenshot": PromptCost(
            "screenshot",
            p1_input, P1_OUTPUT_TOK,
            p2_text_base + SCREENSHOT_TOK, P2_OUTPUT_TOK,
            has_phase2=True,
        ),
        "video": PromptCost(
            "video",
            p1_input, P1_OUTPUT_TOK,
            p2_text_base + VIDEO_FRAMES_PER_BUG * VIDEO_FRAME_TOK, P2_OUTPUT_TOK,
            has_phase2=True,
        ),
        "screenshot_plus_video": PromptCost(
            "screenshot_plus_video",
            p1_input, P1_OUTPUT_TOK,
            p2_text_base + SCREENSHOT_TOK + VIDEO_FRAMES_PER_BUG * VIDEO_FRAME_TOK,
            P2_OUTPUT_TOK,
            has_phase2=True,
        ),
    }


def monthly_total(shapes: dict[str, PromptCost], volume: int) -> float:
    """Apply the bug-shape mix to a given total volume."""
    avg_video = (shapes["video"].cost_per_bug + shapes["screenshot_plus_video"].cost_per_bug) / 2.0
    sub = (
        SHARE_TEXT_ONLY * volume * shapes["text_only"].cost_per_bug
        + SHARE_SCREENSHOT * volume * shapes["screenshot"].cost_per_bug
        + SHARE_VIDEO * volume * avg_video
    )
    return sub * (1 + RETRY_BUFFER)


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────

def main() -> None:
    print("=" * 64)
    print("  Token cost estimate — QA Bug Logger Bot")
    print(f"  Gemini 2.5 Flash @ ${INPUT_PER_M}/M in, ${OUTPUT_PER_M}/M out")
    print(f"  USD -> INR @ {USD_TO_INR}")
    print("=" * 64)

    # ── Canonical reference case: 1 bug with a 25-second video ──
    print(f"\n### CANONICAL CASE: 1 bug with a {AVG_VIDEO_SECONDS}s video "
          f"({VIDEO_FRAMES_PER_BUG} frames extracted) ###")
    print("    (25s >= 20s, so frame extraction hits the 20-frame cap)")

    for label, few_shot in (
        ("CURRENT (50-example static block)", FEW_SHOT_TOK_STATIC),
        ("RAG (5 retrieved examples)", FEW_SHOT_TOK_RAG),
    ):
        # Phase 1 line items
        p1_in = (SYSTEM_PROMPT_BASE_TOK + few_shot + USER_BRIEF_TOK
                 + USER_WRAPPER_TOK + JSON_MODE_OVERHEAD_TOK)
        p1_out = P1_OUTPUT_TOK
        # Phase 2 line items
        p2_text = (SYSTEM_PROMPT_BASE_TOK + few_shot + PHASE2_TEMPLATE_TOK
                   + P1_RESULT_JSON_TOK + USER_BRIEF_TOK)
        p2_frames = VIDEO_FRAMES_PER_BUG * VIDEO_FRAME_TOK
        p2_in = p2_text + p2_frames
        p2_out = P2_OUTPUT_TOK

        total_in = p1_in + p2_in
        total_out = p1_out + p2_out
        p1_cost = cost_usd(p1_in, p1_out)
        p2_cost = cost_usd(p2_in, p2_out)
        total_cost = p1_cost + p2_cost

        print(f"\n  --- {label} ---")
        print(f"    Phase 1 input tokens   : {p1_in:>8,}")
        print(f"    Phase 1 output tokens  : {p1_out:>8,}")
        print(f"    Phase 2 text input     : {p2_text:>8,}")
        print(f"    Phase 2 video frames   : {p2_frames:>8,}  ({VIDEO_FRAMES_PER_BUG} x {VIDEO_FRAME_TOK})")
        print(f"    Phase 2 input total    : {p2_in:>8,}")
        print(f"    Phase 2 output tokens  : {p2_out:>8,}")
        print(f"    -----------------------------------------")
        print(f"    TOTAL input tokens     : {total_in:>8,}")
        print(f"    TOTAL output tokens    : {total_out:>8,}")
        print(f"    TOTAL tokens           : {total_in + total_out:>8,}")
        print(f"    Phase 1 cost           : ${p1_cost:.5f}")
        print(f"    Phase 2 cost           : ${p2_cost:.5f}")
        print(f"    COST PER BUG           : ${total_cost:.5f}  (Rs {total_cost*USD_TO_INR:.3f})")
        print(f"    x 3,000 bugs/month     : ${total_cost*3000:.2f}  (Rs {total_cost*3000*USD_TO_INR:.0f})")

    print("\n" + "=" * 64)
    print("  ALL BUG SHAPES (weighted monthly model)")
    print("=" * 64)

    for label, few_shot, note in (
        ("CURRENT PRODUCTION (50-example static few-shot)", FEW_SHOT_TOK_STATIC, "qa-bugbot-00042-8zj"),
        ("PHASE 2 — RAG (5-example retrieved few-shot)",   FEW_SHOT_TOK_RAG,    "feat/rag-few-shot-retrieval"),
    ):
        print(f"\n--- {label} ---")
        print(f"    {note}")
        shapes = make_shapes(few_shot)
        for s in shapes.values():
            inr = s.cost_per_bug * USD_TO_INR
            print(f"    {s.name:<24} ${s.cost_per_bug:.5f}  (Rs {inr:.3f})")
        m = monthly_total(shapes, MONTHLY_VOLUME)
        print(f"    {'monthly @ %d bugs' % MONTHLY_VOLUME:<24} ${m:.2f}    (Rs {m*USD_TO_INR:.0f})")

    # Delta line
    static_total = monthly_total(make_shapes(FEW_SHOT_TOK_STATIC), MONTHLY_VOLUME)
    rag_total    = monthly_total(make_shapes(FEW_SHOT_TOK_RAG),    MONTHLY_VOLUME)
    saved_usd = static_total - rag_total
    saved_pct = saved_usd / static_total * 100.0
    print("\n--- DELTA ---")
    print(f"    monthly savings with RAG @ {MONTHLY_VOLUME} bugs: "
          f"${saved_usd:.2f}  (Rs {saved_usd*USD_TO_INR:.0f})  — {saved_pct:.1f}%")


if __name__ == "__main__":
    main()
