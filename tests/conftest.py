"""Shared test fixtures."""

import pytest

from confluence_to_notion.config import Settings


@pytest.fixture
def settings() -> Settings:
    """Create test settings with dummy values (authenticated Confluence)."""
    return Settings(
        confluence_base_url="https://test.atlassian.net/wiki",
        confluence_email="test@example.com",
        confluence_api_token="fake-confluence-token",
        notion_api_token="ntn_fake_token",
        notion_root_page_id="fake-notion-page-id",
        anthropic_api_key="sk-ant-fake-key",
    )


@pytest.fixture
def public_settings() -> Settings:
    """Create test settings for a public wiki (no Confluence auth)."""
    return Settings(
        confluence_base_url="https://cwiki.apache.org/confluence",
        notion_api_token="ntn_fake_token",
        notion_root_page_id="fake-notion-page-id",
        anthropic_api_key="sk-ant-fake-key",
    )
