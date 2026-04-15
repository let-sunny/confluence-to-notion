"""Unit tests for configuration loading."""

import pytest
from pydantic import ValidationError

from confluence_to_notion.config import Settings

# Reusable valid kwargs to build settings from
_VALID = dict(
    confluence_base_url="https://test.atlassian.net/wiki",
    confluence_email="user@example.com",
    confluence_api_token="token123",
    notion_api_token="ntn_xxx",
    notion_root_page_id="page-id",
    anthropic_api_key="sk-ant-xxx",
)


def test_settings_with_all_fields() -> None:
    """Settings loads when all required fields are provided."""
    s = Settings(**_VALID)
    assert s.confluence_base_url == "https://test.atlassian.net/wiki"
    assert s.anthropic_model == "claude-sonnet-4-5-20250929"


def test_settings_default_api_path() -> None:
    s = Settings(**_VALID)
    assert s.confluence_api_path == "/rest/api"


def test_settings_rest_url_property() -> None:
    s = Settings(**_VALID, confluence_api_path="/rest/api/v2")
    assert s.confluence_rest_url == "https://test.atlassian.net/wiki/rest/api/v2"


def test_settings_rest_url_strips_trailing_slash() -> None:
    s = Settings(**{**_VALID, "confluence_base_url": "https://test.atlassian.net/wiki/"})
    assert s.confluence_rest_url == "https://test.atlassian.net/wiki/rest/api"


def test_settings_missing_required_field(monkeypatch: pytest.MonkeyPatch) -> None:
    """Settings raises ValidationError when required fields are missing."""
    for key in _VALID:
        monkeypatch.delenv(key.upper(), raising=False)
    with pytest.raises(ValidationError):
        Settings()  # type: ignore[call-arg]


def test_settings_invalid_confluence_url() -> None:
    """Rejects confluence_base_url that doesn't start with http(s)://."""
    with pytest.raises(ValidationError, match="must start with http"):
        Settings(**{**_VALID, "confluence_base_url": "not-a-url"})


def test_settings_invalid_api_path() -> None:
    """Rejects confluence_api_path that doesn't start with /."""
    with pytest.raises(ValidationError, match="must start with /"):
        Settings(**{**_VALID, "confluence_api_path": "rest/api"})


def test_settings_invalid_notion_token() -> None:
    """Rejects notion_api_token that doesn't match known prefixes."""
    with pytest.raises(ValidationError, match="must start with"):
        Settings(**{**_VALID, "notion_api_token": "bad-token"})


def test_settings_notion_secret_prefix_accepted() -> None:
    """Notion legacy 'secret_' prefix tokens are also valid."""
    s = Settings(**{**_VALID, "notion_api_token": "secret_abc123"})
    assert s.notion_api_token == "secret_abc123"
