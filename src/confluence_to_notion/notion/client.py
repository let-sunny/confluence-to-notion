"""Async wrapper over the official notion-client SDK."""

import logging
from typing import Any

from notion_client import APIResponseError, AsyncClient

from confluence_to_notion.config import Settings
from confluence_to_notion.notion.schemas import NotionPageResult

logger = logging.getLogger(__name__)


class NotionClientWrapper:
    """Thin async wrapper around the Notion SDK."""

    def __init__(self, settings: Settings) -> None:
        self._client = AsyncClient(auth=settings.notion_api_token)

    async def ping(self) -> bool:
        """Validate the Notion token by fetching the current bot user.

        Returns True if the token is valid, False otherwise.
        Logs the specific failure reason for debugging.
        """
        try:
            resp: Any = await self._client.users.me()
            return bool(resp.get("id"))
        except APIResponseError as e:
            logger.warning("Notion API error during ping: %s (status %s)", e, e.status)
            return False
        except (OSError, TimeoutError) as e:
            logger.warning("Network error during Notion ping: %s", e)
            return False

    async def create_page(
        self, parent_id: str, title: str, blocks: list[dict[str, Any]]
    ) -> NotionPageResult:
        """Create a page under the given parent and return a NotionPageResult."""
        resp: Any = await self._client.pages.create(
            parent={"page_id": parent_id},
            properties={"title": [{"text": {"content": title}}]},
            children=blocks,
        )
        return NotionPageResult(page_id=resp["id"])
