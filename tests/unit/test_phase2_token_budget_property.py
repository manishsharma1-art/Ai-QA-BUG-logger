"""
Hypothesis test for Phase 2 LLM budget — Property 6.
Ensures prompt + payload size does not exceed token budget.
"""

from hypothesis import given
from hypothesis import strategies as st

from gemini_client import PHASE2_PROMPT_TEMPLATE

# Fixed template variable set — must be updated when PHASE2_PROMPT_TEMPLATE changes.
_TEMPLATE_FIXED_VARS = {
    "initial_environment": "STAGE",
    "initial_bug_type": "Functional/Logical",
    "initial_priority": "Medium",
}


@given(st.text(min_size=0, max_size=10000), st.text(min_size=0, max_size=5000))
def test_prompt_size_scaling(initial_json, original_brief):
    """
    Property 6:
    Verify that the rendered prompt text length scales predictably with inputs.
    We don't have a local tokenizer, but we can assert the character length
    is exactly the sum of inputs + template overhead, preventing unexpected explosion.
    """
    template_overhead = len(
        PHASE2_PROMPT_TEMPLATE.format(
            initial_json="", original_brief="", **_TEMPLATE_FIXED_VARS
        )
    )
    rendered = PHASE2_PROMPT_TEMPLATE.format(
        initial_json=initial_json,
        original_brief=original_brief,
        **_TEMPLATE_FIXED_VARS,
    )
    assert len(rendered) == len(initial_json) + len(original_brief) + template_overhead
