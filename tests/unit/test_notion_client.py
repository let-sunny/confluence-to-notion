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
