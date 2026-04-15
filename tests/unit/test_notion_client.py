"""Unit tests for the Notion async client wrapper."""

from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from notion_client import APIResponseError

from confluence_to_notion.config import Settings
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
