"""
Hypothesis test for priority validator in models.py — Property 4.
Ensures priority validation is deterministic and total over arbitrary strings.
"""
from hypothesis import given, strategies as st
from models import ExtractedBugReport, PriorityLevel

@given(st.text())
def test_priority_is_total_and_deterministic(input_str):
    """
    Property 4:
    Priority validator must never crash on any string (total)
    and must always map into {HIGH, MEDIUM, LOW} (deterministic).
    """
    report = ExtractedBugReport(priority=input_str)
    assert report.priority in (PriorityLevel.HIGH, PriorityLevel.MEDIUM, PriorityLevel.LOW)
