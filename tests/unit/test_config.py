"""Unit tests for configuration loading."""

import pytest
from pydantic import ValidationError

from confluence_to_notion.config import Settings

# All fields provided (authenticated Confluence + Notion)
_FULL = dict(
    confluence_base_url="https://test.atlassian.net/wiki",
    confluence_email="user@example.com",
    confluence_api_token="token123",
    notion_api_token="ntn_xxx",
    notion_root_page_id="page-id",
)


def test_settings_with_all_fields() -> None:
    s = Settings(**_FULL)
    assert s.confluence_base_url == "https://test.atlassian.net/wiki"
    assert s.notion_api_token == "ntn_xxx"


def test_settings_minimal_defaults() -> None:
    """Settings loads with zero args — uses defaults for everything.

    Passes `_env_file=None` to disable .env loading so this regression test
    verifies class defaults regardless of any local .env on the dev machine.
    """
    s = Settings(_env_file=None)
    assert s.confluence_base_url == "https://cwiki.apache.org/confluence"
    assert s.confluence_email is None
    assert s.notion_api_token is None
    assert s.notion_api_token is None


def test_settings_public_wiki_no_auth() -> None:
    s = Settings(confluence_base_url="https://cwiki.apache.org/confluence")
    assert s.confluence_auth_available is False


def test_settings_auth_available_when_credentials_set() -> None:
    s = Settings(**_FULL)
    assert s.confluence_auth_available is True


def test_settings_default_api_path() -> None:
    s = Settings(**_FULL)
    assert s.confluence_api_path == "/rest/api"


def test_settings_rest_url_property() -> None:
    s = Settings(**_FULL, confluence_api_path="/rest/api/v2")
    assert s.confluence_rest_url == "https://test.atlassian.net/wiki/rest/api/v2"


def test_settings_rest_url_strips_trailing_slash() -> None:
    s = Settings(**{**_FULL, "confluence_base_url": "https://test.atlassian.net/wiki/"})
    assert s.confluence_rest_url == "https://test.atlassian.net/wiki/rest/api"


def test_settings_invalid_confluence_url() -> None:
    with pytest.raises(ValidationError, match="must start with http"):
        Settings(confluence_base_url="not-a-url")


def test_settings_invalid_api_path() -> None:
    with pytest.raises(ValidationError, match="must start with /"):
        Settings(confluence_api_path="rest/api")


def test_settings_invalid_notion_token() -> None:
    with pytest.raises(ValidationError, match="must start with"):
        Settings(notion_api_token="bad-token")


def test_settings_notion_secret_prefix_accepted() -> None:
    s = Settings(notion_api_token="secret_abc123")
    assert s.notion_api_token == "secret_abc123"


def test_require_notion_raises_when_missing() -> None:
    """Settings.require_notion raises when token is unset.

    Passes `_env_file=None` to disable .env loading so this regression test
    verifies default (unset) token behavior regardless of any local .env on the
    dev machine.
    """
    s = Settings(_env_file=None)
    with pytest.raises(ValueError, match="NOTION_API_TOKEN"):
        s.require_notion()


def test_require_notion_raises_when_no_page_id() -> None:
    """Settings.require_notion raises when page-id is unset.

    Passes `_env_file=None` to disable .env loading so this regression test
    verifies default (unset) page-id behavior regardless of any local .env on
    the dev machine.
    """
    s = Settings(_env_file=None, notion_api_token="ntn_xxx")
    with pytest.raises(ValueError, match="NOTION_ROOT_PAGE_ID"):
        s.require_notion()


def test_require_notion_passes_when_complete() -> None:
    s = Settings(notion_api_token="ntn_xxx", notion_root_page_id="page-id")
    s.require_notion()  # should not raise
