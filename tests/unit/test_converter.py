"""Unit tests for the deterministic XHTML → Notion block converter."""

import logging
from pathlib import Path
from typing import Any

import pytest

from confluence_to_notion.agents.schemas import FinalRule, FinalRuleset, ProposedRule
from confluence_to_notion.converter.converter import convert_page
from confluence_to_notion.converter.resolution import ResolutionStore
from confluence_to_notion.converter.schemas import TableRule, UnresolvedItem
from confluence_to_notion.converter.table_rules import TableRuleStore

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "nested-macros"
TABLE_FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "tables"

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
        blocks = convert_page("<h1>Title</h1>", _default_ruleset()).blocks
        assert blocks == [
            {
                "type": "heading_1",
                "heading_1": {
                    "rich_text": [{"type": "text", "text": {"content": "Title"}}],
                },
            }
        ]

    def test_h2(self) -> None:
        blocks = convert_page("<h2>Section</h2>", _default_ruleset()).blocks
        assert blocks[0]["type"] == "heading_2"

    def test_h3(self) -> None:
        blocks = convert_page("<h3>Subsection</h3>", _default_ruleset()).blocks
        assert blocks[0]["type"] == "heading_3"

    def test_h4_h5_h6_fallback_to_h3(self) -> None:
        """Notion only supports h1-h3; h4+ should map to h3."""
        blocks = convert_page("<h4>Deep heading</h4>", _default_ruleset()).blocks
        assert blocks[0]["type"] == "heading_3"


class TestParagraphs:
    def test_simple_paragraph(self) -> None:
        blocks = convert_page("<p>Hello world</p>", _default_ruleset()).blocks
        assert blocks == [
            {
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "text": {"content": "Hello world"}}],
                },
            }
        ]

    def test_empty_paragraph_skipped(self) -> None:
        blocks = convert_page("<p></p>", _default_ruleset()).blocks
        assert blocks == []

    def test_br_only_paragraph_skipped(self) -> None:
        blocks = convert_page("<p><br /></p>", _default_ruleset()).blocks
        assert blocks == []

    def test_paragraph_with_inline_code(self) -> None:
        blocks = convert_page("<p>Run <code>gradle</code> now</p>", _default_ruleset()).blocks
        rich_text = blocks[0]["paragraph"]["rich_text"]
        assert len(rich_text) == 3
        assert rich_text[0] == {"type": "text", "text": {"content": "Run "}}
        assert rich_text[1]["annotations"]["code"] is True
        assert rich_text[1]["text"]["content"] == "gradle"
        assert rich_text[2] == {"type": "text", "text": {"content": " now"}}

    def test_paragraph_with_bold(self) -> None:
        xhtml = "<p>This is <strong>bold</strong> text</p>"
        blocks = convert_page(xhtml, _default_ruleset()).blocks
        rich_text = blocks[0]["paragraph"]["rich_text"]
        assert rich_text[1]["annotations"]["bold"] is True

    def test_paragraph_with_italic(self) -> None:
        blocks = convert_page("<p>This is <em>italic</em> text</p>", _default_ruleset()).blocks
        rich_text = blocks[0]["paragraph"]["rich_text"]
        assert rich_text[1]["annotations"]["italic"] is True

    def test_paragraph_with_link(self) -> None:
        blocks = convert_page(
            '<p>See <a href="https://example.com">here</a></p>',
            _default_ruleset(),
        ).blocks
        rich_text = blocks[0]["paragraph"]["rich_text"]
        assert rich_text[1]["text"]["link"] == {"url": "https://example.com"}


class TestLists:
    def test_unordered_list(self) -> None:
        blocks = convert_page("<ul><li>one</li><li>two</li></ul>", _default_ruleset()).blocks
        assert len(blocks) == 2
        assert blocks[0]["type"] == "bulleted_list_item"
        assert blocks[0]["bulleted_list_item"]["rich_text"][0]["text"]["content"] == "one"

    def test_ordered_list(self) -> None:
        blocks = convert_page("<ol><li>first</li><li>second</li></ol>", _default_ruleset()).blocks
        assert len(blocks) == 2
        assert blocks[0]["type"] == "numbered_list_item"

    def test_nested_list(self) -> None:
        xhtml = "<ul><li>parent<ul><li>child</li></ul></li></ul>"
        blocks = convert_page(xhtml, _default_ruleset()).blocks
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
        blocks = convert_page(xhtml, _default_ruleset()).blocks
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
        blocks = convert_page(xhtml, _default_ruleset()).blocks
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
        blocks = convert_page(xhtml, _default_ruleset()).blocks
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
        blocks = convert_page(xhtml, _default_ruleset()).blocks
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
        blocks = convert_page(xhtml, _default_ruleset()).blocks
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
        blocks = convert_page(xhtml, _default_ruleset()).blocks
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
        blocks = convert_page(xhtml, _default_ruleset()).blocks
        assert blocks[0]["type"] == "code"
        assert blocks[0]["code"]["language"] == "plain text"

    def test_noformat_macro(self) -> None:
        """noformat macro produces a code block with 'plain text' language."""
        xhtml = (
            '<ac:structured-macro ac:name="noformat">'
            "<ac:plain-text-body><![CDATA[raw text]]></ac:plain-text-body>"
            "</ac:structured-macro>"
        )
        blocks = convert_page(xhtml, _default_ruleset()).blocks
        assert blocks[0]["type"] == "code"
        assert blocks[0]["code"]["language"] == "plain text"
        assert blocks[0]["code"]["rich_text"][0]["text"]["content"] == "raw text"


class TestNestedMacros:
    """Nested macro tests using fixture files from tests/fixtures/nested-macros/."""

    @staticmethod
    def _load_fixture(name: str) -> str:
        return (FIXTURES_DIR / name).read_text()

    def test_info_with_inline_code_from_sample(self) -> None:
        """Real sample: info macro with <code> inside (from samples/27835336.xhtml)."""
        xhtml = self._load_fixture("info-with-code-from-sample.xhtml")
        blocks = convert_page(xhtml, _default_ruleset()).blocks
        assert len(blocks) == 1
        assert blocks[0]["type"] == "callout"
        callout = blocks[0]["callout"]
        # Verify the real-world text is preserved
        text = "".join(seg["text"]["content"] for seg in callout["rich_text"])
        assert "./gradlew eclipse" in text
        assert "regenerate the projects" in text

    def test_expand_with_nested_code(self) -> None:
        """Expand containing a code macro → toggle with code block child."""
        xhtml = self._load_fixture("expand-with-code.xhtml")
        blocks = convert_page(xhtml, _default_ruleset()).blocks
        assert len(blocks) == 1
        assert blocks[0]["type"] == "toggle"
        toggle = blocks[0]["toggle"]
        assert toggle["rich_text"][0]["text"]["content"] == "Show configuration example"
        children = toggle["children"]
        code_children = [c for c in children if c["type"] == "code"]
        assert len(code_children) == 1
        assert code_children[0]["code"]["language"] == "properties"
        assert "broker.id=0" in code_children[0]["code"]["rich_text"][0]["text"]["content"]

    def test_three_level_expand_info_code(self) -> None:
        """Expand > info > code → toggle > callout > code (3-level nesting)."""
        xhtml = self._load_fixture("expand-with-info-and-code.xhtml")
        blocks = convert_page(xhtml, _default_ruleset()).blocks
        assert len(blocks) == 1
        assert blocks[0]["type"] == "toggle"
        toggle = blocks[0]["toggle"]
        assert toggle["rich_text"][0]["text"]["content"] == "Installation steps"
        toggle_children = toggle["children"]
        assert len(toggle_children) == 1
        assert toggle_children[0]["type"] == "callout"
        callout = toggle_children[0]["callout"]
        text = "".join(seg["text"]["content"] for seg in callout["rich_text"])
        assert "JDK 11" in text
        callout_children = callout["children"]
        code_children = [c for c in callout_children if c["type"] == "code"]
        assert len(code_children) == 1
        assert code_children[0]["code"]["language"] == "bash"
        assert "gradlew jar" in code_children[0]["code"]["rich_text"][0]["text"]["content"]

    def test_warning_with_nested_info(self) -> None:
        """Warning panel containing info panel → callout with callout child."""
        xhtml = self._load_fixture("warning-with-info.xhtml")
        blocks = convert_page(xhtml, _default_ruleset()).blocks
        assert len(blocks) == 1
        assert blocks[0]["type"] == "callout"
        outer = blocks[0]["callout"]
        assert outer["icon"]["emoji"] == "\u26a0\ufe0f"
        assert outer["color"] == "yellow_background"
        assert "Breaking change" in outer["rich_text"][0]["text"]["content"]
        assert "children" in outer
        children = outer["children"]
        info_children = [c for c in children if c["type"] == "callout"]
        assert len(info_children) == 1
        inner = info_children[0]["callout"]
        assert inner["icon"]["emoji"] == "\u2139\ufe0f"
        assert inner["color"] == "blue_background"

    def test_note_with_jira_and_code(self) -> None:
        """Note panel with JIRA macro + code block — mixed nesting from real patterns."""
        xhtml = self._load_fixture("panel-with-jira-and-code.xhtml")
        blocks = convert_page(xhtml, _default_ruleset()).blocks
        assert len(blocks) == 1
        assert blocks[0]["type"] == "callout"
        callout = blocks[0]["callout"]
        # Note panel should have children including code block
        assert "children" in callout
        children = callout["children"]
        code_children = [c for c in children if c["type"] == "code"]
        assert len(code_children) == 1
        assert "gradlew eclipse" in code_children[0]["code"]["rich_text"][0]["text"]["content"]


# --- Confluence Elements ---


class TestAcLink:
    def test_ac_link_in_paragraph(self) -> None:
        xhtml = (
            "<p>See "
            '<ac:link><ri:page ri:content-title="Setup Guide" /></ac:link>'
            " for details</p>"
        )
        blocks = convert_page(xhtml, _default_ruleset()).blocks
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
        blocks = convert_page(xhtml, _default_ruleset()).blocks
        rt = blocks[0]["paragraph"]["rich_text"]
        link_seg = next(s for s in rt if s["text"].get("link"))
        assert link_seg["text"]["content"] == "Kafka compression"


class TestAcImage:
    def test_image(self) -> None:
        xhtml = '<ac:image ac:height="250"><ri:attachment ri:filename="pic.jpg" /></ac:image>'
        blocks = convert_page(xhtml, _default_ruleset()).blocks
        assert blocks[0]["type"] == "image"
        assert blocks[0]["image"]["type"] == "external"
        assert "pic.jpg" in blocks[0]["image"]["external"]["url"]


# --- Formatting ---


class TestPreformatted:
    def test_pre_block(self) -> None:
        xhtml = "<pre>line1<br />line2</pre>"
        blocks = convert_page(xhtml, _default_ruleset()).blocks
        assert blocks[0]["type"] == "code"
        content = blocks[0]["code"]["rich_text"][0]["text"]["content"]
        assert content == "line1\nline2"
        assert blocks[0]["code"]["language"] == "plain text"


class TestStyledSpan:
    def test_bold_large_span_as_heading(self) -> None:
        xhtml = '<span style="font-size: 16.0px;font-weight: bold;">Section Title</span>'
        blocks = convert_page(xhtml, _default_ruleset()).blocks
        assert blocks[0]["type"] == "heading_2"

    def test_non_bold_span_as_paragraph(self) -> None:
        xhtml = '<span style="font-size: 16.0px;">Not a heading</span>'
        blocks = convert_page(xhtml, _default_ruleset()).blocks
        assert blocks[0]["type"] == "paragraph"


# --- Edge cases ---


class TestEdgeCases:
    def test_empty_input(self) -> None:
        blocks = convert_page("", _default_ruleset()).blocks
        assert blocks == []

    def test_plain_text_only(self) -> None:
        blocks = convert_page("just text", _default_ruleset()).blocks
        assert blocks[0]["type"] == "paragraph"
        assert blocks[0]["paragraph"]["rich_text"][0]["text"]["content"] == "just text"

    def test_unknown_macro_as_paragraph(self) -> None:
        xhtml = (
            '<ac:structured-macro ac:name="unknown-thing">'
            '<ac:parameter ac:name="x">val</ac:parameter>'
            "</ac:structured-macro>"
        )
        blocks = convert_page(xhtml, _default_ruleset()).blocks
        assert len(blocks) == 1
        assert blocks[0]["type"] == "paragraph"

    def test_disabled_rule_not_applied(self) -> None:
        """When the toc rule is disabled, toc macro becomes a fallback paragraph."""
        ruleset = _default_ruleset()
        for r in ruleset.rules:
            if r.rule_id == "rule:macro:toc":
                r.enabled = False
        xhtml = '<ac:structured-macro ac:name="toc" ac:schema-version="1" />'
        blocks = convert_page(xhtml, ruleset).blocks
        assert blocks[0]["type"] == "paragraph"


# --- Large page conversion warning ---


class TestLargePageConversion:
    """Tests for warning logs emitted when converting large pages."""

    @staticmethod
    def _make_large_xhtml(p_count: int) -> str:
        """Generate XHTML with `p_count` paragraph tags."""
        return "".join(f"<p>Paragraph {i}</p>" for i in range(p_count))

    def test_large_page_produces_expected_block_count(self) -> None:
        """200+ <p> tags should produce 200+ blocks."""
        xhtml = self._make_large_xhtml(200)
        blocks = convert_page(xhtml, _default_ruleset()).blocks
        assert len(blocks) == 200

    def test_large_page_emits_warning_log(self, caplog: pytest.LogCaptureFixture) -> None:
        """Converting XHTML producing >100 blocks emits a warning with block count and size."""
        xhtml = self._make_large_xhtml(150)
        with caplog.at_level(logging.WARNING, logger="confluence_to_notion.converter.converter"):
            blocks = convert_page(xhtml, _default_ruleset()).blocks
        assert len(blocks) == 150
        warning_records = [
            r for r in caplog.records
            if r.name == "confluence_to_notion.converter.converter"
            and r.levelno == logging.WARNING
        ]
        assert len(warning_records) == 1
        assert "150" in warning_records[0].message  # block count

    def test_small_page_no_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """XHTML under the threshold does NOT emit a warning."""
        xhtml = self._make_large_xhtml(50)
        with caplog.at_level(logging.WARNING, logger="confluence_to_notion.converter.converter"):
            blocks = convert_page(xhtml, _default_ruleset()).blocks
        assert len(blocks) == 50
        warning_records = [
            r for r in caplog.records
            if r.name == "confluence_to_notion.converter.converter"
            and r.levelno == logging.WARNING
        ]
        assert len(warning_records) == 0


# --- Unresolved item collection ---


class TestUnresolvedCollection:
    """convert_page collects UnresolvedItem for elements it can't handle deterministically."""

    def test_unknown_macro_collected(self) -> None:
        """Unknown macro produces a placeholder block AND an unresolved item."""
        xhtml = (
            '<ac:structured-macro ac:name="custom-board">'
            "<ac:rich-text-body><p>Board content</p></ac:rich-text-body>"
            "</ac:structured-macro>"
        )
        result = convert_page(xhtml, _default_ruleset(), page_id="pg-1")
        # Still produces placeholder block
        assert len(result.blocks) == 1
        assert result.blocks[0]["type"] == "paragraph"
        # Collects unresolved item
        assert len(result.unresolved) == 1
        item = result.unresolved[0]
        assert item.kind == "macro"
        assert item.identifier == "custom-board"
        assert item.source_page_id == "pg-1"

    def test_known_macro_no_unresolved(self) -> None:
        """Known macros (toc, info, etc.) produce NO unresolved items."""
        xhtml = (
            '<ac:structured-macro ac:name="toc" ac:schema-version="1">'
            '<ac:parameter ac:name="maxLevel">3</ac:parameter>'
            "</ac:structured-macro>"
        )
        result = convert_page(xhtml, _default_ruleset(), page_id="pg-2")
        assert len(result.blocks) == 1
        assert result.blocks[0]["type"] == "table_of_contents"
        assert result.unresolved == []

    def test_ac_link_collected(self) -> None:
        """Internal page links are collected as unresolved page_link items."""
        xhtml = (
            "<p>See "
            '<ac:link><ri:page ri:content-title="Setup Guide" /></ac:link>'
            " for details</p>"
        )
        result = convert_page(xhtml, _default_ruleset(), page_id="pg-3")
        # Still produces block with placeholder link
        assert len(result.blocks) == 1
        # Collects page link unresolved
        page_links = [u for u in result.unresolved if u.kind == "page_link"]
        assert len(page_links) == 1
        assert page_links[0].identifier == "Setup Guide"
        assert page_links[0].source_page_id == "pg-3"

    def test_mixed_known_unknown(self) -> None:
        """Page with both known and unknown elements only collects unknowns."""
        xhtml = (
            "<h1>Title</h1>"
            '<ac:structured-macro ac:name="toc" />'
            '<ac:structured-macro ac:name="fancy-widget">'
            "<ac:rich-text-body><p>Widget</p></ac:rich-text-body>"
            "</ac:structured-macro>"
        )
        result = convert_page(xhtml, _default_ruleset(), page_id="pg-4")
        assert len(result.blocks) == 3  # heading + toc + placeholder
        assert len(result.unresolved) == 1
        assert result.unresolved[0].identifier == "fancy-widget"

    def test_no_page_id_still_works(self) -> None:
        """Without page_id, unresolved items have empty source_page_id."""
        xhtml = '<ac:structured-macro ac:name="mystery" />'
        result = convert_page(xhtml, _default_ruleset())
        assert len(result.unresolved) == 1
        assert result.unresolved[0].source_page_id == ""


# --- Re-conversion with resolution store ---


class TestResolvedConversion:
    """When a ResolutionStore has entries, converter uses them instead of placeholders."""

    def test_resolved_macro_uses_store_blocks(self, tmp_path: Path) -> None:
        """Macro resolved in store → use stored Notion blocks, no unresolved."""
        store = ResolutionStore(tmp_path / "res.json")
        store.add(
            key="macro:custom-board",
            resolved_by="ai_inference",
            value={
                "notion_blocks": [
                    {
                        "type": "callout",
                        "callout": {
                            "icon": {"type": "emoji", "emoji": "\U0001f4cb"},
                            "color": "blue_background",
                            "rich_text": [
                                {"type": "text", "text": {"content": "Board content"}}
                            ],
                        },
                    }
                ]
            },
            confidence=0.9,
        )
        xhtml = (
            '<ac:structured-macro ac:name="custom-board">'
            "<ac:rich-text-body><p>Board content</p></ac:rich-text-body>"
            "</ac:structured-macro>"
        )
        result = convert_page(xhtml, _default_ruleset(), page_id="pg-1", store=store)

        assert len(result.blocks) == 1
        assert result.blocks[0]["type"] == "callout"
        assert result.unresolved == []

    def test_unresolved_macro_still_placeholder(self, tmp_path: Path) -> None:
        """Macro NOT in store → placeholder + unresolved (same as before)."""
        store = ResolutionStore(tmp_path / "res.json")
        xhtml = '<ac:structured-macro ac:name="unknown-thing" />'
        result = convert_page(xhtml, _default_ruleset(), store=store)

        assert result.blocks[0]["type"] == "paragraph"
        assert len(result.unresolved) == 1

    def test_resolved_page_link_uses_mention(self, tmp_path: Path) -> None:
        """Page link resolved in store → Notion page mention segment, no unresolved."""
        store = ResolutionStore(tmp_path / "res.json")
        store.add(
            key="page_link:Setup Guide",
            resolved_by="auto_lookup",
            value={"notion_page_id": "abc123def456"},
        )
        xhtml = (
            "<p>See "
            '<ac:link><ri:page ri:content-title="Setup Guide" /></ac:link>'
            "</p>"
        )
        result = convert_page(xhtml, _default_ruleset(), page_id="pg-1", store=store)

        rt = result.blocks[0]["paragraph"]["rich_text"]
        mention_segs = [s for s in rt if s.get("type") == "mention"]
        assert len(mention_segs) == 1
        mention = mention_segs[0]
        assert mention["mention"] == {"type": "page", "page": {"id": "abc123def456"}}
        assert mention["plain_text"] == "Setup Guide"
        # No text segment carrying a notion.so URL
        for seg in rt:
            if seg.get("type") == "text":
                assert "notion.so" not in (seg.get("text", {}).get("link") or {}).get("url", "")

    def test_resolved_page_link_mention_uses_link_body_text(self, tmp_path: Path) -> None:
        """When plain-text-link-body is present, mention plain_text uses it."""
        store = ResolutionStore(tmp_path / "res.json")
        store.add(
            key="page_link:Setup Guide",
            resolved_by="auto_lookup",
            value={"notion_page_id": "abc123def456"},
        )
        xhtml = (
            "<p>See "
            '<ac:link><ri:page ri:content-title="Setup Guide" />'
            "<ac:plain-text-link-body>the setup doc</ac:plain-text-link-body>"
            "</ac:link>"
            "</p>"
        )
        result = convert_page(xhtml, _default_ruleset(), page_id="pg-1", store=store)

        rt = result.blocks[0]["paragraph"]["rich_text"]
        mention_segs = [s for s in rt if s.get("type") == "mention"]
        assert len(mention_segs) == 1
        assert mention_segs[0]["plain_text"] == "the setup doc"

    def test_resolved_page_link_emits_no_unresolved(self, tmp_path: Path) -> None:
        """Mention path must NOT append an UnresolvedItem of kind 'page_link'."""
        store = ResolutionStore(tmp_path / "res.json")
        store.add(
            key="page_link:Setup Guide",
            resolved_by="auto_lookup",
            value={"notion_page_id": "abc123def456"},
        )
        xhtml = (
            "<p>See "
            '<ac:link><ri:page ri:content-title="Setup Guide" /></ac:link>'
            "</p>"
        )
        result = convert_page(xhtml, _default_ruleset(), page_id="pg-1", store=store)

        page_links = [u for u in result.unresolved if u.kind == "page_link"]
        assert page_links == []

    def test_unresolved_page_link_still_placeholder(self, tmp_path: Path) -> None:
        """Page link NOT in store → placeholder URL + unresolved."""
        store = ResolutionStore(tmp_path / "res.json")
        xhtml = (
            "<p>See "
            '<ac:link><ri:page ri:content-title="Unknown Page" /></ac:link>'
            "</p>"
        )
        result = convert_page(xhtml, _default_ruleset(), store=store)

        rt = result.blocks[0]["paragraph"]["rich_text"]
        link_seg = next(s for s in rt if s["text"].get("link"))
        assert "placeholder" in link_seg["text"]["link"]["url"]
        assert len(result.unresolved) == 1

    def test_no_store_same_as_before(self) -> None:
        """Without store param, behavior is identical to previous tests."""
        xhtml = '<ac:structured-macro ac:name="mystery" />'
        result = convert_page(xhtml, _default_ruleset())
        assert result.blocks[0]["type"] == "paragraph"
        assert len(result.unresolved) == 1


# --- Include / excerpt-include → synced block ---


class TestMacroIncludeSyncedBlock:
    """include / excerpt-include macros map to Notion synced_block references."""

    @staticmethod
    def _include_xhtml(macro_name: str, page_title: str) -> str:
        return (
            f'<ac:structured-macro ac:name="{macro_name}">'
            '<ac:parameter ac:name="">'
            f'<ac:link><ri:page ri:content-title="{page_title}" /></ac:link>'
            "</ac:parameter>"
            "</ac:structured-macro>"
        )

    def test_resolved_include_emits_synced_block(self, tmp_path: Path) -> None:
        """Include with resolved store entry → synced_block referencing original block_id."""
        store = ResolutionStore(tmp_path / "res.json")
        store.add(
            key="synced_block:Source Page",
            resolved_by="notion_migration",
            value={"original_block_id": "abc123def456"},
        )
        xhtml = self._include_xhtml("include", "Source Page")
        result = convert_page(xhtml, _default_ruleset(), page_id="pg-1", store=store)

        assert len(result.blocks) == 1
        assert result.blocks[0] == {
            "type": "synced_block",
            "synced_block": {
                "synced_from": {"type": "block_id", "block_id": "abc123def456"},
            },
        }
        assert result.unresolved == []

    def test_resolved_excerpt_include_emits_synced_block(self, tmp_path: Path) -> None:
        """excerpt-include with resolved store entry → synced_block reference."""
        store = ResolutionStore(tmp_path / "res.json")
        store.add(
            key="synced_block:Source Page",
            resolved_by="notion_migration",
            value={"original_block_id": "xyz789"},
        )
        xhtml = self._include_xhtml("excerpt-include", "Source Page")
        result = convert_page(xhtml, _default_ruleset(), page_id="pg-1", store=store)

        assert len(result.blocks) == 1
        assert result.blocks[0] == {
            "type": "synced_block",
            "synced_block": {
                "synced_from": {"type": "block_id", "block_id": "xyz789"},
            },
        }
        assert result.unresolved == []

    def test_unresolved_include_emits_placeholder_and_unresolved(self) -> None:
        """Include without store entry → placeholder paragraph + synced_block unresolved."""
        xhtml = self._include_xhtml("include", "Missing Page")
        result = convert_page(xhtml, _default_ruleset(), page_id="pg-1")

        assert len(result.blocks) == 1
        assert result.blocks[0]["type"] == "paragraph"
        text = result.blocks[0]["paragraph"]["rich_text"][0]["text"]["content"]
        assert text == "[include: Missing Page]"

        assert len(result.unresolved) == 1
        item = result.unresolved[0]
        assert item.kind == "synced_block"
        assert item.identifier == "Missing Page"
        assert item.source_page_id == "pg-1"

    def test_unresolved_excerpt_include_emits_placeholder_and_unresolved(self) -> None:
        """excerpt-include without store entry → placeholder + synced_block unresolved."""
        xhtml = self._include_xhtml("excerpt-include", "Missing Page")
        result = convert_page(xhtml, _default_ruleset(), page_id="pg-2")

        assert len(result.blocks) == 1
        assert result.blocks[0]["type"] == "paragraph"
        text = result.blocks[0]["paragraph"]["rich_text"][0]["text"]["content"]
        assert text == "[excerpt-include: Missing Page]"

        assert len(result.unresolved) == 1
        item = result.unresolved[0]
        assert item.kind == "synced_block"
        assert item.identifier == "Missing Page"
        assert item.source_page_id == "pg-2"

    def test_include_page_title_parsed_from_ac_link_ri_page(self, tmp_path: Path) -> None:
        """Page title is extracted from <ac:link><ri:page ri:content-title='…'/></ac:link>."""
        store = ResolutionStore(tmp_path / "res.json")
        store.add(
            key="synced_block:Architecture Overview",
            resolved_by="notion_migration",
            value={"original_block_id": "block-arch-001"},
        )
        xhtml = self._include_xhtml("include", "Architecture Overview")
        result = convert_page(xhtml, _default_ruleset(), page_id="pg-1", store=store)

        assert len(result.blocks) == 1
        assert result.blocks[0]["type"] == "synced_block"
        assert (
            result.blocks[0]["synced_block"]["synced_from"]["block_id"]
            == "block-arch-001"
        )
        assert result.unresolved == []


# --- UnresolvedItem schema ---


class TestUnresolvedItemSchema:
    def test_kind_table_is_valid(self) -> None:
        """UnresolvedItem must accept kind='table' so future AI resolvers can override."""
        item = UnresolvedItem(
            kind="table",
            identifier="tbl-0",
            source_page_id="pg-1",
        )
        assert item.kind == "table"


# --- Table conversion ---


class TestTableConversion:
    """<table> → Notion table block + UnresolvedItem(kind='table')."""

    def test_simple_table_with_thead_and_tbody(self) -> None:
        """2-column x 2-row table with thead → single Notion table block."""
        xhtml = (
            "<table>"
            "<thead><tr><th>Name</th><th>Role</th></tr></thead>"
            "<tbody>"
            "<tr><td>Alice</td><td>Dev</td></tr>"
            "<tr><td>Bob</td><td>PM</td></tr>"
            "</tbody>"
            "</table>"
        )
        result = convert_page(xhtml, _default_ruleset(), page_id="pg-1")
        table_blocks = [b for b in result.blocks if b["type"] == "table"]
        assert len(table_blocks) == 1
        table = table_blocks[0]["table"]
        assert table["table_width"] == 2
        assert table["has_column_header"] is True
        assert table["has_row_header"] is False

        rows = table["children"]
        assert len(rows) == 3  # 1 header + 2 data rows
        for row in rows:
            assert row["type"] == "table_row"
            cells = row["table_row"]["cells"]
            assert len(cells) == 2
            for cell in cells:
                assert isinstance(cell, list)
                for seg in cell:
                    assert seg["type"] == "text"

        # Verify header row content
        header_cells = rows[0]["table_row"]["cells"]
        assert header_cells[0][0]["text"]["content"] == "Name"
        assert header_cells[1][0]["text"]["content"] == "Role"
        # Verify first data row
        first_data_cells = rows[1]["table_row"]["cells"]
        assert first_data_cells[0][0]["text"]["content"] == "Alice"
        assert first_data_cells[1][0]["text"]["content"] == "Dev"

    def test_table_preserves_inline_formatting_in_cells(self) -> None:
        """<strong> and <code> inside <td> → annotations preserved in rich_text."""
        xhtml = (
            "<table>"
            "<tbody>"
            "<tr>"
            "<td>Run <code>build</code> for <strong>release</strong></td>"
            "<td>ok</td>"
            "</tr>"
            "</tbody>"
            "</table>"
        )
        result = convert_page(xhtml, _default_ruleset(), page_id="pg-1")
        table_blocks = [b for b in result.blocks if b["type"] == "table"]
        assert len(table_blocks) == 1
        rows = table_blocks[0]["table"]["children"]
        cell = rows[0]["table_row"]["cells"][0]
        code_segs = [s for s in cell if s.get("annotations", {}).get("code")]
        assert len(code_segs) == 1
        assert code_segs[0]["text"]["content"] == "build"
        bold_segs = [s for s in cell if s.get("annotations", {}).get("bold")]
        assert len(bold_segs) == 1
        assert bold_segs[0]["text"]["content"] == "release"

    def test_table_without_thead_has_no_column_header(self) -> None:
        """Table without <thead> → has_column_header=False, only <tbody> rows."""
        xhtml = (
            "<table>"
            "<tbody>"
            "<tr><td>a</td><td>b</td></tr>"
            "<tr><td>c</td><td>d</td></tr>"
            "</tbody>"
            "</table>"
        )
        result = convert_page(xhtml, _default_ruleset(), page_id="pg-1")
        table_blocks = [b for b in result.blocks if b["type"] == "table"]
        assert len(table_blocks) == 1
        table = table_blocks[0]["table"]
        assert table["has_column_header"] is False
        assert table["table_width"] == 2
        rows = table["children"]
        assert len(rows) == 2

    def test_empty_table_produces_no_blocks(self) -> None:
        """<table></table> → no blocks, no crash, no unresolved item."""
        xhtml = "<table></table>"
        result = convert_page(xhtml, _default_ruleset(), page_id="pg-1")
        table_blocks = [b for b in result.blocks if b["type"] == "table"]
        assert table_blocks == []
        tables_unresolved = [u for u in result.unresolved if u.kind == "table"]
        assert tables_unresolved == []

    def test_non_empty_table_emits_unresolved_item(self) -> None:
        """Every rendered table emits one UnresolvedItem(kind='table') with context_xhtml."""
        xhtml = (
            "<table>"
            "<tbody><tr><td>a</td><td>b</td></tr></tbody>"
            "</table>"
        )
        result = convert_page(xhtml, _default_ruleset(), page_id="pg-42")
        tables_unresolved = [u for u in result.unresolved if u.kind == "table"]
        assert len(tables_unresolved) == 1
        item = tables_unresolved[0]
        assert item.identifier  # non-empty stable id
        assert item.source_page_id == "pg-42"
        assert item.context_xhtml is not None
        assert "<" in item.context_xhtml  # XHTML snippet

    def test_simple_table_fixture(self) -> None:
        """End-to-end parity: fixture-based Confluence table → Notion table block."""
        xhtml = (TABLE_FIXTURES_DIR / "simple-table.xhtml").read_text()
        result = convert_page(xhtml, _default_ruleset(), page_id="pg-fixture")
        table_blocks = [b for b in result.blocks if b["type"] == "table"]
        assert len(table_blocks) == 1
        table = table_blocks[0]["table"]
        assert table["table_width"] == 3
        assert table["has_column_header"] is True

        rows = table["children"]
        # 1 header + 3 data rows
        assert len(rows) == 4

        # First data row: **broker** | ready | Run `gradlew build` first
        first_data_cells = rows[1]["table_row"]["cells"]
        # cell 0: strong "broker"
        cell0 = first_data_cells[0]
        bold_segs = [s for s in cell0 if s.get("annotations", {}).get("bold")]
        assert len(bold_segs) == 1
        assert bold_segs[0]["text"]["content"] == "broker"
        # cell 2: inline code preserved
        cell2 = first_data_cells[2]
        code_segs = [s for s in cell2 if s.get("annotations", {}).get("code")]
        assert len(code_segs) == 1
        assert code_segs[0]["text"]["content"] == "gradlew build"

    def test_resolved_table_uses_store_blocks(self, tmp_path: Path) -> None:
        """When store has 'table:{identifier}' with notion_blocks, use them and no unresolved."""
        # Step 1: run once to discover the stable identifier for this table
        xhtml = (
            "<table>"
            "<tbody><tr><td>a</td><td>b</td></tr></tbody>"
            "</table>"
        )
        first = convert_page(xhtml, _default_ruleset(), page_id="pg-1")
        identifier = next(u.identifier for u in first.unresolved if u.kind == "table")

        # Step 2: prime the store with that key → Notion DB reference block
        store = ResolutionStore(tmp_path / "res.json")
        store.add(
            key=f"table:{identifier}",
            resolved_by="ai_inference",
            value={
                "notion_blocks": [
                    {
                        "type": "child_database",
                        "child_database": {"title": "Team"},
                    }
                ]
            },
            confidence=0.85,
        )

        # Step 3: re-run with the store → resolved blocks, no unresolved
        result = convert_page(xhtml, _default_ruleset(), page_id="pg-1", store=store)
        assert result.blocks == [
            {"type": "child_database", "child_database": {"title": "Team"}}
        ]
        tables_unresolved = [u for u in result.unresolved if u.kind == "table"]
        assert tables_unresolved == []


# --- Table conversion with TableRuleStore (Pass 1.5 rule hits) ---


class TestTableConversionWithTableRules:
    """convert_page consults a TableRuleStore by header signature.

    A confirmed-layout rule (is_database=False) suppresses the UnresolvedItem.
    A confirmed-database rule (is_database=True) still emits the UnresolvedItem
    so part 3 can pick it up and create the Notion database. In both branches
    this PR keeps emitting the plain Notion table block — actual database
    materialization is out-of-scope here.
    """

    @staticmethod
    def _table_xhtml(headers: list[str], rows: list[list[str]]) -> str:
        thead = (
            "<thead><tr>"
            + "".join(f"<th>{h}</th>" for h in headers)
            + "</tr></thead>"
        )
        tbody = (
            "<tbody>"
            + "".join(
                "<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>"
                for row in rows
            )
            + "</tbody>"
        )
        return f"<table>{thead}{tbody}</table>"

    def test_rule_hit_layout_suppresses_unresolved(self, tmp_path: Path) -> None:
        """Rule hit with is_database=False → plain table block, NO table unresolved."""
        store = TableRuleStore(tmp_path / "table-rules.json")
        # Headers in the page differ in case/whitespace from the upsert call to
        # exercise normalize_header_signature.
        store.upsert(
            ["Name", "Role"],
            TableRule(is_database=False),
        )
        store.save()

        xhtml = self._table_xhtml(
            ["  name ", "ROLE"],
            [["Alice", "Dev"], ["Bob", "PM"]],
        )
        result = convert_page(
            xhtml,
            _default_ruleset(),
            page_id="pg-1",
            table_rules=store,
        )

        # Plain Notion table block still emitted
        table_blocks = [b for b in result.blocks if b["type"] == "table"]
        assert len(table_blocks) == 1
        # Layout rule = resolution final → no UnresolvedItem(kind='table')
        tables_unresolved = [u for u in result.unresolved if u.kind == "table"]
        assert tables_unresolved == []

    def test_rule_hit_database_still_emits_unresolved(
        self, tmp_path: Path
    ) -> None:
        """Rule hit with is_database=True → plain table block + table unresolved (part 3)."""
        store = TableRuleStore(tmp_path / "table-rules.json")
        store.upsert(
            ["Name", "Role"],
            TableRule(
                is_database=True,
                title_column="name",
                column_types={"name": "title", "role": "select"},
            ),
        )
        store.save()

        xhtml = self._table_xhtml(
            ["Name", "Role"],
            [["Alice", "Dev"], ["Bob", "PM"]],
        )
        result = convert_page(
            xhtml,
            _default_ruleset(),
            page_id="pg-1",
            table_rules=store,
        )

        # Plain Notion table block still emitted (DB materialization is part 3)
        table_blocks = [b for b in result.blocks if b["type"] == "table"]
        assert len(table_blocks) == 1
        # Database candidate → UnresolvedItem so part 3 can pick it up
        tables_unresolved = [u for u in result.unresolved if u.kind == "table"]
        assert len(tables_unresolved) == 1
        assert tables_unresolved[0].source_page_id == "pg-1"
        assert tables_unresolved[0].context_xhtml is not None

    def test_rule_miss_preserves_existing_behavior(self, tmp_path: Path) -> None:
        """No matching signature → plain table + UnresolvedItem (current behavior)."""
        store = TableRuleStore(tmp_path / "table-rules.json")
        # Different headers — no match for the page's table.
        store.upsert(
            ["Different", "Headers"],
            TableRule(is_database=False),
        )
        store.save()

        xhtml = self._table_xhtml(
            ["Name", "Role"],
            [["Alice", "Dev"]],
        )
        result = convert_page(
            xhtml,
            _default_ruleset(),
            page_id="pg-1",
            table_rules=store,
        )

        table_blocks = [b for b in result.blocks if b["type"] == "table"]
        assert len(table_blocks) == 1
        tables_unresolved = [u for u in result.unresolved if u.kind == "table"]
        assert len(tables_unresolved) == 1
        assert tables_unresolved[0].context_xhtml is not None

    def test_resolution_store_short_circuits_before_table_rules(
        self, tmp_path: Path
    ) -> None:
        """Pre-resolved 'table:{identifier}' in ResolutionStore wins over TableRuleStore."""
        xhtml = self._table_xhtml(["Name", "Role"], [["Alice", "Dev"]])

        # Discover the stable identifier first.
        first = convert_page(xhtml, _default_ruleset(), page_id="pg-1")
        identifier = next(u.identifier for u in first.unresolved if u.kind == "table")

        res_store = ResolutionStore(tmp_path / "res.json")
        res_store.add(
            key=f"table:{identifier}",
            resolved_by="notion_migration",
            value={
                "notion_blocks": [
                    {"type": "child_database", "child_database": {"title": "T"}}
                ]
            },
        )

        # TableRuleStore has a database-flagged rule too; ResolutionStore must win.
        tr_store = TableRuleStore(tmp_path / "table-rules.json")
        tr_store.upsert(
            ["Name", "Role"],
            TableRule(is_database=True, title_column="name"),
        )

        result = convert_page(
            xhtml,
            _default_ruleset(),
            page_id="pg-1",
            store=res_store,
            table_rules=tr_store,
        )
        assert result.blocks == [
            {"type": "child_database", "child_database": {"title": "T"}}
        ]
        tables_unresolved = [u for u in result.unresolved if u.kind == "table"]
        assert tables_unresolved == []
