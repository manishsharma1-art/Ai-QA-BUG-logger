"""
QA-audit regression suite.

Pins routing behavior against the May 2026 QA audit sheet
(101gmGqrYxnzqKCnZObhK_8kHWae47Z8e1e4i-IoBZec). Every case below was
flagged by the auditor as either:
  - opened in the wrong bucket (live production behavior), OR
  - "Could not process your bug report" (live production failure to
    create any ticket at all).

The proposed branch's bucket_router + categorized error handling SHALL
route each of these to the correct OpenProject project (or to its
canonical sibling — see EQUIVALENTS for cases where the auditor used a
display name that differs from the actual OP_PROJECTS key).

If a project genuinely doesn't exist in OP_PROJECTS, it's documented in
KNOWN_CONFIG_GAPS — those need an OP_PROJECTS edit, not a code fix.
"""
from __future__ import annotations

import pytest

from bucket_router import extract_bucket_from_message
from config import OP_PROJECTS

ID_TO_NAME = {pid: name for name, pid in OP_PROJECTS.items()}

# Projects the audit names differently from how they appear in OP_PROJECTS.
# Both names refer to the same actual project (verified by inspecting OP_PROJECTS).
EQUIVALENTS = {
    "Photo Search IM": {"Photo Search"},
    "Dir": {"Desktop DIR"},
    "BuyerMY IM": {"Buyer MY.IM"},
    "MobileSite_M": {"Msite"},
    "Indiamart Homepage": {"Desktop Homepage"},
    "Desktop Identification,Login and Verification": {"Desktop Login"},
    "FCP/MDC": {"Desktop FCP"},
    "Centralized Header & Footer": {"Desktop Header Footer"},
}

# Projects flagged by the audit but NOT present in OP_PROJECTS at all.
# These cause routing fall-through to device-detection + Android default.
# Add them to OP_PROJECTS (or alias them) to fix.
KNOWN_CONFIG_GAPS = {
    "Model Product Library",
    "Msite SOI",
    "Export",
}


def _expected_project_keys(audit_name: str) -> set[str]:
    """Return all OP_PROJECTS keys equivalent to the audit's expected name."""
    keys = {audit_name}
    keys |= EQUIVALENTS.get(audit_name, set())
    # Lowercase comparison
    return {k.lower() for k in keys}


# ─── Bucket routing audit cases ────────────────────────────────────────

# (ticket, expected_project_per_audit, brief)
AUDIT_CASES = [
    ("666250", "Clients Templates",
     "[Clients Templates] Search autosuggestions and the keyboard remain visible during page scrolls."),
    ("666327", "Product Approval & AI Audit",
     "[Product Approval and AI Audit] Audit History section gets cut when product has multiple history records"),
    ("666329", "Product Approval & AI Audit",
     "[Product Approval and AI Audit] Audit History section gets cut when product has multiple history records"),
    ("666018", "MobileSite_M",
     "[Msite] PDP: Location is Blank in the first fold of PDP page. Device: Vivo y73, OS: Android 13"),
    ("666029", "Desktop PDP",
     "[Product Detail Page] Masked IEC Digits Are Misaligned in Company Profile chrome version: 138"),
    ("666040", "Centralized Header & Footer",
     "[Centralized Header & Footer] Header Elements are not working Properly || enironment: live, chrome version: 138"),
    ("666226", "Desktop Identification,Login and Verification",
     "[Desktop Identification,Login and Verification] Foreign User Able to Login Using Invalid Mobile Number 0000000 Device: Windows 11"),
    ("666235", "Centralized Header & Footer",
     "[Centralized Header & Footer] Header Elements are not working Properly, Signin and Join NowCTA in the header is not clickable Device: Windows 11"),
    ("666315", "FCP/MDC",
     "[FCP/MDC] Product image is cropped under 'Our Products Range' Section Device: Windows 11"),
    # Three cases that returned "Could not process" in production — proposed
    # branch routes them correctly so the categorised error path won't ever
    # fire for these specific briefs.
    ("FAIL-1", "Product Approval & AI Audit",
     "[Product Approval & AI Audit] Feedback is submitted without filling the mandatory field 'Your Feedback' Device: Windows 11"),
    ("FAIL-2", "BL and Enquiry forms",
     "[BL and Enquiry forms] Not able to search the country name in chat BL form Device: Windows 11"),
    ("FAIL-3", "Google Product Ads",
     "[Google Product Ads] Reverse Identification Fails When User Returns to Platform After Delay Following Successful Call Connection"),
    # Older audit batch
    ("666019", "Photo Search IM",
     "[photo search] Irrelevent result display for searched image. Browser: Google Chrome Enviornment: Live device desktop"),
    ("666027", "BuyerMY IM",
     "[BuyerMY] in buyermy dashboard on footer section post your requriment cta are not clickable."),
    ("666036", "MobileSite_M",
     "[MobileSite_M] in homepage message section it show unread message count for seller"),
    ("666043", "Photo Search IM",
     "[Photo Search IM] when search using any image it showing result click on product name it showing oops page not found"),
    ("666044", "Photo Search IM",
     "[Photo Search IM] Upload product image cta is not clickable Browser: Google Chrome Enviornment: Live device: laptop"),
    ("666051", "Indiamart Homepage",
     "[indiamart homepage] login popup not closed and stuck screen Browser: Google Chrome Enviornment: Live device: laptop"),
    ("666342", "Photo Search IM",
     "[Photo Search IM] croper is not working when user try to crop uploaded image"),
    ("666346", "Dir",
     "[Dir] when click on product name noredirect is work"),
    ("666366", "BuyerMY IM",
     "[Buyer] case 1: selected city get changed when search product"),
    ("666371", "Dir",
     "[Dir] in dir page reently view section on product card product details are shifted to left"),
]


@pytest.mark.parametrize(
    "ticket, expected, brief",
    AUDIT_CASES,
    ids=[c[0] for c in AUDIT_CASES],
)
def test_audit_case_routes_correctly(ticket, expected, brief):
    """Every May 2026 audit case routes to the correct project (or to a
    documented equivalent)."""
    project_id, text_for_llm = extract_bucket_from_message(brief)
    actual_name = ID_TO_NAME.get(project_id, f"id={project_id}")
    expected_set = _expected_project_keys(expected)
    assert actual_name.lower() in expected_set, (
        f"audit case #{ticket}: expected one of {expected_set}, "
        f"got {actual_name!r} (project_id={project_id})"
    )


def test_known_config_gaps_documented():
    """The audit flags 3 projects that have no OP_PROJECTS entry. They
    must remain documented so this gap is visible — adding them to
    OP_PROJECTS is the fix, not removing them from this set."""
    op_keys_lower = {k.lower() for k in OP_PROJECTS.keys()}
    for missing in KNOWN_CONFIG_GAPS:
        assert missing.lower() not in op_keys_lower, (
            f"{missing!r} is now in OP_PROJECTS — remove it from "
            "KNOWN_CONFIG_GAPS in this test file and add a real audit case for it"
        )


def test_bracket_tag_is_preserved_in_text_for_llm():
    """Brief preservation contract — RC5 in the spec. The Phase 1 LLM
    must receive the original bracket-tagged brief verbatim."""
    brief = "[Desktop Lead Manager] Chat conversation crashes when buyer types a reply. Browser: Google Chrome"
    _, text_for_llm = extract_bucket_from_message(brief)
    assert text_for_llm == brief, (
        f"text_for_llm must equal input brief verbatim; got {text_for_llm!r}"
    )
