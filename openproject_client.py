"""
OpenProject REST API client for creating bug tickets.
Uses per-user API keys for authentication.
"""

import base64
import logging
import json
import time
from typing import Optional, Dict, Any

import httpx

from models import ExtractedBugReport
from config import (
    OP_TYPE_BUG_ID, OP_PRIORITIES, OP_PROJECTS,
    OP_BUG_TYPES, OP_ENVIRONMENTS, OP_BUCKET_CATEGORIES, get_settings,
)

logger = logging.getLogger(__name__)


def _log_op_call(
    method: str,
    url: str,
    start_ts: float,
    response: Optional[httpx.Response] = None,
    exc: Optional[BaseException] = None,
) -> None:
    """
    Emit a single structured ``OP_CALL`` log line per OpenProject HTTP call.

    The line shape is::

        OP_CALL method=<…> url=<…> outcome=<…> [status_code=<…>] duration_ms=<…> [detail="…"]

    Five outcomes:
      - ``ok``            : 2xx response
      - ``client_error``  : 4xx response
      - ``server_error``  : 5xx response
      - ``network_error`` : ``httpx.RequestError`` / ``TimeoutError``
      - ``unknown_error`` : anything else (including the defensive
                            "no response and no exception" case)

    This helper only emits a log line; it never raises and never mutates state.
    Callers are expected to handle the response or re-raise the exception
    separately. ``httpx.TimeoutException`` is a subclass of
    ``httpx.RequestError`` and is therefore classified as ``network_error``.
    """
    duration_ms = int((time.time() - start_ts) * 1000)
    if exc is not None:
        if isinstance(exc, (httpx.RequestError, TimeoutError)):
            outcome = "network_error"
        else:
            outcome = "unknown_error"
        logger.warning(
            'OP_CALL method=%s url=%s outcome=%s duration_ms=%d detail="%s: %s"',
            method, url, outcome, duration_ms,
            type(exc).__name__, str(exc)[:200],
        )
        return
    if response is None:
        # Defensive: shouldn't happen in normal flow.
        logger.warning(
            'OP_CALL method=%s url=%s outcome=unknown_error duration_ms=%d detail="no response"',
            method, url, duration_ms,
        )
        return
    sc = response.status_code
    if 200 <= sc < 300:
        outcome = "ok"
    elif 400 <= sc < 500:
        outcome = "client_error"
    elif 500 <= sc < 600:
        outcome = "server_error"
    else:
        outcome = "unknown_error"
    logger.info(
        'OP_CALL method=%s url=%s outcome=%s status_code=%d duration_ms=%d',
        method, url, outcome, sc, duration_ms,
    )


class OpenProjectClient:
    """Client for OpenProject REST API v3."""

    def __init__(self, base_url: str):
        """Initialize the OpenProject client."""
        self.base_url = base_url.rstrip("/")
        self.api_base = f"{self.base_url}/api/v3"
        logger.info(f"OpenProject client initialized: {self.base_url}")

    def _get_auth_header(self, api_key: str) -> Dict[str, str]:
        """Build Basic auth header from API key."""
        credentials = f"apikey:{api_key}"
        encoded = base64.b64encode(credentials.encode("ascii")).decode("ascii")
        return {
            "Authorization": f"Basic {encoded}",
            "Content-Type": "application/json",
        }

    async def verify_api_key(self, api_key: str) -> Optional[Dict[str, Any]]:
        """
        Verify an OpenProject API key by fetching user info.

        Returns user info dict on success, None on failure.
        """
        headers = self._get_auth_header(api_key)
        url = f"{self.api_base}/users/me"
        start_ts = time.time()

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(
                    url,
                    headers=headers,
                )
        except Exception as e:
            _log_op_call("GET", url, start_ts, exc=e)
            logger.error(f"API key verification error: {e}")
            return None

        _log_op_call("GET", url, start_ts, response=response)

        try:
            if response.status_code == 200:
                data = response.json()
                user_info = {
                    "id": data.get("id"),
                    "name": data.get("name"),
                    "login": data.get("login"),
                    "email": data.get("email"),
                    "status": data.get("status"),
                }
                logger.info(f"API key verified for user: {user_info['name']} (ID: {user_info['id']})")
                return user_info
            else:
                logger.warning(f"API key verification failed: HTTP {response.status_code}")
                return None

        except Exception as e:
            logger.error(f"API key verification error: {e}")
            return None

    async def create_work_package(
        self,
        bug_report: ExtractedBugReport,
        api_key: str,
        project_id: int = 3,
    ) -> Dict[str, Any]:
        """
        Create a new work package (bug ticket) in OpenProject.

        Args:
            bug_report: Structured bug report from AI analysis.
            api_key: User's OpenProject API key.
            project_id: OpenProject project ID (determined by bucket_router).

        Returns:
            Dict with ticket ID, URL, and other details.
        """
        headers = self._get_auth_header(api_key)

        # Build the description in the exact format used by the team
        description_md = self._format_description(bug_report)

        # Build steps to reproduce for customField4
        steps_md = self._format_steps(bug_report.steps_to_reproduce)

        # Use the project_id passed from bucket_router (already resolved)
        # project_id comes as parameter, no need to look up from bug_report

        # Resolve priority ID
        priority_id = OP_PRIORITIES.get(bug_report.priority.value, 8)

        # Resolve bug type custom option ID
        bug_type_id = OP_BUG_TYPES.get(bug_report.bug_type.value, 11)

        # Resolve environment custom option ID
        env_id = OP_ENVIRONMENTS.get(bug_report.environment.value, 22)

        # Build the API payload
        payload = {
            "subject": bug_report.title,
            "description": {
                "format": "markdown",
                "raw": description_md,
            },
            "customField4": {
                "format": "markdown",
                "raw": steps_md,
            },
            "_links": {
                "type": {"href": f"/api/v3/types/{OP_TYPE_BUG_ID}"},
                "project": {"href": f"/api/v3/projects/{project_id}"},
                "priority": {"href": f"/api/v3/priorities/{priority_id}"},
                "customField6": {"href": f"/api/v3/custom_options/{bug_type_id}"},
                "customField9": {"href": f"/api/v3/custom_options/{env_id}"},
            },
        }

        # Category setting disabled for now — will be enabled after category mapping is validated
        # bucket_categories = OP_BUCKET_CATEGORIES.get(bug_report.platform.value, {})
        # if bucket_categories and hasattr(bug_report, 'category') and bug_report.category:
        #     category_id = bucket_categories.get(bug_report.category)
        #     if category_id:
        #         payload["_links"]["category"] = {"href": f"/api/v3/categories/{category_id}"}
        #         logger.info(f"Setting category: {bug_report.category} (ID: {category_id})")

        logger.info(f"Creating work package: {bug_report.title}")
        logger.debug(f"Payload: {payload}")

        # Make the API request with retry
        max_retries = 3
        last_error = None
        wp_url = f"{self.api_base}/work_packages"

        for attempt in range(1, max_retries + 1):
            start_ts = time.time()
            response = None
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.post(
                        wp_url,
                        headers=headers,
                        json=payload,
                    )
                _log_op_call("POST", wp_url, start_ts, response=response)

                if response.status_code in (200, 201):
                    data = response.json()
                    ticket_id = data.get("id")
                    ticket_url = f"{self.base_url}/work_packages/{ticket_id}"

                    logger.info(f"Ticket created successfully: #{ticket_id}")

                    # Resolve the canonical project name from OP_PROJECTS so the
                    # user-facing reply shows the actual destination project
                    # (e.g. "Desktop Lead Manager"), not the platform field.
                    # Falls back to platform.upper() only if the project_id has
                    # no entry in OP_PROJECTS (shouldn't happen).
                    project_name = next(
                        (name for name, pid in OP_PROJECTS.items() if pid == project_id),
                        bug_report.platform.value.upper(),
                    )

                    return {
                        "ticket_id": ticket_id,
                        "ticket_url": ticket_url,
                        "project": project_name,
                        "project_id": project_id,
                        "title": bug_report.title,
                        "bug_type": bug_report.bug_type.value,
                        "priority": bug_report.priority.value,
                        "platform": bug_report.platform.value,
                    }
                else:
                    error_detail = response.text
                    logger.error(
                        f"OpenProject API error (attempt {attempt}): "
                        f"HTTP {response.status_code} — {error_detail}"
                    )
                    last_error = f"HTTP {response.status_code}: {error_detail}"

            except httpx.TimeoutException as e:
                _log_op_call("POST", wp_url, start_ts, exc=e)
                logger.error(f"OpenProject request timeout (attempt {attempt})")
                last_error = "Request timed out"
            except Exception as e:
                # If the request itself didn't yield a response, log the exception;
                # otherwise the response was already logged above.
                if response is None:
                    _log_op_call("POST", wp_url, start_ts, exc=e)
                logger.error(f"OpenProject request failed (attempt {attempt}): {e}")
                last_error = str(e)

            # Wait before retry (exponential backoff)
            if attempt < max_retries:
                import asyncio
                await asyncio.sleep(2 ** attempt)

        raise RuntimeError(f"Failed to create ticket after {max_retries} attempts: {last_error}")

    def _format_description(self, bug: ExtractedBugReport) -> str:
        """Format the bug description in the team's standard markdown format."""
        sections = []

        # Actual Behavior
        sections.append(f"### **Actual Behavior**\n\n{bug.actual_behavior}")

        # Expected Behavior
        sections.append(f"### **Expected Behavior**\n\n{bug.expected_behavior}")

        # Steps to Reproduce
        steps_text = "\n".join(
            f"{i+1}.  {step}" for i, step in enumerate(bug.steps_to_reproduce)
        )
        sections.append(f"### **Steps to reproduce:**\n\n{steps_text}")

        # Test Environment
        env_items = [
            f"1.  **Device:** {bug.device}",
            f"2.  **Environment**: {bug.environment.value}",
            f"3.  **Operating System:** {bug.operating_system}",
        ]
        if bug.app_version and bug.app_version != "Not specified":
            env_items.append(f"4.  **App Version:** {bug.app_version}")
        env_text = "\n".join(env_items)
        sections.append(f"### **Test Environment**:\n\n{env_text}")

        # Logs (if any)
        if bug.logs_or_links:
            sections.append(f"### **Logs**\n\n{bug.logs_or_links}")

        # AI Signature — inside last section (no separator) for filterability
        sections.append("🤖 *Created by Bug Logger*")

        return "\n\n".join(sections)

    def _get_auth_header_multipart(self, api_key: str) -> Dict[str, str]:
        """Build Basic auth header for multipart form requests (no Content-Type)."""
        credentials = f"apikey:{api_key}"
        encoded = base64.b64encode(credentials.encode("ascii")).decode("ascii")
        return {
            "Authorization": f"Basic {encoded}"
        }

    async def attach_file_to_work_package(
        self,
        ticket_id: int,
        file_data: bytes,
        file_name: str,
        content_type: str,
        api_key: str,
    ) -> bool:
        """
        Upload a file attachment to an existing work package.
        """
        headers = self._get_auth_header_multipart(api_key)
        
        # OpenProject requires metadata in addition to the file itself. 
        # But for v3, we can post multipart with just the file or with metadata.
        # Simple multipart upload is supported.
        files = {
            'file': (file_name, file_data, content_type)
        }
        
        # We optionally add the metadata as JSON to a 'metadata' field if required,
        # but OpenProject allows uploading directly if we specify the file.
        # Let's add metadata just in case.
        metadata = {
            "fileName": file_name,
            "description": {"format": "plain", "raw": "Attached by QA Bug Logger"}
        }
        data = {
            "metadata": (None, json.dumps(metadata), "application/json")
        }
        
        # Combine data and files into a single files dictionary for httpx
        multipart_data = {
            'file': (file_name, file_data, content_type),
            'metadata': (None, json.dumps(metadata), 'application/json')
        }

        try:
            logger.info(f"Uploading attachment ({len(file_data)} bytes) to ticket #{ticket_id}...")
            attach_url = f"{self.api_base}/work_packages/{ticket_id}/attachments"
            start_ts = time.time()
            response = None
            try:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    response = await client.post(
                        attach_url,
                        headers=headers,
                        files=multipart_data
                    )
            except Exception as e:
                _log_op_call("POST", attach_url, start_ts, exc=e)
                raise

            _log_op_call("POST", attach_url, start_ts, response=response)

            if response.status_code in (200, 201):
                logger.info(f"✅ Attachment uploaded successfully to ticket #{ticket_id}")
                return True
            else:
                logger.error(f"Failed to attach file to ticket #{ticket_id}: HTTP {response.status_code} - {response.text}")
                return False
        except Exception as e:
            logger.error(f"Exception while uploading attachment to ticket #{ticket_id}: {e}")
            return False

    def _format_steps(self, steps: list) -> str:
        """Format steps to reproduce for customField4."""
        return "\n".join(f"{i+1}. {step}" for i, step in enumerate(steps))

    async def check_health(self) -> bool:
        """Check if OpenProject API is accessible."""
        url = f"{self.api_base}/"
        start_ts = time.time()
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url)
        except Exception as e:
            _log_op_call("GET", url, start_ts, exc=e)
            logger.error(f"OpenProject health check failed: {e}")
            return False

        _log_op_call("GET", url, start_ts, response=response)
        return response.status_code in (200, 401)  # 401 means API is up but needs auth
