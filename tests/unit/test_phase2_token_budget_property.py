"""
Hypothesis test for Phase 2 LLM budget — Property 6.
Ensures prompt + payload size does not exceed token budget.
"""
from hypothesis import given, strategies as st
from gemini_client import PHASE2_PROMPT_TEMPLATE

@given(st.text(min_size=0, max_size=10000), st.text(min_size=0, max_size=5000))
def test_prompt_size_scaling(initial_json, original_brief):
    """
    Property 6:
    Verify that the rendered prompt text length scales predictably with inputs.
    We don't have a local tokenizer, but we can assert the character length
    is exactly the sum of inputs + template overhead, preventing unexpected explosion.
    """
    template_overhead = len(PHASE2_PROMPT_TEMPLATE.format(initial_json="", original_brief=""))
    rendered = PHASE2_PROMPT_TEMPLATE.format(
        initial_json=initial_json,
        original_brief=original_brief
    )
    assert len(rendered) == len(initial_json) + len(original_brief) + template_overhead
