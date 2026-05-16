"""
Google Chat API integration for sending messages and downloading attachments.
Uses service account credentials with lazy initialization.
"""

import asyncio
import json
import logging
import os
from functools import lru_cache
from typing import Optional, Dict, Any, List

from google.oauth2 import service_account
from google.auth.transport.requests import Request as GoogleAuthRequest
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

# Google Chat API scopes
CHAT_SCOPES = ["https://www.googleapis.com/auth/chat.bot"]


class GoogleChatClient:
    """Client for Google Chat API — sends messages and downloads attachments."""

    def __init__(self, service_account_path: str):
        """
        Initialize with path to service account JSON file.
        Uses lazy loading — actual API client created on first use.
        """
        self.service_account_path = service_account_path
        self._credentials = None
        self._chat_service = None
        self._initialized = False
        logger.info(f"GoogleChatClient configured with: {service_account_path}")

    def _ensure_initialized(self) -> None:
        """Lazy-load the Chat API client to prevent startup crashes."""
        if self._initialized:
            # Refresh credentials if expired
            if self._credentials and self._credentials.expired:
                self._credentials.refresh(GoogleAuthRequest())
            return

        if not os.path.exists(self.service_account_path):
            logger.warning(
                f"Service account file not found: {self.service_account_path}. "
                "Chat API features (async replies, attachment downloads) will be unavailable."
            )
            return

        try:
            self._credentials = service_account.Credentials.from_service_account_file(
                self.service_account_path,
                scopes=CHAT_SCOPES,
            )
            self._credentials.refresh(GoogleAuthRequest())
            self._chat_service = build("chat", "v1", credentials=self._credentials)
            self._initialized = True
            logger.info("Google Chat API client initialized successfully.")
        except Exception as e:
            logger.error(f"Failed to initialize Google Chat API client: {e}")

    async def send_message(
        self,
        space_name: str,
        text: str,
        thread_name: Optional[str] = None,
        cards: Optional[List[Dict]] = None,
    ) -> Optional[Dict]:
        """
        Send a message to a Google Chat space.

        Args:
            space_name: Space resource name (e.g., 'spaces/AAAA...').
            text: Message text.
            thread_name: Thread resource name for replies (optional).
            cards: Card v2 payload for rich messages (optional).

        Returns:
            Message response dict, or None on failure.
        """
        self._ensure_initialized()
        if not self._chat_service:
            logger.error("Chat service not available — cannot send message.")
            return None

        body: Dict[str, Any] = {"text": text}

        if thread_name:
            body["thread"] = {"name": thread_name}

        if cards:
            body["cardsV2"] = cards

        try:
            # Build kwargs based on whether we have a thread
            kwargs = {
                "parent": space_name,
                "body": body,
            }
            if thread_name:
                kwargs["messageReplyOption"] = "REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD"

            # Run synchronous Google API call in thread executor
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: self._chat_service.spaces().messages().create(**kwargs).execute(),
            )
            logger.info(f"Message sent to {space_name}")
            return result

        except Exception as e:
            logger.error(f"Failed to send message to {space_name}: {e}")
            return None

    async def download_attachment(
        self,
        attachment: Dict[str, Any],
    ) -> Optional[bytes]:
        """
        Download an attachment from a Google Chat message.

        Args:
            attachment: Attachment dict from the webhook payload.

        Returns:
            Attachment content as bytes, or None on failure.
        """
        self._ensure_initialized()
        if not self._chat_service:
            logger.error("Chat service not available — cannot download attachment.")
            return None

        # Get the resource name for download
        attachment_data_ref = attachment.get("attachmentDataRef", {})
        resource_name = attachment_data_ref.get("resourceName")

        if not resource_name:
            # Try alternative: use attachment name to get download URI
            attachment_name = attachment.get("name")
            if attachment_name:
                try:
                    loop = asyncio.get_event_loop()
                    att_info = await loop.run_in_executor(
                        None,
                        lambda: self._chat_service.spaces().messages().attachments().get(
                            name=attachment_name,
                        ).execute(),
                    )
                    resource_name = att_info.get("attachmentDataRef", {}).get("resourceName")
                except Exception as e:
                    logger.error(f"Failed to get attachment info: {e}")
                    return None

        if not resource_name:
            logger.error("No resource name found for attachment download.")
            return None

        try:
            # Download media content
            loop = asyncio.get_event_loop()
            media = await loop.run_in_executor(
                None,
                lambda: self._chat_service.media().download(
                    resourceName=resource_name,
                ).execute(),
            )
            content_type = attachment.get("contentType", "unknown")
            logger.info(f"Downloaded attachment: {content_type}, {len(media)} bytes")
            return media

        except Exception as e:
            logger.error(f"Failed to download attachment: {e}")

            # Fallback: try using httpx with bearer token
            try:
                import httpx
                self._credentials.refresh(GoogleAuthRequest())
                headers = {"Authorization": f"Bearer {self._credentials.token}"}

                async with httpx.AsyncClient(timeout=60.0) as client:
                    response = await client.get(
                        f"https://chat.googleapis.com/v1/media/{resource_name}?alt=media",
                        headers=headers,
                    )

                if response.status_code == 200:
                    logger.info(f"Downloaded attachment via httpx fallback: {len(response.content)} bytes")
                    return response.content
                else:
                    logger.error(f"Attachment download fallback failed: HTTP {response.status_code}")
                    return None

            except Exception as fallback_error:
                logger.error(f"Attachment download fallback also failed: {fallback_error}")
                return None

    def is_available(self) -> bool:
        """Check if the Google Chat client is properly configured."""
        self._ensure_initialized()
        return self._initialized and self._chat_service is not None
