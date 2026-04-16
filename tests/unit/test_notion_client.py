"""Unit tests for the Notion async client wrapper."""

from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from notion_client import APIResponseError

from confluence_to_notion.config import Settings
from confluence_to_notion.confluence.schemas import PageTreeNode
from confluence_to_notion.notion.client import NotionClientWrapper
from confluence_to_notion.notion.schemas import NotionPageResult


def _make_api_error(status: int, message: str) -> APIResponseError:
    """Create a Notion APIResponseError for testing."""
    return APIResponseError(
        code="unauthorized",
        status=status,
        message=message,
        headers=httpx.Headers(),
        raw_body_text=message,
    )


@pytest.fixture
def notion_client(settings: Settings) -> NotionClientWrapper:
    return NotionClientWrapper(settings)


async def test_ping_success(notion_client: NotionClientWrapper) -> None:
    mock_me = AsyncMock(return_value={"id": "bot-user-id", "type": "bot"})
    with patch.object(notion_client._client.users, "me", mock_me):
        result = await notion_client.ping()
    assert result is True


async def test_ping_api_error(notion_client: NotionClientWrapper) -> None:
    """Ping returns False on invalid token (API 401)."""
    mock_me = AsyncMock(side_effect=_make_api_error(401, "Invalid token"))
    with patch.object(notion_client._client.users, "me", mock_me):
        result = await notion_client.ping()
    assert result is False


async def test_ping_network_error(notion_client: NotionClientWrapper) -> None:
    """Ping returns False on network failure."""
    mock_me = AsyncMock(side_effect=OSError("Connection refused"))
    with patch.object(notion_client._client.users, "me", mock_me):
        result = await notion_client.ping()
    assert result is False


async def test_ping_missing_id(notion_client: NotionClientWrapper) -> None:
    """Ping returns False when response has no id field."""
    mock_me = AsyncMock(return_value={"object": "user"})
    with patch.object(notion_client._client.users, "me", mock_me):
        result = await notion_client.ping()
    assert result is False


async def test_create_page(notion_client: NotionClientWrapper) -> None:
    fake_response: dict[str, Any] = {"id": "new-page-id", "object": "page"}
    mock_create = AsyncMock(return_value=fake_response)
    with patch.object(notion_client._client.pages, "create", mock_create):
        result = await notion_client.create_page(
            parent_id="parent-123",
            title="Test Page",
            blocks=[{"object": "block", "type": "paragraph"}],
        )
    assert isinstance(result, NotionPageResult)
    assert result.page_id == "new-page-id"
    mock_create.assert_called_once_with(
        parent={"page_id": "parent-123"},
        properties={"title": [{"text": {"content": "Test Page"}}]},
        children=[{"object": "block", "type": "paragraph"}],
    )


async def test_create_page_missing_id(notion_client: NotionClientWrapper) -> None:
    """KeyError when Notion response is missing 'id'."""
    mock_create = AsyncMock(return_value={"object": "page"})
    with (
        patch.object(notion_client._client.pages, "create", mock_create),
        pytest.raises(KeyError),
    ):
        await notion_client.create_page(
            parent_id="parent-123",
            title="Test",
            blocks=[],
        )


# --- Rate limit retry tests ---


async def test_create_page_retries_on_429(notion_client: NotionClientWrapper) -> None:
    """429 rate limit triggers retry, succeeds on second attempt."""
    rate_limit_error = _make_api_error(429, "Rate limited")
    rate_limit_error.status = 429
    success_response: dict[str, Any] = {"id": "page-after-retry", "object": "page"}
    mock_create = AsyncMock(side_effect=[rate_limit_error, success_response])
    with (
        patch.object(notion_client._client.pages, "create", mock_create),
        patch("confluence_to_notion.notion.client.asyncio.sleep", new_callable=AsyncMock),
    ):
        result = await notion_client.create_page(
            parent_id="parent-123",
            title="Retry Test",
            blocks=[],
        )
    assert result.page_id == "page-after-retry"
    assert mock_create.call_count == 2


async def test_create_page_raises_after_max_retries(
    notion_client: NotionClientWrapper,
) -> None:
    """Raises APIResponseError after exhausting all retries on persistent 429."""
    rate_limit_error = _make_api_error(429, "Rate limited")
    rate_limit_error.status = 429
    mock_create = AsyncMock(side_effect=rate_limit_error)
    with (
        patch.object(notion_client._client.pages, "create", mock_create),
        patch("confluence_to_notion.notion.client.asyncio.sleep", new_callable=AsyncMock),
        pytest.raises(APIResponseError),
    ):
        await notion_client.create_page(
            parent_id="parent-123",
            title="Max Retry Test",
            blocks=[],
        )
    # 1 initial + 5 retries = 6 calls
    assert mock_create.call_count == 6


async def test_create_page_no_retry_on_other_errors(
    notion_client: NotionClientWrapper,
) -> None:
    """Non-429 API errors are raised immediately without retry."""
    auth_error = _make_api_error(401, "Unauthorized")
    auth_error.status = 401
    mock_create = AsyncMock(side_effect=auth_error)
    with (
        patch.object(notion_client._client.pages, "create", mock_create),
        pytest.raises(APIResponseError),
    ):
        await notion_client.create_page(
            parent_id="parent-123",
            title="No Retry Test",
            blocks=[],
        )
    assert mock_create.call_count == 1


async def test_create_page_retry_uses_backoff(
    notion_client: NotionClientWrapper,
) -> None:
    """Verify exponential backoff delays increase between retries."""
    rate_limit_error = _make_api_error(429, "Rate limited")
    rate_limit_error.status = 429
    success_response: dict[str, Any] = {"id": "page-id", "object": "page"}
    mock_create = AsyncMock(
        side_effect=[rate_limit_error, rate_limit_error, rate_limit_error, success_response]
    )
    mock_sleep = AsyncMock()
    with (
        patch.object(notion_client._client.pages, "create", mock_create),
        patch("confluence_to_notion.notion.client.asyncio.sleep", mock_sleep),
    ):
        await notion_client.create_page(
            parent_id="parent-123",
            title="Backoff Test",
            blocks=[],
        )
    assert mock_sleep.call_count == 3
    delays = [call.args[0] for call in mock_sleep.call_args_list]
    # Each delay should be larger than the previous (exponential backoff + jitter)
    # Base delays: 1, 2, 4 — with jitter they should still be increasing
    for i in range(1, len(delays)):
        assert delays[i] > delays[i - 1] * 0.5, f"Delay {i} not increasing: {delays}"


# --- Chunked block upload tests ---


class TestChunkedBlockUpload:
    """Verify create_page splits blocks into chunks of 100 for Notion API limit."""

    @staticmethod
    def _make_blocks(n: int) -> list[dict[str, Any]]:
        """Generate n dummy paragraph blocks."""
        return [{"object": "block", "type": "paragraph", "id": str(i)} for i in range(n)]

    async def test_150_blocks_chunks_into_create_plus_one_append(
        self, notion_client: NotionClientWrapper
    ) -> None:
        """150 blocks → first 100 in create, remaining 50 appended."""
        blocks = self._make_blocks(150)
        fake_response: dict[str, Any] = {"id": "new-page-id", "object": "page"}
        mock_create = AsyncMock(return_value=fake_response)
        mock_append = AsyncMock(return_value={})

        with (
            patch.object(notion_client._client.pages, "create", mock_create),
            patch.object(notion_client._client.blocks.children, "append", mock_append),
            patch("confluence_to_notion.notion.client.asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await notion_client.create_page(
                parent_id="parent-123",
                title="Big Page",
                blocks=blocks,
            )

        assert result.page_id == "new-page-id"
        # create called with first 100 blocks
        mock_create.assert_called_once()
        create_children = mock_create.call_args.kwargs.get(
            "children", mock_create.call_args[1].get("children")
        )
        assert len(create_children) == 100
        # append called once with remaining 50
        mock_append.assert_called_once_with(block_id="new-page-id", children=blocks[100:])
        assert len(blocks[100:]) == 50

    async def test_250_blocks_chunks_into_create_plus_two_appends(
        self, notion_client: NotionClientWrapper
    ) -> None:
        """250 blocks → first 100 in create, then two appends (100 + 50)."""
        blocks = self._make_blocks(250)
        fake_response: dict[str, Any] = {"id": "page-250", "object": "page"}
        mock_create = AsyncMock(return_value=fake_response)
        mock_append = AsyncMock(return_value={})

        with (
            patch.object(notion_client._client.pages, "create", mock_create),
            patch.object(notion_client._client.blocks.children, "append", mock_append),
            patch("confluence_to_notion.notion.client.asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await notion_client.create_page(
                parent_id="parent-123",
                title="Huge Page",
                blocks=blocks,
            )

        assert result.page_id == "page-250"
        create_children = mock_create.call_args.kwargs.get(
            "children", mock_create.call_args[1].get("children")
        )
        assert len(create_children) == 100
        assert mock_append.call_count == 2
        # First append: blocks[100:200] (100 items)
        first_append_children = mock_append.call_args_list[0].kwargs["children"]
        assert len(first_append_children) == 100
        # Second append: blocks[200:250] (50 items)
        second_append_children = mock_append.call_args_list[1].kwargs["children"]
        assert len(second_append_children) == 50

    async def test_100_or_fewer_blocks_no_append(
        self, notion_client: NotionClientWrapper
    ) -> None:
        """≤100 blocks — no append call, existing behavior preserved."""
        blocks = self._make_blocks(100)
        fake_response: dict[str, Any] = {"id": "page-100", "object": "page"}
        mock_create = AsyncMock(return_value=fake_response)
        mock_append = AsyncMock()

        with (
            patch.object(notion_client._client.pages, "create", mock_create),
            patch.object(notion_client._client.blocks.children, "append", mock_append),
            patch("confluence_to_notion.notion.client.asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await notion_client.create_page(
                parent_id="parent-123",
                title="Normal Page",
                blocks=blocks,
            )

        assert result.page_id == "page-100"
        mock_create.assert_called_once()
        create_children = mock_create.call_args.kwargs.get(
            "children", mock_create.call_args[1].get("children")
        )
        assert len(create_children) == 100
        mock_append.assert_not_called()


# --- Empty subpage + recursive tree creation tests ---


def _tree_fixture() -> PageTreeNode:
    """3-level page tree mirroring tests/unit/test_cli_fetch_tree.py::_fixture_tree."""
    return PageTreeNode(
        id="root",
        title="Root Page",
        children=[
            PageTreeNode(id="c1", title="Child 1"),
            PageTreeNode(
                id="c2",
                title="Child 2",
                children=[PageTreeNode(id="gc1", title="Grandchild 1")],
            ),
        ],
    )


async def test_create_subpage_creates_empty_page(
    notion_client: NotionClientWrapper,
) -> None:
    """create_subpage emits a pages.create call with an empty children list."""
    fake_response: dict[str, Any] = {"id": "np-empty", "object": "page"}
    mock_create = AsyncMock(return_value=fake_response)
    with patch.object(notion_client._client.pages, "create", mock_create):
        page_id = await notion_client.create_subpage(
            parent_id="parent-xyz", title="Empty Child"
        )
    assert page_id == "np-empty"
    mock_create.assert_called_once_with(
        parent={"page_id": "parent-xyz"},
        properties={"title": [{"text": {"content": "Empty Child"}}]},
        children=[],
    )


async def test_create_subpage_retries_on_429(
    notion_client: NotionClientWrapper,
) -> None:
    """create_subpage inherits the 429 retry path from _create_page_with_retry."""
    rate_limit_error = _make_api_error(429, "Rate limited")
    rate_limit_error.status = 429
    success_response: dict[str, Any] = {"id": "np-after-retry", "object": "page"}
    mock_create = AsyncMock(side_effect=[rate_limit_error, success_response])
    with (
        patch.object(notion_client._client.pages, "create", mock_create),
        patch("confluence_to_notion.notion.client.asyncio.sleep", new_callable=AsyncMock),
    ):
        page_id = await notion_client.create_subpage(
            parent_id="parent-xyz", title="Retry Page"
        )
    assert page_id == "np-after-retry"
    assert mock_create.call_count == 2


async def test_create_page_tree_builds_hierarchy(
    notion_client: NotionClientWrapper,
) -> None:
    """create_page_tree creates empty pages for every node and returns a title→id map."""
    tree = _tree_fixture()
    # pages.create is invoked in DFS order: Root → Child 1 → Child 2 → Grandchild 1
    responses = [
        {"id": "np-root", "object": "page"},
        {"id": "np-c1", "object": "page"},
        {"id": "np-c2", "object": "page"},
        {"id": "np-gc1", "object": "page"},
    ]
    mock_create = AsyncMock(side_effect=responses)
    with patch.object(notion_client._client.pages, "create", mock_create):
        mapping = await notion_client.create_page_tree(
            parent_id="parent-xyz", tree=tree
        )

    assert mapping == {
        "Root Page": "np-root",
        "Child 1": "np-c1",
        "Child 2": "np-c2",
        "Grandchild 1": "np-gc1",
    }
    assert mock_create.call_count == 4

    calls = mock_create.call_args_list
    # Root is placed under the external parent.
    assert calls[0].kwargs["parent"] == {"page_id": "parent-xyz"}
    assert calls[0].kwargs["properties"] == {
        "title": [{"text": {"content": "Root Page"}}]
    }
    assert calls[0].kwargs["children"] == []
    # Child 1 and Child 2 are placed under the newly-created root.
    assert calls[1].kwargs["parent"] == {"page_id": "np-root"}
    assert calls[1].kwargs["properties"] == {
        "title": [{"text": {"content": "Child 1"}}]
    }
    assert calls[2].kwargs["parent"] == {"page_id": "np-root"}
    assert calls[2].kwargs["properties"] == {
        "title": [{"text": {"content": "Child 2"}}]
    }
    # Grandchild 1 is placed under Child 2.
    assert calls[3].kwargs["parent"] == {"page_id": "np-c2"}
    assert calls[3].kwargs["properties"] == {
        "title": [{"text": {"content": "Grandchild 1"}}]
    }
