"""Unit tests for the Confluence async client."""

from pathlib import Path

import httpx
import pytest
import respx

from confluence_to_notion.config import Settings
from confluence_to_notion.confluence.client import ConfluenceClient
from confluence_to_notion.confluence.schemas import ConfluencePage, ConfluencePageSummary

BASE = "https://test.atlassian.net/wiki/rest/api"


@pytest.fixture
def confluence_client(settings: Settings) -> ConfluenceClient:
    return ConfluenceClient(settings)


GET_PAGE_RESPONSE = {
    "id": "12345",
    "title": "Test Page",
    "space": {"key": "DEV"},
    "body": {"storage": {"value": "<p>Hello World</p>"}},
    "version": {"number": 3, "when": "2026-01-15T10:30:00.000Z"},
}

LIST_PAGES_RESPONSE = {
    "results": [
        {"id": "111", "title": "Page One"},
        {"id": "222", "title": "Page Two"},
        {"id": "333", "title": "Page Three"},
    ]
}


@respx.mock
async def test_get_page(confluence_client: ConfluenceClient) -> None:
    respx.get(f"{BASE}/content/12345").mock(
        return_value=httpx.Response(200, json=GET_PAGE_RESPONSE)
    )
    page = await confluence_client.get_page("12345")

    assert isinstance(page, ConfluencePage)
    assert page.id == "12345"
    assert page.title == "Test Page"
    assert page.space_key == "DEV"
    assert page.storage_body == "<p>Hello World</p>"
    assert page.version == 3


@respx.mock
async def test_list_pages_in_space(confluence_client: ConfluenceClient) -> None:
    respx.get(f"{BASE}/content").mock(
        return_value=httpx.Response(200, json=LIST_PAGES_RESPONSE)
    )
    pages = await confluence_client.list_pages_in_space("DEV", limit=10)

    assert len(pages) == 3
    assert all(isinstance(p, ConfluencePageSummary) for p in pages)
    assert pages[0].id == "111"
    assert pages[1].title == "Page Two"


@respx.mock
async def test_get_page_http_error(confluence_client: ConfluenceClient) -> None:
    respx.get(f"{BASE}/content/99999").mock(
        return_value=httpx.Response(404, json={"message": "Not found"})
    )
    with pytest.raises(httpx.HTTPStatusError):
        await confluence_client.get_page("99999")


@respx.mock
async def test_fetch_samples_to_disk(
    confluence_client: ConfluenceClient, tmp_path: Path
) -> None:
    respx.get(f"{BASE}/content").mock(
        return_value=httpx.Response(
            200,
            json={"results": [{"id": "111", "title": "Page One"}]},
        )
    )
    respx.get(f"{BASE}/content/111").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "111",
                "title": "Page One",
                "space": {"key": "DEV"},
                "body": {"storage": {"value": "<h1>Sample</h1>"}},
                "version": {"number": 1, "when": "2026-01-01T00:00:00.000Z"},
            },
        )
    )

    saved = await confluence_client.fetch_samples_to_disk("DEV", tmp_path, limit=5)

    assert len(saved) == 1
    assert saved[0].name == "111.xhtml"
    assert saved[0].read_text() == "<h1>Sample</h1>"


@respx.mock
async def test_get_page_malformed_response(confluence_client: ConfluenceClient) -> None:
    """KeyError with a helpful message when response is missing expected fields."""
    respx.get(f"{BASE}/content/bad").mock(
        return_value=httpx.Response(200, json={"id": "bad", "title": "Broken"})
    )
    with pytest.raises(KeyError, match="missing expected field"):
        await confluence_client.get_page("bad")


@respx.mock
async def test_list_pages_empty_space(confluence_client: ConfluenceClient) -> None:
    """Empty results list returns an empty list, not an error."""
    respx.get(f"{BASE}/content").mock(
        return_value=httpx.Response(200, json={"results": []})
    )
    pages = await confluence_client.list_pages_in_space("EMPTY")
    assert pages == []


@respx.mock
async def test_fetch_samples_partial_failure(
    confluence_client: ConfluenceClient, tmp_path: Path
) -> None:
    """If one page fails to fetch, the others are still saved."""
    respx.get(f"{BASE}/content").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {"id": "aaa", "title": "Good Page"},
                    {"id": "bbb", "title": "Bad Page"},
                ]
            },
        )
    )
    respx.get(f"{BASE}/content/aaa").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "aaa",
                "title": "Good Page",
                "space": {"key": "DEV"},
                "body": {"storage": {"value": "<p>ok</p>"}},
                "version": {"number": 1, "when": "2026-01-01T00:00:00.000Z"},
            },
        )
    )
    respx.get(f"{BASE}/content/bbb").mock(
        return_value=httpx.Response(404, json={"message": "Not found"})
    )

    saved = await confluence_client.fetch_samples_to_disk("DEV", tmp_path, limit=5)

    assert len(saved) == 1
    assert saved[0].name == "aaa.xhtml"


@respx.mock
async def test_list_pages_pagination(confluence_client: ConfluenceClient) -> None:
    """Fetches multiple pages of results when limit exceeds one batch."""
    page1 = {
        "results": [{"id": "1", "title": "P1"}, {"id": "2", "title": "P2"}],
        "_links": {"next": "/rest/api/content?start=2"},
    }
    page2 = {
        "results": [{"id": "3", "title": "P3"}],
        # No _links.next → last page
    }

    call_count = 0

    def _route(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        start = int(request.url.params.get("start", "0"))
        if start == 0:
            return httpx.Response(200, json=page1)
        return httpx.Response(200, json=page2)

    respx.get(f"{BASE}/content").mock(side_effect=_route)

    pages = await confluence_client.list_pages_in_space("DEV", limit=5)

    assert len(pages) == 3
    assert [p.id for p in pages] == ["1", "2", "3"]
    assert call_count == 2


@respx.mock
async def test_list_pages_stops_at_limit(confluence_client: ConfluenceClient) -> None:
    """Pagination stops when the requested limit is reached."""
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
        if start == 0:
            return httpx.Response(200, json=page1)
        return httpx.Response(200, json=page2)

    respx.get(f"{BASE}/content").mock(side_effect=_route)

    pages = await confluence_client.list_pages_in_space("DEV", limit=4)

    # Should stop at 4, not fetch all 6
    assert len(pages) == 4
