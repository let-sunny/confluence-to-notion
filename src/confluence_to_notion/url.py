"""Confluence URL parsing — classify a URL into (source_type, identifier).

Downstream migrate code dispatches on :class:`ConfluenceUrlInfo.source_type` without
re-parsing. This module is intentionally side-effect free (no network, no filesystem)
so callers such as :mod:`confluence_to_notion.runs` can import it without cycles.
"""

from typing import Literal
from urllib.parse import parse_qs, unquote_plus, urlparse

from pydantic import BaseModel, ConfigDict

SourceType = Literal["page", "space"]


class ConfluenceUrlError(ValueError):
    """Raised when a URL does not match any recognized Confluence URL shape."""


class ConfluenceUrlInfo(BaseModel):
    """Classification result for a Confluence URL."""

    model_config = ConfigDict(frozen=True)

    source_type: SourceType
    identifier: str
    raw_url: str


def parse_confluence_url(url: str) -> ConfluenceUrlInfo:
    """Classify ``url`` as a Confluence page or space reference.

    Dispatch order (URL shape only — no network):
    1. ``?pageId=<id>`` query parameter → ``page`` with ``identifier=<id>``.
    2. Legacy ``/display/<SPACE>/<Title>`` → ``page``; identifier is
       ``unquote_plus(<Title>)`` so ``Some+Title`` becomes ``Some Title``.
    3. New Cloud UI ``/spaces/<KEY>/pages/<id>/...`` → ``page`` with ``identifier=<id>``.
    4. Space root ``/spaces/<KEY>`` (no ``/pages/`` segment) → ``space`` with ``identifier=<KEY>``.

    Raises :class:`ConfluenceUrlError` for URLs that don't match any known shape.
    """
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ConfluenceUrlError(f"Not a http(s) URL: {url!r}")

    page_id = parse_qs(parsed.query).get("pageId")
    if page_id and page_id[0]:
        return ConfluenceUrlInfo(source_type="page", identifier=page_id[0], raw_url=url)

    segments = [s for s in parsed.path.split("/") if s]

    for i, seg in enumerate(segments):
        if seg == "display" and i + 2 < len(segments):
            title = unquote_plus(segments[i + 2])
            return ConfluenceUrlInfo(source_type="page", identifier=title, raw_url=url)

    for i, seg in enumerate(segments):
        if seg == "spaces" and i + 1 < len(segments):
            space_key = segments[i + 1]
            for j in range(i + 2, len(segments) - 1):
                if segments[j] == "pages":
                    return ConfluenceUrlInfo(
                        source_type="page", identifier=segments[j + 1], raw_url=url
                    )
            return ConfluenceUrlInfo(source_type="space", identifier=space_key, raw_url=url)

    raise ConfluenceUrlError(f"Unrecognized Confluence URL shape: {url!r}")
