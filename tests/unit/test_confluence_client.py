"""Unit tests for the Confluence async client."""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx

from confluence_to_notion.config import Settings
from confluence_to_notion.confluence.client import (
    _CONNECT_TIMEOUT,
    _MAX_RETRIES,
    _READ_TIMEOUT,
    ConfluenceClient,
)
from confluence_to_notion.confluence.schemas import (
    ConfluencePage,
    ConfluencePageSummary,
    PageTreeNode,
)

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


# --- Timeout and retry ---


async def test_client_timeout_configured(confluence_client: ConfluenceClient) -> None:
    """httpx.AsyncClient is created with connect/read timeout."""
    async with confluence_client as client:
        assert client._owned_client is not None
        timeout = client._owned_client.timeout
        assert timeout.connect == _CONNECT_TIMEOUT
        assert timeout.read == _READ_TIMEOUT


@respx.mock
@patch("confluence_to_notion.confluence.client.asyncio.sleep", return_value=None)
async def test_retry_on_transient_5xx(
    mock_sleep: AsyncMock, confluence_client: ConfluenceClient
) -> None:
    """Transient 5xx followed by success retries and returns result."""
    call_count = 0

    def _handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(500, json={"message": "Internal Server Error"})
        return httpx.Response(200, json=_page_json("123", "Retry OK"))

    respx.get(f"{BASE}/content/123").mock(side_effect=_handler)

    async with confluence_client as client:
        page = await client.get_page("123")

    assert page.id == "123"
    assert page.title == "Retry OK"
    assert call_count == 2


@respx.mock
@patch("confluence_to_notion.confluence.client.asyncio.sleep", return_value=None)
async def test_retry_on_timeout_exception(
    mock_sleep: AsyncMock, confluence_client: ConfluenceClient
) -> None:
    """httpx.TimeoutException triggers retry and succeeds on next attempt."""
    call_count = 0

    def _handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise httpx.TimeoutException("Connection timed out")
        return httpx.Response(200, json=_page_json("456", "After Timeout"))

    respx.get(f"{BASE}/content/456").mock(side_effect=_handler)

    async with confluence_client as client:
        page = await client.get_page("456")

    assert page.id == "456"
    assert call_count == 2


@respx.mock
async def test_no_retry_on_4xx(confluence_client: ConfluenceClient) -> None:
    """Non-retryable 4xx raises immediately without retry."""
    call_count = 0

    def _handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(403, json={"message": "Forbidden"})

    respx.get(f"{BASE}/content/forbidden").mock(side_effect=_handler)

    async with confluence_client as client:
        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            await client.get_page("forbidden")
        assert exc_info.value.response.status_code == 403

    assert call_count == 1


@respx.mock
@patch("confluence_to_notion.confluence.client.asyncio.sleep", return_value=None)
async def test_retries_exhausted_raises(
    mock_sleep: AsyncMock, confluence_client: ConfluenceClient
) -> None:
    """All retries exhausted on persistent 5xx raises after _MAX_RETRIES attempts."""
    call_count = 0

    def _handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(502, json={"message": "Bad Gateway"})

    respx.get(f"{BASE}/content/bad-gw").mock(side_effect=_handler)

    async with confluence_client as client:
        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            await client.get_page("bad-gw")
        assert exc_info.value.response.status_code == 502

    # 1 initial + _MAX_RETRIES retries
    assert call_count == 1 + _MAX_RETRIES


@respx.mock
@patch("confluence_to_notion.confluence.client.asyncio.sleep", return_value=None)
async def test_oneshot_path_retries_on_5xx(
    mock_sleep: AsyncMock, confluence_client: ConfluenceClient
) -> None:
    """One-shot client path (no async-with) retries on transient 5xx."""
    call_count = 0

    def _handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(503, json={"message": "Service Unavailable"})
        return httpx.Response(200, json=_page_json("789", "Oneshot OK"))

    respx.get(f"{BASE}/content/789").mock(side_effect=_handler)

    # Call without `async with` — exercises the per-attempt AsyncClient branch
    page = await confluence_client.get_page("789")

    assert page.id == "789"
    assert page.title == "Oneshot OK"
    assert call_count == 2


# --- PageTreeNode schema ---


class TestPageTreeNode:
    """PageTreeNode model validation."""

    def test_flat_node(self) -> None:
        node = PageTreeNode(id="1", title="Root")
        assert node.id == "1"
        assert node.title == "Root"
        assert node.children == []

    def test_nested_children(self) -> None:
        node = PageTreeNode(
            id="1",
            title="Root",
            children=[
                PageTreeNode(id="2", title="Child A"),
                PageTreeNode(
                    id="3",
                    title="Child B",
                    children=[PageTreeNode(id="4", title="Grandchild")],
                ),
            ],
        )
        assert len(node.children) == 2
        assert node.children[1].children[0].id == "4"

    def test_serialization_round_trip(self) -> None:
        node = PageTreeNode(
            id="1",
            title="Root",
            children=[PageTreeNode(id="2", title="Child")],
        )
        json_str = node.model_dump_json()
        restored = PageTreeNode.model_validate_json(json_str)
        assert restored == node


# --- get_child_pages ---


@respx.mock
async def test_get_child_pages(confluence_client: ConfluenceClient) -> None:
    """Fetches child page summaries for a given page ID."""
    respx.get(f"{BASE}/content/root/child/page").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {"id": "c1", "title": "Child 1"},
                    {"id": "c2", "title": "Child 2"},
                ],
            },
        )
    )
    children = await confluence_client.get_child_pages("root")

    assert len(children) == 2
    assert all(isinstance(c, ConfluencePageSummary) for c in children)
    assert children[0].id == "c1"
    assert children[1].id == "c2"


@respx.mock
async def test_get_child_pages_empty(confluence_client: ConfluenceClient) -> None:
    """Returns empty list when a page has no children."""
    respx.get(f"{BASE}/content/leaf/child/page").mock(
        return_value=httpx.Response(200, json={"results": []})
    )
    children = await confluence_client.get_child_pages("leaf")
    assert children == []


@respx.mock
async def test_get_child_pages_pagination(confluence_client: ConfluenceClient) -> None:
    """Handles pagination when children span multiple API pages."""
    page1 = {
        "results": [{"id": f"{i}", "title": f"P{i}"} for i in range(25)],
        "_links": {"next": "/rest/api/content/root/child/page?start=25"},
    }
    page2 = {
        "results": [{"id": "25", "title": "P25"}],
    }

    def _route(request: httpx.Request) -> httpx.Response:
        start = int(request.url.params.get("start", "0"))
        return httpx.Response(200, json=page1 if start == 0 else page2)

    respx.get(f"{BASE}/content/root/child/page").mock(side_effect=_route)
    children = await confluence_client.get_child_pages("root")

    assert len(children) == 26


# --- collect_page_tree ---


@respx.mock
async def test_collect_page_tree(confluence_client: ConfluenceClient) -> None:
    """Builds a recursive tree from root → children → grandchildren."""
    # Root has two children
    respx.get(f"{BASE}/content/root/child/page").mock(
        return_value=httpx.Response(
            200,
            json={"results": [
                {"id": "a", "title": "A"},
                {"id": "b", "title": "B"},
            ]},
        )
    )
    # Child A has one grandchild
    respx.get(f"{BASE}/content/a/child/page").mock(
        return_value=httpx.Response(
            200,
            json={"results": [{"id": "a1", "title": "A1"}]},
        )
    )
    # Child B and grandchild A1 are leaves
    respx.get(f"{BASE}/content/b/child/page").mock(
        return_value=httpx.Response(200, json={"results": []})
    )
    respx.get(f"{BASE}/content/a1/child/page").mock(
        return_value=httpx.Response(200, json={"results": []})
    )
    # Mock root page title lookup
    respx.get(f"{BASE}/content/root").mock(
        return_value=httpx.Response(200, json=_page_json("root", "Root Page"))
    )

    tree = await confluence_client.collect_page_tree("root")

    assert isinstance(tree, PageTreeNode)
    assert tree.id == "root"
    assert tree.title == "Root Page"
    assert len(tree.children) == 2
    child_a = next(c for c in tree.children if c.id == "a")
    assert len(child_a.children) == 1
    assert child_a.children[0].id == "a1"


@respx.mock
async def test_collect_page_tree_depth_limit(confluence_client: ConfluenceClient) -> None:
    """Stops recursion at max_depth."""
    respx.get(f"{BASE}/content/root").mock(
        return_value=httpx.Response(200, json=_page_json("root", "Root"))
    )
    respx.get(f"{BASE}/content/root/child/page").mock(
        return_value=httpx.Response(
            200,
            json={"results": [{"id": "d1", "title": "Depth 1"}]},
        )
    )
    # depth-1 children should NOT be fetched when max_depth=1
    respx.get(f"{BASE}/content/d1/child/page").mock(
        return_value=httpx.Response(
            200,
            json={"results": [{"id": "d2", "title": "Depth 2"}]},
        )
    )

    tree = await confluence_client.collect_page_tree("root", max_depth=1)

    assert tree.id == "root"
    assert len(tree.children) == 1
    assert tree.children[0].id == "d1"
    # At max_depth=1, children of d1 should NOT be fetched
    assert tree.children[0].children == []
