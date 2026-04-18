"""Async wrapper over the official notion-client SDK."""

import asyncio
import logging
import random
from typing import Any

from notion_client import APIResponseError, AsyncClient

from confluence_to_notion.config import Settings
from confluence_to_notion.confluence.schemas import PageTreeNode
from confluence_to_notion.converter.schemas import NotionPropertyType
from confluence_to_notion.notion.schemas import NotionPageResult

logger = logging.getLogger(__name__)

MAX_RETRIES = 5
BASE_DELAY = 1.0  # seconds
NOTION_MAX_CHILDREN = 100  # Notion API limit: max children per request


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
        """Create a page under the given parent and return a NotionPageResult.

        Splits blocks into chunks of NOTION_MAX_CHILDREN to respect the API limit.
        Retries up to MAX_RETRIES times on 429 (rate limit) with exponential backoff.
        """
        first_chunk = blocks[:NOTION_MAX_CHILDREN]
        remaining = blocks[NOTION_MAX_CHILDREN:]

        page_id = await self._create_page_with_retry(parent_id, title, first_chunk)

        # Append remaining blocks in chunks
        for i in range(0, len(remaining), NOTION_MAX_CHILDREN):
            chunk = remaining[i : i + NOTION_MAX_CHILDREN]
            logger.info(
                "Appending block chunk %d-%d (%d blocks) to page %s",
                NOTION_MAX_CHILDREN + i,
                NOTION_MAX_CHILDREN + i + len(chunk),
                len(chunk),
                page_id,
            )
            await self._append_children_with_retry(page_id, chunk)

        return NotionPageResult(page_id=page_id)

    async def create_subpage(self, parent_id: str, title: str) -> str:
        """Create an empty page under parent_id and return its Notion id.

        Reuses the 429 retry path so rate-limit handling is preserved.
        """
        return await self._create_page_with_retry(parent_id, title, [])

    async def append_blocks(
        self, page_id: str, blocks: list[dict[str, Any]]
    ) -> None:
        """Append ``blocks`` to ``page_id`` in NOTION_MAX_CHILDREN-sized chunks.

        Delegates to the shared retry path so rate-limit semantics stay uniform.
        """
        if not blocks:
            return
        for i in range(0, len(blocks), NOTION_MAX_CHILDREN):
            chunk = blocks[i : i + NOTION_MAX_CHILDREN]
            logger.info(
                "Appending block chunk %d-%d (%d blocks) to page %s",
                i,
                i + len(chunk),
                len(chunk),
                page_id,
            )
            await self._append_children_with_retry(page_id, chunk)

    async def create_page_tree(
        self, parent_id: str, tree: PageTreeNode
    ) -> dict[str, str]:
        """Recursively create an empty Notion page tree mirroring ``tree``.

        Pages are created sequentially (serial calls keep the 429 retry
        contract intact). Returns a ``{confluence_title: notion_page_id}``
        mapping for every node visited.
        """
        new_page_id = await self.create_subpage(parent_id, tree.title)
        mapping: dict[str, str] = {tree.title: new_page_id}
        for child in tree.children:
            child_mapping = await self.create_page_tree(new_page_id, child)
            mapping.update(child_mapping)
        return mapping

    async def create_database(
        self,
        parent_id: str,
        title: str,
        title_column: str,
        column_types: dict[str, NotionPropertyType],
    ) -> str:
        """Create a Notion database under ``parent_id`` and return its database id.

        ``title_column`` is forced to the ``title`` Notion property type even if
        ``column_types`` declares a different type for it. All other columns map to
        ``{<type>: {}}``. Inherits the same 429 + exponential-backoff retry shape
        as ``_create_page_with_retry``.
        """
        properties: dict[str, dict[str, dict[str, Any]]] = {}
        for column, prop_type in column_types.items():
            effective = "title" if column == title_column else prop_type
            properties[column] = {effective: {}}

        last_error: APIResponseError | None = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                resp: Any = await self._client.databases.create(
                    parent={"page_id": parent_id},
                    title=[{"type": "text", "text": {"content": title}}],
                    properties=properties,
                )
                return str(resp["id"])
            except APIResponseError as e:
                if e.status != 429 or attempt == MAX_RETRIES:
                    raise
                last_error = e
                delay = BASE_DELAY * (2**attempt) + random.uniform(0, 1)
                logger.warning(
                    "Notion rate limited (429) on database create, retry %d/%d in %.1fs",
                    attempt + 1,
                    MAX_RETRIES,
                    delay,
                )
                await asyncio.sleep(delay)

        assert last_error is not None  # unreachable, satisfies mypy
        raise last_error

    async def _create_page_with_retry(
        self, parent_id: str, title: str, children: list[dict[str, Any]]
    ) -> str:
        """Create page with retry-on-429, return the page id."""
        last_error: APIResponseError | None = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                resp: Any = await self._client.pages.create(
                    parent={"page_id": parent_id},
                    properties={"title": [{"text": {"content": title}}]},
                    children=children,
                )
                return str(resp["id"])
            except APIResponseError as e:
                if e.status != 429 or attempt == MAX_RETRIES:
                    raise
                last_error = e
                delay = BASE_DELAY * (2**attempt) + random.uniform(0, 1)
                logger.warning(
                    "Notion rate limited (429), retry %d/%d in %.1fs",
                    attempt + 1,
                    MAX_RETRIES,
                    delay,
                )
                await asyncio.sleep(delay)

        assert last_error is not None  # unreachable, satisfies mypy
        raise last_error

    async def _append_children_with_retry(
        self, page_id: str, children: list[dict[str, Any]]
    ) -> None:
        """Append children blocks to a page with retry-on-429."""
        last_error: APIResponseError | None = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                await self._client.blocks.children.append(
                    block_id=page_id, children=children
                )
                return
            except APIResponseError as e:
                if e.status != 429 or attempt == MAX_RETRIES:
                    raise
                last_error = e
                delay = BASE_DELAY * (2**attempt) + random.uniform(0, 1)
                logger.warning(
                    "Notion rate limited (429) on append, retry %d/%d in %.1fs",
                    attempt + 1,
                    MAX_RETRIES,
                    delay,
                )
                await asyncio.sleep(delay)

        assert last_error is not None  # unreachable, satisfies mypy
        raise last_error
