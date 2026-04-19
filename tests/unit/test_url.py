"""Unit tests for ``parse_confluence_url()`` in ``confluence_to_notion.url``."""

import pytest

from confluence_to_notion.url import (
    ConfluenceUrlError,
    ConfluenceUrlInfo,
    parse_confluence_url,
)


@pytest.mark.parametrize(
    ("url", "source_type", "identifier"),
    [
        # (1) viewpage.action?pageId=<id> — id query wins.
        (
            "https://cwiki.apache.org/confluence/pages/viewpage.action?pageId=12345",
            "page",
            "12345",
        ),
        # (2) Legacy /display/<SPACE>/<Title> — identifier is the title segment,
        # URL-decoded with unquote_plus so `+` → space (matches Confluence's own
        # rendering of these links). Documenting the choice here.
        (
            "https://cwiki.apache.org/confluence/display/KAFKA/Some+Title",
            "page",
            "Some Title",
        ),
        # (3) New Cloud UI /wiki/spaces/<KEY>/pages/<id>/<slug>.
        (
            "https://example.atlassian.net/wiki/spaces/ENG/pages/12345/Some-Title",
            "page",
            "12345",
        ),
        # (4) Space root — no /pages/ segment.
        (
            "https://example.atlassian.net/wiki/spaces/ENG",
            "space",
            "ENG",
        ),
        # (4b) Space root with trailing slash.
        (
            "https://example.atlassian.net/wiki/spaces/ENG/",
            "space",
            "ENG",
        ),
    ],
)
def test_parse_confluence_url_happy_path(
    url: str, source_type: str, identifier: str
) -> None:
    result = parse_confluence_url(url)
    assert isinstance(result, ConfluenceUrlInfo)
    assert result.source_type == source_type
    assert result.identifier == identifier
    assert result.raw_url == url


def test_pageid_query_wins_over_spaces_path() -> None:
    """When both a ``pageId`` query and a /spaces/ path are present, the query wins."""
    result = parse_confluence_url(
        "https://example.atlassian.net/wiki/spaces/ENG/pages/viewpage.action?pageId=999"
    )
    assert result.source_type == "page"
    assert result.identifier == "999"


@pytest.mark.parametrize(
    "url",
    [
        "",
        "not-a-url",
        "ftp://example.com/foo",
        "https://example.atlassian.net/",
        "https://example.atlassian.net/wiki/",
        "https://example.atlassian.net/wiki/spaces/",
        "https://example.atlassian.net/some/unknown/path",
    ],
)
def test_parse_confluence_url_malformed_raises(url: str) -> None:
    with pytest.raises(ConfluenceUrlError):
        parse_confluence_url(url)


def test_confluence_url_error_is_value_error() -> None:
    """Callers should be able to catch the typed exception as a ``ValueError``."""
    assert issubclass(ConfluenceUrlError, ValueError)
