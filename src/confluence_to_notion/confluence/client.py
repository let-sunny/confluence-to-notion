"""Async Confluence REST API client using httpx."""

import asyncio
import logging
from pathlib import Path
from types import TracebackType
from typing import Any

import httpx

from confluence_to_notion.config import Settings
from confluence_to_notion.confluence.schemas import ConfluencePage, ConfluencePageSummary

logger = logging.getLogger(__name__)

# Confluence REST API caps a single request at 250 results.
_API_MAX_PER_PAGE = 250
# Concurrency limit for parallel page fetches.
_FETCH_CONCURRENCY = 10


class ConfluenceClient:
    """Async client for Confluence Cloud REST API.

    Use as an async context manager to reuse the underlying httpx connection pool:

        async with ConfluenceClient(settings) as client:
            page = await client.get_page("12345")

    Can also be used without context manager (creates a new connection per call).
    """

    def __init__(self, settings: Settings) -> None:
        self._base = settings.confluence_rest_url
        self._auth = httpx.BasicAuth(
            username=settings.confluence_email,
            password=settings.confluence_api_token,
        )
        self._owned_client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "ConfluenceClient":
        self._owned_client = httpx.AsyncClient(auth=self._auth)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if self._owned_client:
            await self._owned_client.aclose()
            self._owned_client = None

    async def _get(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Perform a GET request, reusing the connection pool if available."""
        if self._owned_client:
            resp = await self._owned_client.get(url, params=params)
        else:
            async with httpx.AsyncClient(auth=self._auth) as client:
                resp = await client.get(url, params=params)
        resp.raise_for_status()
        result: dict[str, Any] = resp.json()
        return result

    async def get_page(self, page_id: str) -> ConfluencePage:
        """Fetch a single page by ID with its XHTML storage body."""
        url = f"{self._base}/content/{page_id}"
        params: dict[str, Any] = {"expand": "body.storage,version,space"}
        data = await self._get(url, params)
        return _parse_page(data)

    async def list_pages_in_space(
        self, space_key: str, limit: int = 25
    ) -> list[ConfluencePageSummary]:
        """List pages in a Confluence space with automatic pagination.

        Args:
            space_key: The Confluence space key.
            limit: Maximum total number of pages to return. Handles pagination
                   internally when limit exceeds the API per-page maximum (250).
        """
        url = f"{self._base}/content"
        collected: list[ConfluencePageSummary] = []
        start = 0

        while len(collected) < limit:
            per_page = min(limit - len(collected), _API_MAX_PER_PAGE)
            params: dict[str, str | int] = {
                "spaceKey": space_key,
                "limit": per_page,
                "start": start,
                "type": "page",
            }
            data = await self._get(url, params)
            results: list[dict[str, Any]] = data.get("results", [])
            if not results:
                break
            collected.extend(
                ConfluencePageSummary(id=r["id"], title=r["title"])
                for r in results
            )
            # No more pages available
            if "_links" not in data or "next" not in data["_links"]:
                break
            start += len(results)

        return collected[:limit]

    async def fetch_samples_to_disk(
        self, space_key: str, out_dir: Path, limit: int = 25
    ) -> list[Path]:
        """Fetch pages from a space and save their XHTML bodies to disk.

        Uses concurrent requests (up to _FETCH_CONCURRENCY) for speed.
        Individual page failures are logged and skipped.
        """
        out_dir.mkdir(parents=True, exist_ok=True)
        async with self:
            pages = await self.list_pages_in_space(space_key, limit=limit)
            if not pages:
                logger.warning("No pages found in space '%s'", space_key)
                return []

            semaphore = asyncio.Semaphore(_FETCH_CONCURRENCY)
            saved: list[Path] = []
            lock = asyncio.Lock()

            async def _fetch_one(summary: ConfluencePageSummary) -> None:
                async with semaphore:
                    try:
                        page = await self.get_page(summary.id)
                    except (httpx.HTTPStatusError, KeyError) as e:
                        logger.warning(
                            "Skipping page %s (%s): %s", summary.id, summary.title, e
                        )
                        return
                    file_path = out_dir / f"{page.id}.xhtml"
                    file_path.write_text(page.storage_body, encoding="utf-8")
                    async with lock:
                        saved.append(file_path)

            await asyncio.gather(*[_fetch_one(s) for s in pages])
        return saved


def _parse_page(data: dict[str, Any]) -> ConfluencePage:
    """Parse Confluence REST API response into a ConfluencePage model.

    Raises KeyError if expected fields are missing from the response.
    """
    try:
        return ConfluencePage(
            id=data["id"],
            title=data["title"],
            space_key=data["space"]["key"],
            storage_body=data["body"]["storage"]["value"],
            version=data["version"]["number"],
            created_at=data["version"]["when"],
        )
    except KeyError as e:
        raise KeyError(
            f"Confluence API response missing expected field: {e}. "
            f"Available top-level keys: {list(data.keys())}"
        ) from e
