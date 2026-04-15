"""Unit tests for the Confluence async client."""

from pathlib import Path

import httpx
import pytest
import respx

from confluence_to_notion.config import Settings
from confluence_to_notion.confluence.client import ConfluenceClient
from confluence_to_notion.confluence.schemas import ConfluencePage, ConfluencePageSummary

BASE = "https://test.atlassian.net/wiki/rest/api"
PUBLIC_BASE = "https://cwiki.apache.org/confluence/rest/api"


@pytest.fixture
def confluence_client(settings: Settings) -> ConfluenceClient:
    return ConfluenceClient(settings)


@pytest.fixture
def public_client(public_settings: Settings) -> ConfluenceClient:
    return ConfluenceClient(public_settings)


def _page_json(page_id: str, title: str, space: str = "DEV") -> dict:
    return {
        "id": page_id,
        "title": title,
        "space": {"key": space},
        "body": {"storage": {"value": f"<p>{title}</p>"}},
        "version": {"number": 1, "when": "2026-01-01T00:00:00.000Z"},
    }


# --- get_page ---


@respx.mock
async def test_get_page(confluence_client: ConfluenceClient) -> None:
    respx.get(f"{BASE}/content/12345").mock(
        return_value=httpx.Response(200, json=_page_json("12345", "Test Page"))
    )
    page = await confluence_client.get_page("12345")

    assert isinstance(page, ConfluencePage)
    assert page.id == "12345"
    assert page.title == "Test Page"
    assert page.space_key == "DEV"
    assert page.storage_body == "<p>Test Page</p>"


@respx.mock
async def test_get_page_http_error(confluence_client: ConfluenceClient) -> None:
    respx.get(f"{BASE}/content/99999").mock(
        return_value=httpx.Response(404, json={"message": "Not found"})
    )
    with pytest.raises(httpx.HTTPStatusError):
        await confluence_client.get_page("99999")


@respx.mock
async def test_get_page_malformed_response(confluence_client: ConfluenceClient) -> None:
    respx.get(f"{BASE}/content/bad").mock(
        return_value=httpx.Response(200, json={"id": "bad", "title": "Broken"})
    )
    with pytest.raises(KeyError, match="missing expected field"):
        await confluence_client.get_page("bad")


# --- get_pages (batch by ID) ---


@respx.mock
async def test_get_pages(confluence_client: ConfluenceClient) -> None:
    """Fetch multiple specific pages by ID."""
    respx.get(f"{BASE}/content/aaa").mock(
        return_value=httpx.Response(200, json=_page_json("aaa", "Page A"))
    )
    respx.get(f"{BASE}/content/bbb").mock(
        return_value=httpx.Response(200, json=_page_json("bbb", "Page B"))
    )
    pages = await confluence_client.get_pages(["aaa", "bbb"])

    assert len(pages) == 2
    ids = {p.id for p in pages}
    assert ids == {"aaa", "bbb"}


@respx.mock
async def test_get_pages_skips_failures(confluence_client: ConfluenceClient) -> None:
    """Failed page IDs are skipped, successful ones are returned."""
    respx.get(f"{BASE}/content/good").mock(
        return_value=httpx.Response(200, json=_page_json("good", "OK"))
    )
    respx.get(f"{BASE}/content/bad").mock(
        return_value=httpx.Response(404, json={"message": "Not found"})
    )
    pages = await confluence_client.get_pages(["good", "bad"])

    assert len(pages) == 1
    assert pages[0].id == "good"


# --- list_pages_in_space ---


@respx.mock
async def test_list_pages_in_space(confluence_client: ConfluenceClient) -> None:
    respx.get(f"{BASE}/content").mock(
        return_value=httpx.Response(
            200,
            json={"results": [{"id": "1", "title": "P1"}, {"id": "2", "title": "P2"}]},
        )
    )
    pages = await confluence_client.list_pages_in_space("DEV", limit=10)

    assert len(pages) == 2
    assert all(isinstance(p, ConfluencePageSummary) for p in pages)


@respx.mock
async def test_list_pages_empty_space(confluence_client: ConfluenceClient) -> None:
    respx.get(f"{BASE}/content").mock(
        return_value=httpx.Response(200, json={"results": []})
    )
    pages = await confluence_client.list_pages_in_space("EMPTY")
    assert pages == []


@respx.mock
async def test_list_pages_pagination(confluence_client: ConfluenceClient) -> None:
    page1 = {
        "results": [{"id": "1", "title": "P1"}, {"id": "2", "title": "P2"}],
        "_links": {"next": "/rest/api/content?start=2"},
    }
    page2 = {"results": [{"id": "3", "title": "P3"}]}

    call_count = 0

    def _route(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        start = int(request.url.params.get("start", "0"))
        return httpx.Response(200, json=page1 if start == 0 else page2)

    respx.get(f"{BASE}/content").mock(side_effect=_route)
    pages = await confluence_client.list_pages_in_space("DEV", limit=5)

    assert len(pages) == 3
    assert [p.id for p in pages] == ["1", "2", "3"]
    assert call_count == 2


@respx.mock
async def test_list_pages_stops_at_limit(confluence_client: ConfluenceClient) -> None:
    page1 = {
        "results": [{"id": str(i), "title": f"P{i}"} for i in range(3)],
        "_links": {"next": "/rest/api/content?start=3"},
    }
    page2 = {
        "results": [{"id": str(i), "title": f"P{i}"} for i in range(3, 6)],
        "_links": {"next": "/rest/api/content?start=6"},
    }

    def _route(request: httpx.Request) -> httpx.Response:
        start = int(request.url.params.get("start", "0"))
        return httpx.Response(200, json=page1 if start == 0 else page2)

    respx.get(f"{BASE}/content").mock(side_effect=_route)
    pages = await confluence_client.list_pages_in_space("DEV", limit=4)
    assert len(pages) == 4


# --- fetch_samples_to_disk ---


@respx.mock
async def test_fetch_samples_by_space(
    confluence_client: ConfluenceClient, tmp_path: Path
) -> None:
    respx.get(f"{BASE}/content").mock(
        return_value=httpx.Response(
            200, json={"results": [{"id": "111", "title": "Page One"}]}
        )
    )
    respx.get(f"{BASE}/content/111").mock(
        return_value=httpx.Response(200, json=_page_json("111", "Page One"))
    )

    saved = await confluence_client.fetch_samples_to_disk(
        tmp_path, space_key="DEV", limit=5
    )

    assert len(saved) == 1
    assert saved[0].name == "111.xhtml"


@respx.mock
async def test_fetch_samples_by_page_ids(
    confluence_client: ConfluenceClient, tmp_path: Path
) -> None:
    """Fetch specific pages by ID (--pages mode)."""
    respx.get(f"{BASE}/content/aaa").mock(
        return_value=httpx.Response(200, json=_page_json("aaa", "A"))
    )
    respx.get(f"{BASE}/content/bbb").mock(
        return_value=httpx.Response(200, json=_page_json("bbb", "B"))
    )

    saved = await confluence_client.fetch_samples_to_disk(
        tmp_path, page_ids=["aaa", "bbb"]
    )

    assert len(saved) == 2
    names = {p.name for p in saved}
    assert names == {"aaa.xhtml", "bbb.xhtml"}


@respx.mock
async def test_fetch_samples_partial_failure(
    confluence_client: ConfluenceClient, tmp_path: Path
) -> None:
    respx.get(f"{BASE}/content").mock(
        return_value=httpx.Response(
            200,
            json={"results": [
                {"id": "aaa", "title": "Good"},
                {"id": "bbb", "title": "Bad"},
            ]},
        )
    )
    respx.get(f"{BASE}/content/aaa").mock(
        return_value=httpx.Response(200, json=_page_json("aaa", "Good"))
    )
    respx.get(f"{BASE}/content/bbb").mock(
        return_value=httpx.Response(404, json={"message": "Not found"})
    )

    saved = await confluence_client.fetch_samples_to_disk(
        tmp_path, space_key="DEV", limit=5
    )

    assert len(saved) == 1
    assert saved[0].name == "aaa.xhtml"


async def test_fetch_samples_requires_space_or_pages(
    confluence_client: ConfluenceClient, tmp_path: Path
) -> None:
    """Raises ValueError if neither space_key nor page_ids is provided."""
    with pytest.raises(ValueError, match="space_key or page_ids"):
        await confluence_client.fetch_samples_to_disk(tmp_path)


# --- Public wiki (no auth) ---


@respx.mock
async def test_public_wiki_no_auth(public_client: ConfluenceClient) -> None:
    """Public wiki client sends requests without auth headers."""
    respx.get(f"{PUBLIC_BASE}/content/42").mock(
        return_value=httpx.Response(
            200, json=_page_json("42", "Public Page", "KAFKA")
        )
    )
    page = await public_client.get_page("42")
    assert page.id == "42"
    assert page.space_key == "KAFKA"
