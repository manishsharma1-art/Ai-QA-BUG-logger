"""
Hypothesis test for bucket_router.py — Property 3.
Ensures that typos within Levenshtein 1-2 distance map to the same project ID or None,
but never to a completely different project ID.
"""
from hypothesis import given, strategies as st
from bucket_router import _resolve_tag, PROJECT_ALIASES
from config import OP_PROJECTS

# Collect all valid aliases that resolve to something
_ALL = [a for a in PROJECT_ALIASES.keys() if PROJECT_ALIASES[a] in OP_PROJECTS]
# Filter out aliases that contain other shorter aliases, because injecting typos in the outer alias 
# can leave the inner alias intact, causing substring match to legitimately return a different project.
VALID_ALIASES = [a for a in _ALL if not any(len(sub) >= 3 and sub != a and sub in a for sub in _ALL)]


@given(
    st.sampled_from(VALID_ALIASES),
    st.integers(min_value=0, max_value=2),  # number of typos to inject
    st.randoms()
)
def test_resolve_tag_typo_tolerance(base_alias, num_typos, rnd):
    """
    Property 3:
    If we take a valid tag/alias and introduce 1-2 character edits (typos),
    it should either:
      1) Resolve to the EXACT SAME project ID as the base alias.
      2) Resolve to None (if it falls below the fuzzy threshold).
    It must NEVER resolve to a DIFFERENT project ID.
    """
    base_project_id = _resolve_tag(base_alias)
    assert base_project_id is not None, f"Base alias '{base_alias}' must resolve"

    # Inject typos
    typo_alias = list(base_alias)
    for _ in range(num_typos):
        if not typo_alias:
            break
        op = rnd.choice(["insert", "delete", "substitute"])
        idx = rnd.randint(0, len(typo_alias) - 1 if typo_alias else 0)
        char = chr(rnd.randint(97, 122))  # a-z
        
        if op == "insert":
            typo_alias.insert(idx, char)
        elif op == "delete" and len(typo_alias) > 1:
            typo_alias.pop(idx)
        elif op == "substitute":
            typo_alias[idx] = char

    mutated_str = "".join(typo_alias)
    mutated_project_id = _resolve_tag(mutated_str)

    if mutated_project_id is not None:
        assert mutated_project_id == base_project_id, \
            f"Mutated '{mutated_str}' (from '{base_alias}') resolved to {mutated_project_id}, expected {base_project_id}"
