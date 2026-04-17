"""Deterministic XHTML → Notion block converter.

Applies FinalRuleset rules to Confluence XHTML, producing Notion API block dicts.
No LLM calls — pure Python transformation logic.
"""

from __future__ import annotations

import copy
import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any

from confluence_to_notion.agents.schemas import FinalRuleset
from confluence_to_notion.converter.resolution import ResolutionStore
from confluence_to_notion.converter.schemas import ConversionResult, UnresolvedItem
from confluence_to_notion.converter.table_rules import (
    TableRuleStore,
    extract_headers_from_xhtml,
)

logger = logging.getLogger(__name__)

LARGE_PAGE_BLOCK_THRESHOLD = 100  # blocks
LARGE_PAGE_SIZE_THRESHOLD = 102_400  # bytes (100 KB)

# Confluence XHTML namespace prefixes
_NS = {
    "ac": "http://www.atlassian.com/schema/confluence/4/ac/",
    "ri": "http://www.atlassian.com/schema/confluence/4/ri/",
}

_XHTML_WRAPPER = (
    '<root xmlns:ac="http://www.atlassian.com/schema/confluence/4/ac/"'
    ' xmlns:ri="http://www.atlassian.com/schema/confluence/4/ri/"'
    ">{}</root>"
)

# Panel macro → (emoji, color)
_PANEL_STYLES: dict[str, tuple[str, str]] = {
    "info": ("\u2139\ufe0f", "blue_background"),
    "note": ("\U0001f4dd", "gray_background"),
    "warning": ("\u26a0\ufe0f", "yellow_background"),
    "tip": ("\U0001f4a1", "green_background"),
}

_HEADING_MAP: dict[str, str] = {
    "h1": "heading_1",
    "h2": "heading_2",
    "h3": "heading_3",
    "h4": "heading_3",
    "h5": "heading_3",
    "h6": "heading_3",
}


@dataclass
class _ConversionContext:
    """Internal state threaded through all conversion functions."""

    enabled_ids: set[str]
    page_id: str
    store: ResolutionStore | None = None
    table_rules: TableRuleStore | None = None
    unresolved: list[UnresolvedItem] = field(default_factory=list)
    table_index: int = 0


def convert_page(
    xhtml: str,
    ruleset: FinalRuleset,
    *,
    page_id: str = "",
    store: ResolutionStore | None = None,
    table_rules: TableRuleStore | None = None,
) -> ConversionResult:
    """Convert a Confluence XHTML page to a list of Notion blocks.

    Args:
        xhtml: Confluence XHTML storage body.
        ruleset: Rules controlling which macros/elements to convert.
        page_id: Confluence page ID (used to tag unresolved items).
        store: Resolution store — if provided, resolved entries are used
            instead of placeholders for unknown macros and page links.
        table_rules: Table rule store — if provided, layout-confirmed tables
            (is_database=False) are converted without an UnresolvedItem so
            the resolver/Pass 1.5 doesn't re-prompt on them.

    Returns:
        ConversionResult with blocks and any unresolved items.
    """
    xhtml = xhtml.strip()
    if not xhtml:
        return ConversionResult()

    ctx = _ConversionContext(
        enabled_ids={r.rule_id for r in ruleset.enabled_rules},
        page_id=page_id,
        store=store,
        table_rules=table_rules,
    )
    xml_str = _XHTML_WRAPPER.format(xhtml)
    root = ET.fromstring(xml_str)

    blocks = _convert_children(root, ctx, block_type=None)

    input_size = len(xhtml.encode())
    if len(blocks) > LARGE_PAGE_BLOCK_THRESHOLD or input_size > LARGE_PAGE_SIZE_THRESHOLD:
        logger.warning(
            "Large page: %d blocks from %.1f KB input — Notion API will require chunked upload",
            len(blocks),
            input_size / 1024,
        )

    return ConversionResult(blocks=blocks, unresolved=ctx.unresolved)


def _convert_children(
    parent: ET.Element,
    ctx: _ConversionContext,
    block_type: str | None,
) -> list[dict[str, Any]]:
    """Convert child elements of a parent node to Notion blocks."""
    blocks: list[dict[str, Any]] = []

    # Handle bare text before first child
    if parent.text and parent.text.strip():
        blocks.append(_paragraph([_text_seg(parent.text.strip())]))

    for child in parent:
        child_blocks = _convert_element(child, ctx)
        blocks.extend(child_blocks)

        # Handle tail text after elements
        if child.tail and child.tail.strip():
            blocks.append(_paragraph([_text_seg(child.tail.strip())]))

    return blocks


def _convert_element(
    elem: ET.Element,
    ctx: _ConversionContext,
) -> list[dict[str, Any]]:
    """Convert a single element to Notion block(s)."""
    tag = _local_tag(elem)

    # --- Headings ---
    if tag in _HEADING_MAP:
        rt = _extract_rich_text(elem, ctx)
        if not rt:
            return []
        heading_type = _HEADING_MAP[tag]
        return [{heading_type: {"rich_text": rt}, "type": heading_type}]

    # --- Paragraphs ---
    if tag == "p":
        # Promote block-level macros wrapped in <p> (common in Confluence XHTML)
        promoted = _try_promote_block_macro(elem, ctx)
        if promoted is not None:
            return promoted
        rt = _extract_rich_text(elem, ctx)
        if not rt:
            return []
        return [_paragraph(rt)]

    # --- Lists ---
    if tag in ("ul", "ol"):
        return _convert_list(elem, tag, ctx)

    # --- Preformatted ---
    if tag == "pre":
        return _convert_pre(elem)

    # --- Confluence structured macro ---
    if tag == "structured-macro":
        return _convert_macro(elem, ctx)

    # --- Confluence image ---
    if tag == "image":
        return _convert_ac_image(elem, ctx)

    # --- Styled span (heading substitute) ---
    if tag == "span":
        return _convert_span(elem)

    # --- HTML table (layout table → Notion table block; databases come later) ---
    if tag == "table":
        return _convert_table(elem, ctx)

    # --- Fallback: recurse into children ---
    return _convert_children(elem, ctx, block_type=None)


# --- Rich text extraction ---


def _extract_rich_text(
    elem: ET.Element,
    ctx: _ConversionContext,
) -> list[dict[str, Any]]:
    """Extract Notion rich_text segments from an inline element."""
    segments: list[dict[str, Any]] = []

    if elem.text:
        segments.append(_text_seg(elem.text))

    for child in elem:
        tag = _local_tag(child)

        if tag == "code":
            text = _get_all_text(child)
            if text:
                segments.append(_text_seg(text, code=True))

        elif tag in ("strong", "b"):
            text = _get_all_text(child)
            if text:
                segments.append(_text_seg(text, bold=True))

        elif tag in ("em", "i"):
            text = _get_all_text(child)
            if text:
                segments.append(_text_seg(text, italic=True))

        elif tag == "a":
            text = _get_all_text(child) or child.get("href", "")
            href = child.get("href", "")
            segments.append(_text_seg(text, link=href))

        elif tag == "link":
            # ac:link — Confluence internal page link
            segments.extend(_extract_ac_link_rich_text(child, ctx))

        elif tag == "br":
            pass  # skip line breaks in inline context

        elif tag == "span":
            # Plain span: just extract text
            text = _get_all_text(child)
            if text:
                segments.append(_text_seg(text))

        elif tag == "structured-macro":
            # Inline macro (e.g., JIRA reference within a paragraph)
            inline_segs = _extract_inline_macro(child, ctx)
            segments.extend(inline_segs)

        elif tag == "image":
            pass  # Images handled at block level

        else:
            # Unknown inline element: extract text
            text = _get_all_text(child)
            if text:
                segments.append(_text_seg(text))

        if child.tail:
            segments.append(_text_seg(child.tail))

    return segments


def _extract_ac_link_rich_text(
    elem: ET.Element,
    ctx: _ConversionContext,
) -> list[dict[str, Any]]:
    """Extract rich_text from an ac:link element."""
    page_title = ""
    display_text = ""

    for child in elem:
        child_tag = _local_tag(child)
        if child_tag == "page":
            page_title = child.get(f"{{{_NS['ri']}}}content-title", "") or child.get(
                "ri:content-title", ""
            )
        elif child_tag == "plain-text-link-body":
            display_text = _get_all_text(child)

    text = display_text or page_title or "link"

    if page_title and ctx.store:
        entry = ctx.store.lookup(f"page_link:{page_title}")
        if entry and "notion_page_id" in entry.value:
            return [_page_mention_seg(text, page_id=entry.value["notion_page_id"])]

    url = f"https://notion.so/placeholder/{page_title}" if page_title else "#"
    if page_title:
        ctx.unresolved.append(
            UnresolvedItem(
                kind="page_link",
                identifier=page_title,
                source_page_id=ctx.page_id,
            )
        )

    return [_text_seg(text, link=url)]


def _extract_inline_macro(
    elem: ET.Element,
    ctx: _ConversionContext,
) -> list[dict[str, Any]]:
    """Extract rich_text segments from an inline macro (e.g., JIRA)."""
    macro_name = _get_macro_name(elem)

    if macro_name == "jira" and "rule:macro:jira" in ctx.enabled_ids:
        return _jira_rich_text(elem)

    # Unknown inline macro: extract any text
    text = _get_all_text(elem)
    return [_text_seg(text)] if text else []


# --- Block converters ---


_BLOCK_MACROS = {"toc", "info", "note", "warning", "tip", "code", "noformat", "expand"}


def _try_promote_block_macro(
    p_elem: ET.Element,
    ctx: _ConversionContext,
) -> list[dict[str, Any]] | None:
    """If a <p> contains only a single block-level macro, promote it."""
    has_text = bool(p_elem.text and p_elem.text.strip())
    children = list(p_elem)

    if has_text or len(children) != 1:
        return None

    child = children[0]
    if _local_tag(child) != "structured-macro":
        return None

    has_tail = bool(child.tail and child.tail.strip())
    if has_tail:
        return None

    macro_name = _get_macro_name(child)
    if macro_name in _BLOCK_MACROS:
        return _convert_macro(child, ctx)

    return None


def _convert_macro(
    elem: ET.Element,
    ctx: _ConversionContext,
) -> list[dict[str, Any]]:
    """Convert an ac:structured-macro to Notion block(s)."""
    macro_name = _get_macro_name(elem)

    # TOC
    if macro_name == "toc" and "rule:macro:toc" in ctx.enabled_ids:
        return [{"type": "table_of_contents", "table_of_contents": {"color": "default"}}]

    # JIRA
    if macro_name == "jira" and "rule:macro:jira" in ctx.enabled_ids:
        return [_paragraph(_jira_rich_text(elem))]

    # Code / noformat
    if macro_name in ("code", "noformat") and "rule:macro:code" in ctx.enabled_ids:
        return _convert_code_macro(elem)

    # Expand (toggle)
    if macro_name == "expand" and "rule:macro:expand" in ctx.enabled_ids:
        return _convert_expand_macro(elem, ctx)

    # Info/Note/Warning/Tip panels
    if macro_name in _PANEL_STYLES and f"rule:macro:{macro_name}" in ctx.enabled_ids:
        return _convert_panel_macro(elem, macro_name, ctx)
    # Also handle panels without explicit rules (built-in behavior for info-family macros)
    if macro_name in _PANEL_STYLES:
        return _convert_panel_macro(elem, macro_name, ctx)

    # Include / excerpt-include → Notion synced block
    if macro_name in ("include", "excerpt-include"):
        page_title = _extract_include_page_title(elem)
        if page_title:
            return _convert_include_macro(elem, macro_name, page_title, ctx)

    # Check resolution store for pre-resolved blocks
    if ctx.store:
        entry = ctx.store.lookup(f"macro:{macro_name}")
        if entry and "notion_blocks" in entry.value:
            blocks: list[dict[str, Any]] = copy.deepcopy(entry.value["notion_blocks"])
            return blocks

    # Fallback: render as paragraph with the macro's text content
    ctx.unresolved.append(
        UnresolvedItem(
            kind="macro",
            identifier=macro_name,
            source_page_id=ctx.page_id,
            context_xhtml=ET.tostring(elem, encoding="unicode"),
        )
    )
    text = _get_all_text(elem).strip()
    if text:
        return [_paragraph([_text_seg(f"[{macro_name}] {text}")])]
    return [_paragraph([_text_seg(f"[{macro_name}]")])]


def _extract_include_page_title(elem: ET.Element) -> str:
    """Extract the referenced page title from an include/excerpt-include macro."""
    for child in elem:
        if _local_tag(child) != "parameter":
            continue
        for link in child:
            if _local_tag(link) != "link":
                continue
            for page in link:
                if _local_tag(page) == "page":
                    title = page.get(
                        f"{{{_NS['ri']}}}content-title", ""
                    ) or page.get("ri:content-title", "")
                    if title:
                        return title
    return ""


def _convert_include_macro(
    elem: ET.Element,
    macro_name: str,
    page_title: str,
    ctx: _ConversionContext,
) -> list[dict[str, Any]]:
    """Convert include/excerpt-include to a synced_block reference or placeholder."""
    if ctx.store:
        entry = ctx.store.lookup(f"synced_block:{page_title}")
        if entry and "original_block_id" in entry.value:
            return [
                {
                    "type": "synced_block",
                    "synced_block": {
                        "synced_from": {
                            "type": "block_id",
                            "block_id": entry.value["original_block_id"],
                        },
                    },
                }
            ]

    ctx.unresolved.append(
        UnresolvedItem(
            kind="synced_block",
            identifier=page_title,
            source_page_id=ctx.page_id,
            context_xhtml=ET.tostring(elem, encoding="unicode"),
        )
    )
    return [_paragraph([_text_seg(f"[{macro_name}: {page_title}]")])]


def _convert_panel_macro(
    elem: ET.Element,
    macro_name: str,
    ctx: _ConversionContext,
) -> list[dict[str, Any]]:
    """Convert info/note/warning/tip macro to a Notion callout block."""
    emoji, color = _PANEL_STYLES[macro_name]
    rich_text: list[dict[str, Any]] = []
    children: list[dict[str, Any]] = []
    first_p_done = False

    for child in elem:
        if _local_tag(child) == "rich-text-body":
            for inner in child:
                inner_tag = _local_tag(inner)
                if inner_tag == "p" and not first_p_done:
                    # First <p> becomes the callout's rich_text
                    rt = _extract_rich_text(inner, ctx)
                    rich_text.extend(rt)
                    first_p_done = True
                else:
                    # Subsequent elements become nested children
                    child_blocks = _convert_element(inner, ctx)
                    children.extend(child_blocks)

    callout: dict[str, Any] = {
        "icon": {"type": "emoji", "emoji": emoji},
        "color": color,
        "rich_text": rich_text,
    }
    if children:
        callout["children"] = children

    return [{"type": "callout", "callout": callout}]


def _convert_code_macro(elem: ET.Element) -> list[dict[str, Any]]:
    """Convert code/noformat macro to a Notion code block."""
    params = _get_macro_params(elem)
    language = params.get("language", "plain text")

    content = ""
    for child in elem:
        if _local_tag(child) == "plain-text-body":
            content = _get_all_text(child).strip()

    return [
        {
            "type": "code",
            "code": {
                "language": language,
                "rich_text": [_text_seg(content)],
            },
        }
    ]


def _convert_expand_macro(
    elem: ET.Element,
    ctx: _ConversionContext,
) -> list[dict[str, Any]]:
    """Convert expand macro to a Notion toggle block."""
    params = _get_macro_params(elem)
    title = params.get("title", "Details")

    children: list[dict[str, Any]] = []
    for child in elem:
        if _local_tag(child) == "rich-text-body":
            for inner in child:
                child_blocks = _convert_element(inner, ctx)
                children.extend(child_blocks)

    toggle: dict[str, Any] = {
        "rich_text": [_text_seg(title)],
    }
    if children:
        toggle["children"] = children

    return [{"type": "toggle", "toggle": toggle}]


def _jira_rich_text(elem: ET.Element) -> list[dict[str, Any]]:
    """Extract JIRA issue key and URL as rich_text segments."""
    params = _get_macro_params(elem)
    key = params.get("key", "UNKNOWN")
    url = f"https://issues.apache.org/jira/browse/{key}"
    return [_text_seg(key, link=url)]


def _convert_ac_image(
    elem: ET.Element,
    ctx: _ConversionContext,
) -> list[dict[str, Any]]:
    """Convert an ac:image element to a Notion image block."""
    if "rule:element:ac-image" not in ctx.enabled_ids:
        return [_paragraph([_text_seg("[image]")])]

    filename = ""
    for child in elem:
        if _local_tag(child) == "attachment":
            filename = child.get(f"{{{_NS['ri']}}}filename", "") or child.get(
                "ri:filename", ""
            )

    url = f"https://placeholder.confluence/attachments/{filename}" if filename else "#"
    return [
        {
            "type": "image",
            "image": {
                "type": "external",
                "external": {"url": url},
            },
        }
    ]


def _convert_pre(elem: ET.Element) -> list[dict[str, Any]]:
    """Convert a <pre> element to a Notion code block."""
    parts: list[str] = []
    if elem.text:
        parts.append(elem.text)
    for child in elem:
        tag = _local_tag(child)
        if tag == "br":
            parts.append("\n")
        else:
            text = _get_all_text(child)
            if text:
                parts.append(text)
        if child.tail:
            parts.append(child.tail)

    content = "".join(parts).strip()
    return [
        {
            "type": "code",
            "code": {
                "language": "plain text",
                "rich_text": [_text_seg(content)],
            },
        }
    ]


_TABLE_CONTEXT_MAX_LEN = 1000


def _convert_table(
    elem: ET.Element,
    ctx: _ConversionContext,
) -> list[dict[str, Any]]:
    """Convert an HTML <table> to a Notion table block.

    Emits an UnresolvedItem(kind='table') alongside so a later AI resolver
    can re-emit the table as a Notion database if the rows look structured.
    """
    thead_rows: list[ET.Element] = []
    tbody_rows: list[ET.Element] = []
    for child in elem:
        tag = _local_tag(child)
        if tag == "thead":
            thead_rows.extend(tr for tr in child if _local_tag(tr) == "tr")
        elif tag == "tbody":
            tbody_rows.extend(tr for tr in child if _local_tag(tr) == "tr")
        elif tag == "tr":
            tbody_rows.append(child)

    all_rows = thead_rows + tbody_rows
    if not all_rows:
        return []

    identifier = f"table-{ctx.table_index:04d}"
    ctx.table_index += 1

    if ctx.store:
        entry = ctx.store.lookup(f"table:{identifier}")
        if entry and "notion_blocks" in entry.value:
            resolved: list[dict[str, Any]] = copy.deepcopy(entry.value["notion_blocks"])
            return resolved

    converted_rows: list[dict[str, Any]] = []
    max_width = 0
    for tr in all_rows:
        cells: list[list[dict[str, Any]]] = []
        for cell_elem in tr:
            if _local_tag(cell_elem) in ("th", "td"):
                cells.append(_extract_rich_text(cell_elem, ctx))
        if not cells:
            continue
        max_width = max(max_width, len(cells))
        converted_rows.append({"type": "table_row", "table_row": {"cells": cells}})

    if not converted_rows:
        return []

    # Notion requires every row to have the same cell count as table_width.
    for row in converted_rows:
        row_cells = row["table_row"]["cells"]
        while len(row_cells) < max_width:
            row_cells.append([])

    full_xhtml = ET.tostring(elem, encoding="unicode")
    context_xhtml = full_xhtml
    if len(context_xhtml) > _TABLE_CONTEXT_MAX_LEN:
        context_xhtml = context_xhtml[:_TABLE_CONTEXT_MAX_LEN]

    suppress_unresolved = False
    if ctx.table_rules is not None:
        headers = extract_headers_from_xhtml(full_xhtml)
        if headers:
            rule = ctx.table_rules.lookup(headers)
            if rule is not None and not rule.is_database:
                suppress_unresolved = True

    if not suppress_unresolved:
        ctx.unresolved.append(
            UnresolvedItem(
                kind="table",
                identifier=identifier,
                source_page_id=ctx.page_id,
                context_xhtml=context_xhtml,
            )
        )

    return [
        {
            "type": "table",
            "table": {
                "table_width": max_width,
                "has_column_header": bool(thead_rows),
                "has_row_header": False,
                "children": converted_rows,
            },
        }
    ]


def _convert_list(
    elem: ET.Element,
    list_tag: str,
    ctx: _ConversionContext,
) -> list[dict[str, Any]]:
    """Convert a <ul> or <ol> to Notion list items."""
    block_type = "bulleted_list_item" if list_tag == "ul" else "numbered_list_item"
    items: list[dict[str, Any]] = []

    for child in elem:
        if _local_tag(child) != "li":
            continue

        rt = _extract_rich_text_from_li(child, ctx)
        children = _extract_nested_list(child, ctx)

        block: dict[str, Any] = {
            "type": block_type,
            block_type: {"rich_text": rt},
        }
        if children:
            block[block_type]["children"] = children
        items.append(block)

    return items


def _extract_rich_text_from_li(
    li: ET.Element,
    ctx: _ConversionContext,
) -> list[dict[str, Any]]:
    """Extract rich_text from a <li>, ignoring nested lists."""
    segments: list[dict[str, Any]] = []

    if li.text:
        segments.append(_text_seg(li.text))

    for child in li:
        tag = _local_tag(child)
        if tag in ("ul", "ol"):
            continue  # nested list handled separately

        if tag == "p":
            rt = _extract_rich_text(child, ctx)
            segments.extend(rt)
        elif tag == "code":
            segments.append(_text_seg(_get_all_text(child), code=True))
        elif tag in ("strong", "b"):
            segments.append(_text_seg(_get_all_text(child), bold=True))
        elif tag in ("em", "i"):
            segments.append(_text_seg(_get_all_text(child), italic=True))
        elif tag == "a":
            text = _get_all_text(child) or child.get("href", "")
            segments.append(_text_seg(text, link=child.get("href", "")))
        elif tag == "link":
            segments.extend(_extract_ac_link_rich_text(child, ctx))
        elif tag == "structured-macro":
            segments.extend(_extract_inline_macro(child, ctx))
        else:
            text = _get_all_text(child)
            if text:
                segments.append(_text_seg(text))

        if child.tail:
            segments.append(_text_seg(child.tail))

    return segments


def _extract_nested_list(
    li: ET.Element,
    ctx: _ConversionContext,
) -> list[dict[str, Any]]:
    """Extract nested <ul>/<ol> from a <li> element."""
    children: list[dict[str, Any]] = []
    for child in li:
        tag = _local_tag(child)
        if tag in ("ul", "ol"):
            children.extend(_convert_list(child, tag, ctx))
    return children


def _convert_span(elem: ET.Element) -> list[dict[str, Any]]:
    """Convert a styled <span> to heading or paragraph."""
    style = elem.get("style", "")
    text = _get_all_text(elem).strip()
    if not text:
        return []

    is_bold = "font-weight: bold" in style or "font-weight:bold" in style
    font_size = _parse_font_size(style)

    if is_bold and font_size:
        if font_size >= 20:
            heading_type = "heading_1"
        elif font_size >= 14:
            heading_type = "heading_2"
        else:
            heading_type = "heading_3"
        return [{"type": heading_type, heading_type: {"rich_text": [_text_seg(text)]}}]

    return [_paragraph([_text_seg(text)])]


# --- Utility functions ---


def _local_tag(elem: ET.Element) -> str:
    """Strip namespace from element tag, returning the local name."""
    tag = elem.tag
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _get_all_text(elem: ET.Element) -> str:
    """Get all text content from an element and its descendants."""
    return "".join(elem.itertext())


def _get_macro_name(elem: ET.Element) -> str:
    """Get the macro name from an ac:structured-macro element."""
    return elem.get(f"{{{_NS['ac']}}}name", "") or elem.get("ac:name", "")


def _get_macro_params(elem: ET.Element) -> dict[str, str]:
    """Extract parameter name→value map from macro child elements."""
    params: dict[str, str] = {}
    for child in elem:
        if _local_tag(child) == "parameter":
            name = child.get(f"{{{_NS['ac']}}}name", "") or child.get("ac:name", "")
            value = _get_all_text(child).strip()
            if name:
                params[name] = value
    return params


def _parse_font_size(style: str) -> float | None:
    """Extract font-size in px from an inline style string."""
    match = re.search(r"font-size:\s*([\d.]+)px", style)
    return float(match.group(1)) if match else None


def _text_seg(
    content: str,
    *,
    bold: bool = False,
    italic: bool = False,
    code: bool = False,
    link: str = "",
) -> dict[str, Any]:
    """Build a Notion rich_text segment."""
    seg: dict[str, Any] = {
        "type": "text",
        "text": {"content": content},
    }
    if link:
        seg["text"]["link"] = {"url": link}

    annotations: dict[str, bool] = {}
    if bold:
        annotations["bold"] = True
    if italic:
        annotations["italic"] = True
    if code:
        annotations["code"] = True
    if annotations:
        seg["annotations"] = annotations

    return seg


def _page_mention_seg(plain_text: str, *, page_id: str) -> dict[str, Any]:
    """Build a Notion page-mention rich_text segment."""
    return {
        "type": "mention",
        "mention": {"type": "page", "page": {"id": page_id}},
        "plain_text": plain_text,
    }


def _paragraph(rich_text: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a Notion paragraph block."""
    return {
        "type": "paragraph",
        "paragraph": {"rich_text": rich_text},
    }
