"""
Regression test for the QA-audit finding: the user-facing reply showed
'Project: ANDROID' even when the ticket was correctly filed in
'Desktop Lead Manager'.

Root cause: openproject_client.create_work_package returned
    "project": bug_report.platform.value.upper()
which is the LLM's `platform` field (Android/iOS), not the actual
destination project resolved by the bucket router.

Fix: resolve the canonical project name from OP_PROJECTS using the
project_id passed to create_work_package.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from config import OP_PROJECTS
from models import (
    BugType,
    EnvironmentType,
    ExtractedBugReport,
    PlatformType,
    PriorityLevel,
)
from openproject_client import OpenProjectClient


def _report(platform: PlatformType = PlatformType.ANDROID) -> ExtractedBugReport:
    return ExtractedBugReport(
        title="Bug",
        actual_behavior="x",
        expected_behavior="y",
        steps_to_reproduce=["a"],
        device="Not specified",
        operating_system="Not specified",
        environment=EnvironmentType.STAGE,
        app_version="Not specified",
        bug_type=BugType.FUNCTIONAL,
        priority=PriorityLevel.MEDIUM,
        platform=platform,
    )


def _mock_201_response() -> MagicMock:
    resp = MagicMock()
    resp.status_code = 201
    resp.json.return_value = {"id": 12345}
    return resp


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "project_id, expected_project_name, llm_platform",
    [
        # The QA audit finding: Android-platform LLM output, ticket filed in
        # Desktop Lead Manager. Reply MUST say "Desktop Lead Manager", not "ANDROID".
        (70, "Desktop Lead Manager", PlatformType.ANDROID),
        # Android tickets stay Android.
        (3, "Android", PlatformType.ANDROID),
        # iOS tickets stay iOS.
        (85, "iOS", PlatformType.IOS),
    ],
)
async def test_reply_project_matches_actual_destination(
    project_id, expected_project_name, llm_platform
):
    """The reply 'project' field MUST be the canonical name of project_id,
    not the LLM platform field."""
    # Sanity: the test data must match the real OP_PROJECTS mapping
    assert OP_PROJECTS.get(expected_project_name) == project_id, (
        f"Test data drift: OP_PROJECTS[{expected_project_name!r}] "
        f"!= {project_id}"
    )

    client = OpenProjectClient(base_url="http://fake")
    fake_async_client = MagicMock()
    fake_async_client.__aenter__ = AsyncMock(return_value=fake_async_client)
    fake_async_client.__aexit__ = AsyncMock(return_value=None)
    fake_async_client.post = AsyncMock(return_value=_mock_201_response())

    with patch("openproject_client.httpx.AsyncClient", return_value=fake_async_client):
        result = await client.create_work_package(
            bug_report=_report(llm_platform),
            api_key="fake-key",
            project_id=project_id,
        )

    assert result["project"] == expected_project_name, (
        f"Reply 'project' lied: expected {expected_project_name!r} "
        f"but got {result['project']!r}"
    )
    assert result["project_id"] == project_id
    # Sanity: payload sent to OP also targeted the right project
    sent_payload = fake_async_client.post.call_args.kwargs["json"]
    assert sent_payload["_links"]["project"]["href"].endswith(f"/{project_id}")
