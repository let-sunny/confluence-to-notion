"""Async Confluence REST API client using httpx."""

import asyncio
import logging
from pathlib import Path
from types import TracebackType
from typing import Any

import httpx

from confluence_to_notion.config import Settings
from confluence_to_notion.confluence.schemas import (
    ConfluencePage,
    ConfluencePageSummary,
    PageTreeNode,
)

logger = logging.getLogger(__name__)

# Confluence REST API caps a single request at 250 results.
_API_MAX_PER_PAGE = 250
# Concurrency limit for parallel page fetches.
_FETCH_CONCURRENCY = 10
# Timeout and retry configuration.
_CONNECT_TIMEOUT = 10.0
_READ_TIMEOUT = 30.0
_MAX_RETRIES = 3
_BACKOFF_BASE = 1.0


class ConfluenceClient:
    """Async client for Confluence REST API (Cloud and Server/DC).

    Supports both authenticated (Cloud/private) and unauthenticated (public wikis
    like cwiki.apache.org) access. Auth is used only when credentials are configured.

    Use as an async context manager to reuse the underlying httpx connection pool:

        async with ConfluenceClient(settings) as client:
            page = await client.get_page("12345")
    """

    def __init__(self, settings: Settings) -> None:
        self._base = settings.confluence_rest_url
        self._auth: httpx.BasicAuth | None = None
        if settings.confluence_auth_available:
            self._auth = httpx.BasicAuth(
                username=settings.confluence_email or "",
                password=settings.confluence_api_token or "",
            )
        self._owned_client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "ConfluenceClient":
        self._owned_client = httpx.AsyncClient(
            auth=self._auth,
            timeout=httpx.Timeout(_READ_TIMEOUT, connect=_CONNECT_TIMEOUT),
        )
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
        """Perform a GET request with retry on transient failures.

        Retries on httpx.TimeoutException or 5xx HTTP errors with exponential
        backoff. Non-retryable errors (4xx, parse errors) re-raise immediately.
        """
        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                if self._owned_client:
                    resp = await self._owned_client.get(url, params=params)
                else:
                    async with httpx.AsyncClient(
                        auth=self._auth,
                        timeout=httpx.Timeout(_READ_TIMEOUT, connect=_CONNECT_TIMEOUT),
                    ) as client:
                        resp = await client.get(url, params=params)
                resp.raise_for_status()
                result: dict[str, Any] = resp.json()
                return result
            except httpx.TimeoutException as exc:
                last_exc = exc
                if attempt < _MAX_RETRIES:
                    delay = _BACKOFF_BASE * (2 ** attempt)
                    logger.warning(
                        "Timeout on %s (attempt %d/%d), retrying in %.1fs: %s",
                        url, attempt + 1, _MAX_RETRIES + 1, delay, exc,
                    )
                    await asyncio.sleep(delay)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code < 500:
                    raise
                last_exc = exc
                if attempt < _MAX_RETRIES:
                    delay = _BACKOFF_BASE * (2 ** attempt)
                    logger.warning(
                        "%d on %s (attempt %d/%d), retrying in %.1fs",
                        exc.response.status_code, url,
                        attempt + 1, _MAX_RETRIES + 1, delay,
                    )
                    await asyncio.sleep(delay)
        assert last_exc is not None
        raise last_exc

    async def get_page(self, page_id: str) -> ConfluencePage:
        """Fetch a single page by ID with its XHTML storage body."""
        url = f"{self._base}/content/{page_id}"
        params: dict[str, Any] = {"expand": "body.storage,version,space"}
        data = await self._get(url, params)
        return _parse_page(data)

    async def get_pages(self, page_ids: list[str]) -> list[ConfluencePage]:
        """Fetch multiple pages by ID concurrently.

        Individual page failures are logged and skipped.
        """
        semaphore = asyncio.Semaphore(_FETCH_CONCURRENCY)
        results: list[ConfluencePage] = []
        lock = asyncio.Lock()

        async def _fetch_one(pid: str) -> None:
            async with semaphore:
                try:
                    page = await self.get_page(pid)
                except (httpx.HTTPStatusError, KeyError) as e:
                    logger.warning("Skipping page %s: %s", pid, e)
                    return
                async with lock:
                    results.append(page)

        async with self:
            await asyncio.gather(*[_fetch_one(pid) for pid in page_ids])
        return results

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
        self,
        out_dir: Path,
        *,
        space_key: str | None = None,
        page_ids: list[str] | None = None,
        limit: int = 25,
    ) -> list[Path]:
        """Fetch pages and save their XHTML bodies to disk.

        Provide either space_key (lists pages from a space) or page_ids
        (fetches specific pages). Uses concurrent requests for speed.
        """
        if not space_key and not page_ids:
            msg = "Provide either space_key or page_ids"
            raise ValueError(msg)

        out_dir.mkdir(parents=True, exist_ok=True)

        if page_ids:
            pages = await self.get_pages(page_ids)
        else:
            assert space_key is not None
            async with self:
                summaries = await self.list_pages_in_space(space_key, limit=limit)
                if not summaries:
                    logger.warning("No pages found in space '%s'", space_key)
                    return []
                pages = await self._fetch_summaries(summaries)

        saved: list[Path] = []
        for page in pages:
            file_path = out_dir / f"{page.id}.xhtml"
            file_path.write_text(page.storage_body, encoding="utf-8")
            saved.append(file_path)
        return saved

    async def get_child_pages(self, page_id: str) -> list[ConfluencePageSummary]:
        """Fetch child pages of a given page with automatic pagination.

        Returns a list of ConfluencePageSummary for all direct children.
        """
        url = f"{self._base}/content/{page_id}/child/page"
        collected: list[ConfluencePageSummary] = []
        start = 0

        while True:
            params: dict[str, str | int] = {"limit": _API_MAX_PER_PAGE, "start": start}
            data = await self._get(url, params)
            results: list[dict[str, Any]] = data.get("results", [])
            if not results:
                break
            collected.extend(
                ConfluencePageSummary(id=r["id"], title=r["title"]) for r in results
            )
            if "_links" not in data or "next" not in data["_links"]:
                break
            start += len(results)

        return collected

    async def collect_page_tree(
        self, root_id: str, max_depth: int = 10
    ) -> PageTreeNode:
        """Recursively build a page tree starting from root_id.

        Fetches the root page title, then recursively collects children
        up to max_depth levels deep. Uses _FETCH_CONCURRENCY semaphore
        to limit concurrent requests.
        """
        semaphore = asyncio.Semaphore(_FETCH_CONCURRENCY)

        # Fetch root page title
        root_data = await self._get(f"{self._base}/content/{root_id}")
        root_title: str = root_data.get("title", root_id)

        async def _build_node(
            page_id: str, title: str, depth: int
        ) -> PageTreeNode:
            if depth >= max_depth:
                return PageTreeNode(id=page_id, title=title)

            async with semaphore:
                children_summaries = await self.get_child_pages(page_id)

            child_nodes = await asyncio.gather(
                *[
                    _build_node(c.id, c.title, depth + 1)
                    for c in children_summaries
                ]
            )
            return PageTreeNode(
                id=page_id, title=title, children=list(child_nodes)
            )

        return await _build_node(root_id, root_title, 0)

    async def _fetch_summaries(
        self, summaries: list[ConfluencePageSummary]
    ) -> list[ConfluencePage]:
        """Fetch full page data for a list of summaries, concurrently."""
        semaphore = asyncio.Semaphore(_FETCH_CONCURRENCY)
        results: list[ConfluencePage] = []
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
                async with lock:
                    results.append(page)

        await asyncio.gather(*[_fetch_one(s) for s in summaries])
        return results


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
