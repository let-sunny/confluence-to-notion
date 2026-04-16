"""Unit tests for the deterministic XHTML → Notion block converter."""

from typing import Any

import pytest

from confluence_to_notion.agents.schemas import FinalRule, FinalRuleset, ProposedRule
from confluence_to_notion.converter.converter import convert_page

# --- Helpers ---


def _ruleset(rules: list[dict[str, Any]] | None = None) -> FinalRuleset:
    """Build a FinalRuleset from shorthand dicts, or return default test ruleset."""
    if rules is None:
        rules = []
    final_rules = [
        FinalRule.from_proposed(ProposedRule(**r))  # type: ignore[arg-type]
        for r in rules
    ]
    return FinalRuleset(source="test", rules=final_rules)


def _default_ruleset() -> FinalRuleset:
    """A ruleset containing all rules from the actual proposals.json."""
    return _ruleset(
        [
            {
                "rule_id": "rule:macro:toc",
                "source_pattern_id": "macro:toc",
                "source_description": "TOC",
                "notion_block_type": "table_of_contents",
                "mapping_description": "Map TOC",
                "example_input": "<x/>",
                "example_output": {"type": "table_of_contents"},
                "confidence": "high",
            },
            {
                "rule_id": "rule:macro:jira",
                "source_pattern_id": "macro:jira",
                "source_description": "JIRA ref",
                "notion_block_type": "paragraph",
                "mapping_description": "Map JIRA",
                "example_input": "<x/>",
                "example_output": {"type": "paragraph"},
                "confidence": "medium",
            },
            {
                "rule_id": "rule:macro:info",
                "source_pattern_id": "macro:info",
                "source_description": "Info panel",
                "notion_block_type": "callout",
                "mapping_description": "Map info",
                "example_input": "<x/>",
                "example_output": {"type": "callout"},
                "confidence": "high",
            },
            {
                "rule_id": "rule:element:ac-image",
                "source_pattern_id": "element:ac-image",
                "source_description": "Image",
                "notion_block_type": "image",
                "mapping_description": "Map image",
                "example_input": "<x/>",
                "example_output": {"type": "image"},
                "confidence": "medium",
            },
            {
                "rule_id": "rule:formatting:pre",
                "source_pattern_id": "formatting:pre",
                "source_description": "Preformatted",
                "notion_block_type": "code",
                "mapping_description": "Map pre",
                "example_input": "<x/>",
                "example_output": {"type": "code"},
                "confidence": "high",
            },
            {
                "rule_id": "rule:macro:code",
                "source_pattern_id": "macro:code",
                "source_description": "Code macro",
                "notion_block_type": "code",
                "mapping_description": "Map code macro to code block",
                "example_input": "<x/>",
                "example_output": {"type": "code"},
                "confidence": "high",
            },
            {
                "rule_id": "rule:macro:expand",
                "source_pattern_id": "macro:expand",
                "source_description": "Expand macro",
                "notion_block_type": "toggle",
                "mapping_description": "Map expand macro to toggle block",
                "example_input": "<x/>",
                "example_output": {"type": "toggle"},
                "confidence": "high",
            },
        ]
    )


# --- Standard HTML ---


class TestHeadings:
    def test_h1(self) -> None:
        blocks = convert_page("<h1>Title</h1>", _default_ruleset())
        assert blocks == [
            {
                "type": "heading_1",
                "heading_1": {
                    "rich_text": [{"type": "text", "text": {"content": "Title"}}],
                },
            }
        ]

    def test_h2(self) -> None:
        blocks = convert_page("<h2>Section</h2>", _default_ruleset())
        assert blocks[0]["type"] == "heading_2"

    def test_h3(self) -> None:
        blocks = convert_page("<h3>Subsection</h3>", _default_ruleset())
        assert blocks[0]["type"] == "heading_3"

    def test_h4_h5_h6_fallback_to_h3(self) -> None:
        """Notion only supports h1-h3; h4+ should map to h3."""
        blocks = convert_page("<h4>Deep heading</h4>", _default_ruleset())
        assert blocks[0]["type"] == "heading_3"


class TestParagraphs:
    def test_simple_paragraph(self) -> None:
        blocks = convert_page("<p>Hello world</p>", _default_ruleset())
        assert blocks == [
            {
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "text": {"content": "Hello world"}}],
                },
            }
        ]

    def test_empty_paragraph_skipped(self) -> None:
        blocks = convert_page("<p></p>", _default_ruleset())
        assert blocks == []

    def test_br_only_paragraph_skipped(self) -> None:
        blocks = convert_page("<p><br /></p>", _default_ruleset())
        assert blocks == []

    def test_paragraph_with_inline_code(self) -> None:
        blocks = convert_page("<p>Run <code>gradle</code> now</p>", _default_ruleset())
        rich_text = blocks[0]["paragraph"]["rich_text"]
        assert len(rich_text) == 3
        assert rich_text[0] == {"type": "text", "text": {"content": "Run "}}
        assert rich_text[1]["annotations"]["code"] is True
        assert rich_text[1]["text"]["content"] == "gradle"
        assert rich_text[2] == {"type": "text", "text": {"content": " now"}}

    def test_paragraph_with_bold(self) -> None:
        blocks = convert_page("<p>This is <strong>bold</strong> text</p>", _default_ruleset())
        rich_text = blocks[0]["paragraph"]["rich_text"]
        assert rich_text[1]["annotations"]["bold"] is True

    def test_paragraph_with_italic(self) -> None:
        blocks = convert_page("<p>This is <em>italic</em> text</p>", _default_ruleset())
        rich_text = blocks[0]["paragraph"]["rich_text"]
        assert rich_text[1]["annotations"]["italic"] is True

    def test_paragraph_with_link(self) -> None:
        blocks = convert_page(
            '<p>See <a href="https://example.com">here</a></p>',
            _default_ruleset(),
        )
        rich_text = blocks[0]["paragraph"]["rich_text"]
        assert rich_text[1]["text"]["link"] == {"url": "https://example.com"}


class TestLists:
    def test_unordered_list(self) -> None:
        blocks = convert_page("<ul><li>one</li><li>two</li></ul>", _default_ruleset())
        assert len(blocks) == 2
        assert blocks[0]["type"] == "bulleted_list_item"
        assert blocks[0]["bulleted_list_item"]["rich_text"][0]["text"]["content"] == "one"

    def test_ordered_list(self) -> None:
        blocks = convert_page("<ol><li>first</li><li>second</li></ol>", _default_ruleset())
        assert len(blocks) == 2
        assert blocks[0]["type"] == "numbered_list_item"

    def test_nested_list(self) -> None:
        xhtml = "<ul><li>parent<ul><li>child</li></ul></li></ul>"
        blocks = convert_page(xhtml, _default_ruleset())
        assert blocks[0]["type"] == "bulleted_list_item"
        children = blocks[0].get("bulleted_list_item", {}).get("children", [])
        assert len(children) == 1
        assert children[0]["type"] == "bulleted_list_item"


# --- Confluence Macros ---


class TestMacroToc:
    def test_toc_macro(self) -> None:
        xhtml = (
            '<ac:structured-macro ac:name="toc" ac:schema-version="1">'
            '<ac:parameter ac:name="maxLevel">3</ac:parameter>'
            "</ac:structured-macro>"
        )
        blocks = convert_page(xhtml, _default_ruleset())
        assert blocks == [
            {
                "type": "table_of_contents",
                "table_of_contents": {"color": "default"},
            }
        ]

    def test_toc_macro_wrapped_in_paragraph(self) -> None:
        """Confluence often wraps block macros in <p>; converter should promote them."""
        xhtml = (
            "<p>"
            '<ac:structured-macro ac:name="toc" ac:schema-version="1">'
            '<ac:parameter ac:name="maxLevel">3</ac:parameter>'
            "</ac:structured-macro>"
            "</p>"
        )
        blocks = convert_page(xhtml, _default_ruleset())
        assert len(blocks) == 1
        assert blocks[0]["type"] == "table_of_contents"


class TestMacroJira:
    def test_jira_macro(self) -> None:
        xhtml = (
            '<ac:structured-macro ac:name="jira" ac:schema-version="1">'
            '<ac:parameter ac:name="server">ASF JIRA</ac:parameter>'
            '<ac:parameter ac:name="key">KAFKA-4617</ac:parameter>'
            "</ac:structured-macro>"
        )
        blocks = convert_page(xhtml, _default_ruleset())
        rt = blocks[0]["paragraph"]["rich_text"]
        assert rt[0]["text"]["content"] == "KAFKA-4617"
        assert "jira/browse/KAFKA-4617" in rt[0]["text"]["link"]["url"]


class TestMacroInfo:
    def test_info_macro(self) -> None:
        xhtml = (
            '<ac:structured-macro ac:name="info">'
            "<ac:rich-text-body><p>Important note</p></ac:rich-text-body>"
            "</ac:structured-macro>"
        )
        blocks = convert_page(xhtml, _default_ruleset())
        assert blocks[0]["type"] == "callout"
        callout = blocks[0]["callout"]
        assert callout["icon"] == {"type": "emoji", "emoji": "\u2139\ufe0f"}
        assert callout["color"] == "blue_background"
        assert callout["rich_text"][0]["text"]["content"] == "Important note"

    @pytest.mark.parametrize(
        ("macro_name", "emoji", "color"),
        [
            ("note", "\U0001f4dd", "gray_background"),
            ("warning", "\u26a0\ufe0f", "yellow_background"),
            ("tip", "\U0001f4a1", "green_background"),
        ],
    )
    def test_panel_variants(self, macro_name: str, emoji: str, color: str) -> None:
        xhtml = (
            f'<ac:structured-macro ac:name="{macro_name}">'
            "<ac:rich-text-body><p>Text</p></ac:rich-text-body>"
            "</ac:structured-macro>"
        )
        blocks = convert_page(xhtml, _default_ruleset())
        assert blocks[0]["callout"]["icon"]["emoji"] == emoji
        assert blocks[0]["callout"]["color"] == color


class TestMacroCode:
    def test_code_macro_with_language(self) -> None:
        """Code macro with language param produces a Notion code block."""
        xhtml = (
            '<ac:structured-macro ac:name="code">'
            '<ac:parameter ac:name="language">python</ac:parameter>'
            "<ac:plain-text-body><![CDATA[print('hello')]]></ac:plain-text-body>"
            "</ac:structured-macro>"
        )
        blocks = convert_page(xhtml, _default_ruleset())
        assert len(blocks) == 1
        assert blocks[0]["type"] == "code"
        assert blocks[0]["code"]["language"] == "python"
        assert blocks[0]["code"]["rich_text"][0]["text"]["content"] == "print('hello')"

    def test_code_macro_no_language(self) -> None:
        """Code macro without language defaults to 'plain text'."""
        xhtml = (
            '<ac:structured-macro ac:name="code">'
            "<ac:plain-text-body><![CDATA[some code]]></ac:plain-text-body>"
            "</ac:structured-macro>"
        )
        blocks = convert_page(xhtml, _default_ruleset())
        assert blocks[0]["type"] == "code"
        assert blocks[0]["code"]["language"] == "plain text"

    def test_noformat_macro(self) -> None:
        """noformat macro produces a code block with 'plain text' language."""
        xhtml = (
            '<ac:structured-macro ac:name="noformat">'
            "<ac:plain-text-body><![CDATA[raw text]]></ac:plain-text-body>"
            "</ac:structured-macro>"
        )
        blocks = convert_page(xhtml, _default_ruleset())
        assert blocks[0]["type"] == "code"
        assert blocks[0]["code"]["language"] == "plain text"
        assert blocks[0]["code"]["rich_text"][0]["text"]["content"] == "raw text"


class TestNestedMacros:
    def test_info_with_nested_code(self) -> None:
        """Info panel containing a code macro → callout with code block child."""
        xhtml = (
            '<ac:structured-macro ac:name="info">'
            "<ac:rich-text-body>"
            "<p>Setup instructions:</p>"
            '<ac:structured-macro ac:name="code">'
            '<ac:parameter ac:name="language">bash</ac:parameter>'
            "<ac:plain-text-body><![CDATA[pip install pkg]]></ac:plain-text-body>"
            "</ac:structured-macro>"
            "</ac:rich-text-body>"
            "</ac:structured-macro>"
        )
        blocks = convert_page(xhtml, _default_ruleset())
        assert len(blocks) == 1
        assert blocks[0]["type"] == "callout"
        callout = blocks[0]["callout"]
        assert callout["rich_text"][0]["text"]["content"] == "Setup instructions:"
        assert "children" in callout
        children = callout["children"]
        assert len(children) == 1
        assert children[0]["type"] == "code"
        assert children[0]["code"]["language"] == "bash"
        assert children[0]["code"]["rich_text"][0]["text"]["content"] == "pip install pkg"

    def test_expand_basic(self) -> None:
        """Expand macro with <p> → toggle block with title from ac:parameter."""
        xhtml = (
            '<ac:structured-macro ac:name="expand">'
            '<ac:parameter ac:name="title">Click to expand</ac:parameter>'
            "<ac:rich-text-body>"
            "<p>Hidden content here</p>"
            "</ac:rich-text-body>"
            "</ac:structured-macro>"
        )
        blocks = convert_page(xhtml, _default_ruleset())
        assert len(blocks) == 1
        assert blocks[0]["type"] == "toggle"
        toggle = blocks[0]["toggle"]
        assert toggle["rich_text"][0]["text"]["content"] == "Click to expand"
        assert "children" in toggle
        children = toggle["children"]
        assert len(children) == 1
        assert children[0]["type"] == "paragraph"
        assert children[0]["paragraph"]["rich_text"][0]["text"]["content"] == "Hidden content here"

    def test_expand_with_nested_info(self) -> None:
        """Expand containing an info panel → toggle with callout child (2+ level nesting)."""
        xhtml = (
            '<ac:structured-macro ac:name="expand">'
            '<ac:parameter ac:name="title">Details</ac:parameter>'
            "<ac:rich-text-body>"
            '<ac:structured-macro ac:name="info">'
            "<ac:rich-text-body><p>Important note</p></ac:rich-text-body>"
            "</ac:structured-macro>"
            "</ac:rich-text-body>"
            "</ac:structured-macro>"
        )
        blocks = convert_page(xhtml, _default_ruleset())
        assert len(blocks) == 1
        assert blocks[0]["type"] == "toggle"
        toggle = blocks[0]["toggle"]
        assert toggle["rich_text"][0]["text"]["content"] == "Details"
        children = toggle["children"]
        assert len(children) == 1
        assert children[0]["type"] == "callout"
        assert children[0]["callout"]["rich_text"][0]["text"]["content"] == "Important note"

    def test_expand_with_nested_code(self) -> None:
        """Expand containing a code macro → toggle with code block child."""
        xhtml = (
            '<ac:structured-macro ac:name="expand">'
            '<ac:parameter ac:name="title">Show code</ac:parameter>'
            "<ac:rich-text-body>"
            '<ac:structured-macro ac:name="code">'
            '<ac:parameter ac:name="language">java</ac:parameter>'
            "<ac:plain-text-body><![CDATA[System.out.println();]]></ac:plain-text-body>"
            "</ac:structured-macro>"
            "</ac:rich-text-body>"
            "</ac:structured-macro>"
        )
        blocks = convert_page(xhtml, _default_ruleset())
        assert len(blocks) == 1
        assert blocks[0]["type"] == "toggle"
        toggle = blocks[0]["toggle"]
        assert toggle["rich_text"][0]["text"]["content"] == "Show code"
        children = toggle["children"]
        assert len(children) == 1
        assert children[0]["type"] == "code"
        assert children[0]["code"]["language"] == "java"
        assert children[0]["code"]["rich_text"][0]["text"]["content"] == "System.out.println();"

    def test_three_level_expand_info_code(self) -> None:
        """Expand > info > code → toggle > callout > code (3-level nesting)."""
        xhtml = (
            '<ac:structured-macro ac:name="expand">'
            '<ac:parameter ac:name="title">Setup</ac:parameter>'
            "<ac:rich-text-body>"
            '<ac:structured-macro ac:name="info">'
            "<ac:rich-text-body>"
            "<p>Install steps:</p>"
            '<ac:structured-macro ac:name="code">'
            '<ac:parameter ac:name="language">bash</ac:parameter>'
            "<ac:plain-text-body><![CDATA[npm install]]></ac:plain-text-body>"
            "</ac:structured-macro>"
            "</ac:rich-text-body>"
            "</ac:structured-macro>"
            "</ac:rich-text-body>"
            "</ac:structured-macro>"
        )
        blocks = convert_page(xhtml, _default_ruleset())
        assert len(blocks) == 1
        assert blocks[0]["type"] == "toggle"
        toggle_children = blocks[0]["toggle"]["children"]
        assert len(toggle_children) == 1
        assert toggle_children[0]["type"] == "callout"
        callout = toggle_children[0]["callout"]
        assert callout["rich_text"][0]["text"]["content"] == "Install steps:"
        assert "children" in callout
        callout_children = callout["children"]
        assert len(callout_children) == 1
        assert callout_children[0]["type"] == "code"
        assert callout_children[0]["code"]["language"] == "bash"
        assert callout_children[0]["code"]["rich_text"][0]["text"]["content"] == "npm install"

    def test_panel_with_nested_panel(self) -> None:
        """Warning panel containing info panel → callout with callout child."""
        xhtml = (
            '<ac:structured-macro ac:name="warning">'
            "<ac:rich-text-body>"
            "<p>Be careful:</p>"
            '<ac:structured-macro ac:name="info">'
            "<ac:rich-text-body><p>See docs for details</p></ac:rich-text-body>"
            "</ac:structured-macro>"
            "</ac:rich-text-body>"
            "</ac:structured-macro>"
        )
        blocks = convert_page(xhtml, _default_ruleset())
        assert len(blocks) == 1
        assert blocks[0]["type"] == "callout"
        outer = blocks[0]["callout"]
        assert outer["icon"]["emoji"] == "\u26a0\ufe0f"
        assert outer["color"] == "yellow_background"
        assert outer["rich_text"][0]["text"]["content"] == "Be careful:"
        assert "children" in outer
        children = outer["children"]
        assert len(children) == 1
        assert children[0]["type"] == "callout"
        inner = children[0]["callout"]
        assert inner["icon"]["emoji"] == "\u2139\ufe0f"
        assert inner["color"] == "blue_background"
        assert inner["rich_text"][0]["text"]["content"] == "See docs for details"


# --- Confluence Elements ---


class TestAcLink:
    def test_ac_link_in_paragraph(self) -> None:
        xhtml = (
            "<p>See "
            '<ac:link><ri:page ri:content-title="Setup Guide" /></ac:link>'
            " for details</p>"
        )
        blocks = convert_page(xhtml, _default_ruleset())
        rt = blocks[0]["paragraph"]["rich_text"]
        link_seg = next(s for s in rt if s["text"].get("link"))
        assert link_seg["text"]["content"] == "Setup Guide"

    def test_ac_link_with_custom_text(self) -> None:
        xhtml = (
            "<p>"
            "<ac:link><ri:page ri:content-title=\"Compression\" />"
            "<ac:plain-text-link-body><![CDATA[Kafka compression]]>"
            "</ac:plain-text-link-body></ac:link>"
            "</p>"
        )
        blocks = convert_page(xhtml, _default_ruleset())
        rt = blocks[0]["paragraph"]["rich_text"]
        link_seg = next(s for s in rt if s["text"].get("link"))
        assert link_seg["text"]["content"] == "Kafka compression"


class TestAcImage:
    def test_image(self) -> None:
        xhtml = '<ac:image ac:height="250"><ri:attachment ri:filename="pic.jpg" /></ac:image>'
        blocks = convert_page(xhtml, _default_ruleset())
        assert blocks[0]["type"] == "image"
        assert blocks[0]["image"]["type"] == "external"
        assert "pic.jpg" in blocks[0]["image"]["external"]["url"]


# --- Formatting ---


class TestPreformatted:
    def test_pre_block(self) -> None:
        xhtml = "<pre>line1<br />line2</pre>"
        blocks = convert_page(xhtml, _default_ruleset())
        assert blocks[0]["type"] == "code"
        content = blocks[0]["code"]["rich_text"][0]["text"]["content"]
        assert content == "line1\nline2"
        assert blocks[0]["code"]["language"] == "plain text"


class TestStyledSpan:
    def test_bold_large_span_as_heading(self) -> None:
        xhtml = '<span style="font-size: 16.0px;font-weight: bold;">Section Title</span>'
        blocks = convert_page(xhtml, _default_ruleset())
        assert blocks[0]["type"] == "heading_2"

    def test_non_bold_span_as_paragraph(self) -> None:
        xhtml = '<span style="font-size: 16.0px;">Not a heading</span>'
        blocks = convert_page(xhtml, _default_ruleset())
        assert blocks[0]["type"] == "paragraph"


# --- Edge cases ---


class TestEdgeCases:
    def test_empty_input(self) -> None:
        blocks = convert_page("", _default_ruleset())
        assert blocks == []

    def test_plain_text_only(self) -> None:
        blocks = convert_page("just text", _default_ruleset())
        assert blocks[0]["type"] == "paragraph"
        assert blocks[0]["paragraph"]["rich_text"][0]["text"]["content"] == "just text"

    def test_unknown_macro_as_paragraph(self) -> None:
        xhtml = (
            '<ac:structured-macro ac:name="unknown-thing">'
            '<ac:parameter ac:name="x">val</ac:parameter>'
            "</ac:structured-macro>"
        )
        blocks = convert_page(xhtml, _default_ruleset())
        assert len(blocks) == 1
        assert blocks[0]["type"] == "paragraph"

    def test_disabled_rule_not_applied(self) -> None:
        """When the toc rule is disabled, toc macro becomes a fallback paragraph."""
        ruleset = _default_ruleset()
        for r in ruleset.rules:
            if r.rule_id == "rule:macro:toc":
                r.enabled = False
        xhtml = '<ac:structured-macro ac:name="toc" ac:schema-version="1" />'
        blocks = convert_page(xhtml, ruleset)
        assert blocks[0]["type"] == "paragraph"
