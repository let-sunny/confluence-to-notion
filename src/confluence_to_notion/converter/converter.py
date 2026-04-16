"""Deterministic XHTML → Notion block converter.

Applies FinalRuleset rules to Confluence XHTML, producing Notion API block dicts.
No LLM calls — pure Python transformation logic.
"""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from typing import Any

from confluence_to_notion.agents.schemas import FinalRuleset

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


def convert_page(xhtml: str, ruleset: FinalRuleset) -> list[dict[str, Any]]:
    """Convert a Confluence XHTML page to a list of Notion blocks."""
    xhtml = xhtml.strip()
    if not xhtml:
        return []

    enabled_ids = {r.rule_id for r in ruleset.enabled_rules}
    xml_str = _XHTML_WRAPPER.format(xhtml)
    root = ET.fromstring(xml_str)

    blocks = _convert_children(root, enabled_ids, block_type=None)

    input_size = len(xhtml.encode())
    if len(blocks) > LARGE_PAGE_BLOCK_THRESHOLD or input_size > LARGE_PAGE_SIZE_THRESHOLD:
        logger.warning(
            "Large page: %d blocks from %.1f KB input — Notion API will require chunked upload",
            len(blocks),
            input_size / 1024,
        )

    return blocks


def _convert_children(
    parent: ET.Element,
    enabled_ids: set[str],
    block_type: str | None,
) -> list[dict[str, Any]]:
    """Convert child elements of a parent node to Notion blocks."""
    blocks: list[dict[str, Any]] = []

    # Handle bare text before first child
    if parent.text and parent.text.strip():
        blocks.append(_paragraph([_text_seg(parent.text.strip())]))

    for child in parent:
        child_blocks = _convert_element(child, enabled_ids)
        blocks.extend(child_blocks)

        # Handle tail text after elements
        if child.tail and child.tail.strip():
            blocks.append(_paragraph([_text_seg(child.tail.strip())]))

    return blocks


def _convert_element(
    elem: ET.Element,
    enabled_ids: set[str],
) -> list[dict[str, Any]]:
    """Convert a single element to Notion block(s)."""
    tag = _local_tag(elem)

    # --- Headings ---
    if tag in _HEADING_MAP:
        rt = _extract_rich_text(elem, enabled_ids)
        if not rt:
            return []
        heading_type = _HEADING_MAP[tag]
        return [{heading_type: {"rich_text": rt}, "type": heading_type}]

    # --- Paragraphs ---
    if tag == "p":
        # Promote block-level macros wrapped in <p> (common in Confluence XHTML)
        promoted = _try_promote_block_macro(elem, enabled_ids)
        if promoted is not None:
            return promoted
        rt = _extract_rich_text(elem, enabled_ids)
        if not rt:
            return []
        return [_paragraph(rt)]

    # --- Lists ---
    if tag in ("ul", "ol"):
        return _convert_list(elem, tag, enabled_ids)

    # --- Preformatted ---
    if tag == "pre":
        return _convert_pre(elem)

    # --- Confluence structured macro ---
    if tag == "structured-macro":
        return _convert_macro(elem, enabled_ids)

    # --- Confluence image ---
    if tag == "image":
        return _convert_ac_image(elem, enabled_ids)

    # --- Styled span (heading substitute) ---
    if tag == "span":
        return _convert_span(elem)

    # --- Fallback: recurse into children ---
    return _convert_children(elem, enabled_ids, block_type=None)


# --- Rich text extraction ---


def _extract_rich_text(
    elem: ET.Element,
    enabled_ids: set[str],
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
            segments.extend(_extract_ac_link_rich_text(child))

        elif tag == "br":
            pass  # skip line breaks in inline context

        elif tag == "span":
            # Plain span: just extract text
            text = _get_all_text(child)
            if text:
                segments.append(_text_seg(text))

        elif tag == "structured-macro":
            # Inline macro (e.g., JIRA reference within a paragraph)
            inline_segs = _extract_inline_macro(child, enabled_ids)
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


def _extract_ac_link_rich_text(elem: ET.Element) -> list[dict[str, Any]]:
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
    url = f"https://notion.so/placeholder/{page_title}" if page_title else "#"
    return [_text_seg(text, link=url)]


def _extract_inline_macro(
    elem: ET.Element,
    enabled_ids: set[str],
) -> list[dict[str, Any]]:
    """Extract rich_text segments from an inline macro (e.g., JIRA)."""
    macro_name = _get_macro_name(elem)

    if macro_name == "jira" and "rule:macro:jira" in enabled_ids:
        return _jira_rich_text(elem)

    # Unknown inline macro: extract any text
    text = _get_all_text(elem)
    return [_text_seg(text)] if text else []


# --- Block converters ---


_BLOCK_MACROS = {"toc", "info", "note", "warning", "tip", "code", "noformat", "expand"}


def _try_promote_block_macro(
    p_elem: ET.Element,
    enabled_ids: set[str],
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
        return _convert_macro(child, enabled_ids)

    return None


def _convert_macro(
    elem: ET.Element,
    enabled_ids: set[str],
) -> list[dict[str, Any]]:
    """Convert an ac:structured-macro to Notion block(s)."""
    macro_name = _get_macro_name(elem)

    # TOC
    if macro_name == "toc" and "rule:macro:toc" in enabled_ids:
        return [{"type": "table_of_contents", "table_of_contents": {"color": "default"}}]

    # JIRA
    if macro_name == "jira" and "rule:macro:jira" in enabled_ids:
        return [_paragraph(_jira_rich_text(elem))]

    # Code / noformat
    if macro_name in ("code", "noformat") and "rule:macro:code" in enabled_ids:
        return _convert_code_macro(elem)

    # Expand (toggle)
    if macro_name == "expand" and "rule:macro:expand" in enabled_ids:
        return _convert_expand_macro(elem, enabled_ids)

    # Info/Note/Warning/Tip panels
    if macro_name in _PANEL_STYLES and f"rule:macro:{macro_name}" in enabled_ids:
        return _convert_panel_macro(elem, macro_name, enabled_ids)
    # Also handle panels without explicit rules (built-in behavior for info-family macros)
    if macro_name in _PANEL_STYLES:
        return _convert_panel_macro(elem, macro_name, enabled_ids)

    # Fallback: render as paragraph with the macro's text content
    text = _get_all_text(elem).strip()
    if text:
        return [_paragraph([_text_seg(f"[{macro_name}] {text}")])]
    return [_paragraph([_text_seg(f"[{macro_name}]")])]


def _convert_panel_macro(
    elem: ET.Element,
    macro_name: str,
    enabled_ids: set[str],
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
                    rt = _extract_rich_text(inner, enabled_ids)
                    rich_text.extend(rt)
                    first_p_done = True
                else:
                    # Subsequent elements become nested children
                    child_blocks = _convert_element(inner, enabled_ids)
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
    enabled_ids: set[str],
) -> list[dict[str, Any]]:
    """Convert expand macro to a Notion toggle block."""
    params = _get_macro_params(elem)
    title = params.get("title", "Details")

    children: list[dict[str, Any]] = []
    for child in elem:
        if _local_tag(child) == "rich-text-body":
            for inner in child:
                child_blocks = _convert_element(inner, enabled_ids)
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
    enabled_ids: set[str],
) -> list[dict[str, Any]]:
    """Convert an ac:image element to a Notion image block."""
    if "rule:element:ac-image" not in enabled_ids:
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


def _convert_list(
    elem: ET.Element,
    list_tag: str,
    enabled_ids: set[str],
) -> list[dict[str, Any]]:
    """Convert a <ul> or <ol> to Notion list items."""
    block_type = "bulleted_list_item" if list_tag == "ul" else "numbered_list_item"
    items: list[dict[str, Any]] = []

    for child in elem:
        if _local_tag(child) != "li":
            continue

        rt = _extract_rich_text_from_li(child, enabled_ids)
        children = _extract_nested_list(child, enabled_ids)

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
    enabled_ids: set[str],
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
            rt = _extract_rich_text(child, enabled_ids)
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
            segments.extend(_extract_ac_link_rich_text(child))
        elif tag == "structured-macro":
            segments.extend(_extract_inline_macro(child, enabled_ids))
        else:
            text = _get_all_text(child)
            if text:
                segments.append(_text_seg(text))

        if child.tail:
            segments.append(_text_seg(child.tail))

    return segments


def _extract_nested_list(
    li: ET.Element,
    enabled_ids: set[str],
) -> list[dict[str, Any]]:
    """Extract nested <ul>/<ol> from a <li> element."""
    children: list[dict[str, Any]] = []
    for child in li:
        tag = _local_tag(child)
        if tag in ("ul", "ol"):
            children.extend(_convert_list(child, tag, enabled_ids))
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


def _paragraph(rich_text: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a Notion paragraph block."""
    return {
        "type": "paragraph",
        "paragraph": {"rich_text": rich_text},
    }
