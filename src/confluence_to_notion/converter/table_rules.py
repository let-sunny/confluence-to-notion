"""Table rule store — header-signature keyed rules for table → Notion database mapping.

The store persists user decisions (and AI-drafted defaults) about whether a given
Confluence table should be migrated as a Notion database, which column becomes the
title, and what Notion property type each column maps to. Rules are keyed by a
normalized header signature so the same layout across many pages resolves once.
"""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from confluence_to_notion.converter.schemas import (
    NotionPropertyType,
    TableRule,
    TableRuleSet,
)

logger = logging.getLogger(__name__)

_DATE_RE = re.compile(
    r"^(?:\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|\d{1,2}[-/.]\d{1,2}[-/.]\d{4})$"
)
_SELECT_MAX_DISTINCT = 5
_SELECT_MIN_ROWS = 3


def normalize_header_signature(headers: list[str]) -> str:
    """Normalize a header list into a canonical signature string.

    Headers are lowercased, stripped, and joined with ``|`` preserving order.
    Raises ``ValueError`` if the list is empty.
    """
    if not headers:
        raise ValueError("normalize_header_signature requires at least one header")
    return "|".join(h.strip().lower() for h in headers)


def _local_tag(elem: ET.Element) -> str:
    tag = elem.tag
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _header_text(th: ET.Element) -> str:
    return " ".join("".join(th.itertext()).split()).strip()


def extract_headers_from_xhtml(context_xhtml: str) -> list[str]:
    """Extract the column headers from a ``<table>`` XHTML snippet.

    Prefers the first row inside ``<thead>``; falls back to the first ``<tr>`` in the
    table. Returns ``[]`` if the snippet can't be parsed or no ``<th>`` cells are found.
    Inline formatting tags inside ``<th>`` are stripped; colspan/rowspan are ignored
    (each ``<th>`` contributes one header).
    """
    try:
        root = ET.fromstring(context_xhtml)
    except ET.ParseError:
        logger.debug("extract_headers_from_xhtml: failed to parse snippet")
        return []

    thead = next((c for c in root.iter() if _local_tag(c) == "thead"), None)
    header_row: ET.Element | None = None
    if thead is not None:
        header_row = next((c for c in thead if _local_tag(c) == "tr"), None)
    if header_row is None:
        header_row = next((c for c in root.iter() if _local_tag(c) == "tr"), None)
    if header_row is None:
        return []

    headers: list[str] = []
    for cell in header_row:
        if _local_tag(cell) == "th":
            headers.append(_header_text(cell))
    return headers


def _looks_like_date(values: list[str]) -> bool:
    stripped = [v.strip() for v in values if v and v.strip()]
    if not stripped:
        return False
    return all(_DATE_RE.match(v) for v in stripped)


def _looks_like_select(values: list[str]) -> bool:
    non_empty = [v.strip() for v in values if v and v.strip()]
    if len(non_empty) < _SELECT_MIN_ROWS:
        return False
    distinct = set(non_empty)
    if len(distinct) > _SELECT_MAX_DISTINCT:
        return False
    # Require at least one repeat so free-form short strings don't look categorical.
    return len(distinct) < len(non_empty)


def infer_column_types(
    rows: list[list[str]],
    headers: list[str],
) -> dict[str, NotionPropertyType]:
    """Draft a property type for each header using simple content heuristics.

    Returns a mapping whose keys are the input header names (order matches ``headers``).
    ISO/common date columns → ``'date'``; low-cardinality string columns (≤5 distinct
    values, ≥3 rows, at least one repeat) → ``'select'``; everything else → ``'rich_text'``.
    The caller decides which column becomes the ``'title'``.
    """
    result: dict[str, NotionPropertyType] = {}
    for idx, header in enumerate(headers):
        column_values = [row[idx] if idx < len(row) else "" for row in rows]
        if _looks_like_date(column_values):
            result[header] = "date"
        elif _looks_like_select(column_values):
            result[header] = "select"
        else:
            result[header] = "rich_text"
    return result


class TableRuleStore:
    """Load, query, and persist table rules keyed by header signature.

    Mirrors the ``ResolutionStore`` pattern: ``pathlib.Path`` init, load-on-construct,
    explicit ``save()``. A missing file yields an empty store.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self.data = self._load()

    def _load(self) -> TableRuleSet:
        if not self._path.exists():
            return TableRuleSet()
        try:
            return TableRuleSet.model_validate_json(
                self._path.read_text(encoding="utf-8")
            )
        except (ValueError, OSError):
            logger.warning("Failed to load %s, starting fresh", self._path)
            return TableRuleSet()

    def lookup(self, headers: list[str]) -> TableRule | None:
        """Return the rule for the given headers, or ``None`` if absent."""
        try:
            key = normalize_header_signature(headers)
        except ValueError:
            return None
        return self.data.rules.get(key)

    def upsert(self, headers: list[str], rule: TableRule) -> None:
        """Insert or overwrite the rule for the given headers."""
        key = normalize_header_signature(headers)
        self.data.rules[key] = rule

    def save(self) -> None:
        """Persist the store to disk, creating parent directories as needed."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            self.data.model_dump_json(indent=2),
            encoding="utf-8",
        )
