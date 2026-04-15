"""Unit tests for agent I/O schemas."""


import pytest
from pydantic import ValidationError

from confluence_to_notion.agents.schemas import (
    DiscoveryOutput,
    DiscoveryPattern,
    FinalRule,
    FinalRuleset,
    ProposedRule,
    ProposerOutput,
)

# --- DiscoveryPattern ---


class TestDiscoveryPattern:
    def test_minimal_pattern(self) -> None:
        p = DiscoveryPattern(
            pattern_id="macro:toc",
            pattern_type="macro",
            description="Table of contents macro",
            example_snippets=["<ac:structured-macro ac:name=\"toc\"/>"],
            source_pages=["27835336"],
            frequency=1,
        )
        assert p.pattern_id == "macro:toc"
        assert p.pattern_type == "macro"
        assert len(p.example_snippets) == 1

    def test_pattern_with_multiple_snippets(self) -> None:
        p = DiscoveryPattern(
            pattern_id="macro:jira",
            pattern_type="macro",
            description="Jira issue reference",
            example_snippets=[
                '<ac:structured-macro ac:name="jira">'
                '<ac:parameter ac:name="key">KAFKA-123</ac:parameter>'
                "</ac:structured-macro>",
                '<ac:structured-macro ac:name="jira">'
                '<ac:parameter ac:name="key">KAFKA-456</ac:parameter>'
                "</ac:structured-macro>",
            ],
            source_pages=["27835336", "27849051"],
            frequency=5,
        )
        assert len(p.example_snippets) == 2
        assert len(p.source_pages) == 2

    def test_pattern_requires_at_least_one_snippet(self) -> None:
        with pytest.raises(ValidationError, match="example_snippets"):
            DiscoveryPattern(
                pattern_id="macro:toc",
                pattern_type="macro",
                description="TOC",
                example_snippets=[],
                source_pages=["123"],
                frequency=1,
            )

    def test_pattern_requires_at_least_one_source_page(self) -> None:
        with pytest.raises(ValidationError, match="source_pages"):
            DiscoveryPattern(
                pattern_id="macro:toc",
                pattern_type="macro",
                description="TOC",
                example_snippets=["<ac:structured-macro/>"],
                source_pages=[],
                frequency=1,
            )

    def test_frequency_must_be_positive(self) -> None:
        with pytest.raises(ValidationError, match="frequency"):
            DiscoveryPattern(
                pattern_id="macro:toc",
                pattern_type="macro",
                description="TOC",
                example_snippets=["<ac:structured-macro/>"],
                source_pages=["123"],
                frequency=0,
            )


# --- DiscoveryOutput ---


class TestDiscoveryOutput:
    def test_valid_output(self) -> None:
        output = DiscoveryOutput(
            sample_dir="samples/",
            pages_analyzed=5,
            patterns=[
                DiscoveryPattern(
                    pattern_id="macro:toc",
                    pattern_type="macro",
                    description="Table of contents",
                    example_snippets=["<ac:structured-macro ac:name=\"toc\"/>"],
                    source_pages=["27835336"],
                    frequency=1,
                ),
            ],
        )
        assert output.pages_analyzed == 5
        assert len(output.patterns) == 1

    def test_empty_patterns_allowed(self) -> None:
        """A page set with no patterns is valid (unlikely but possible)."""
        output = DiscoveryOutput(
            sample_dir="samples/",
            pages_analyzed=1,
            patterns=[],
        )
        assert len(output.patterns) == 0

    def test_pages_analyzed_must_be_positive(self) -> None:
        with pytest.raises(ValidationError, match="pages_analyzed"):
            DiscoveryOutput(sample_dir="samples/", pages_analyzed=0, patterns=[])

    def test_json_roundtrip(self) -> None:
        output = DiscoveryOutput(
            sample_dir="samples/",
            pages_analyzed=3,
            patterns=[
                DiscoveryPattern(
                    pattern_id="element:ac-link",
                    pattern_type="element",
                    description="Confluence internal link",
                    example_snippets=['<ac:link><ri:page ri:content-title="Foo"/></ac:link>'],
                    source_pages=["123"],
                    frequency=10,
                ),
            ],
        )
        json_str = output.model_dump_json(indent=2)
        parsed = DiscoveryOutput.model_validate_json(json_str)
        assert parsed == output


# --- ProposedRule / ProposerOutput ---


class TestProposedRule:
    def test_valid_rule(self) -> None:
        rule = ProposedRule(
            rule_id="rule:macro:toc",
            source_pattern_id="macro:toc",
            source_description="Table of contents macro",
            notion_block_type="table_of_contents",
            mapping_description="Map ac:structured-macro[toc] to Notion TOC block",
            example_input='<ac:structured-macro ac:name="toc"/>',
            example_output={"type": "table_of_contents", "table_of_contents": {}},
            confidence="high",
        )
        assert rule.confidence == "high"

    def test_confidence_must_be_valid(self) -> None:
        with pytest.raises(ValidationError, match="confidence"):
            ProposedRule(
                rule_id="rule:macro:toc",
                source_pattern_id="macro:toc",
                source_description="TOC",
                notion_block_type="table_of_contents",
                mapping_description="Map TOC",
                example_input="<x/>",
                example_output={"type": "table_of_contents"},
                confidence="maybe",
            )


class TestProposerOutput:
    def test_valid_output(self) -> None:
        output = ProposerOutput(
            source_patterns_file="output/patterns.json",
            rules=[
                ProposedRule(
                    rule_id="rule:macro:toc",
                    source_pattern_id="macro:toc",
                    source_description="TOC macro",
                    notion_block_type="table_of_contents",
                    mapping_description="Map TOC",
                    example_input="<x/>",
                    example_output={"type": "table_of_contents"},
                    confidence="high",
                ),
            ],
        )
        assert len(output.rules) == 1

    def test_empty_rules_allowed(self) -> None:
        output = ProposerOutput(source_patterns_file="output/patterns.json", rules=[])
        assert len(output.rules) == 0

    def test_json_roundtrip(self) -> None:
        rule = ProposedRule(
            rule_id="rule:macro:info",
            source_pattern_id="macro:info",
            source_description="Info panel macro",
            notion_block_type="callout",
            mapping_description="Map info macro to callout with blue icon",
            example_input=(
                '<ac:structured-macro ac:name="info">'
                "<ac:rich-text-body><p>Note</p></ac:rich-text-body>"
                "</ac:structured-macro>"
            ),
            example_output={
                "type": "callout",
                "callout": {
                    "icon": {"emoji": "\u2139\ufe0f"},
                    "rich_text": [{"text": {"content": "Note"}}],
                },
            },
            confidence="medium",
        )
        output = ProposerOutput(source_patterns_file="output/patterns.json", rules=[rule])
        json_str = output.model_dump_json(indent=2)
        parsed = ProposerOutput.model_validate_json(json_str)
        assert parsed == output


# --- FinalRule / FinalRuleset ---


def _make_proposed_rule(**overrides: object) -> ProposedRule:
    defaults = dict(
        rule_id="rule:macro:toc",
        source_pattern_id="macro:toc",
        source_description="TOC macro",
        notion_block_type="table_of_contents",
        mapping_description="Map TOC",
        example_input="<x/>",
        example_output={"type": "table_of_contents"},
        confidence="high",
    )
    return ProposedRule(**{**defaults, **overrides})  # type: ignore[arg-type]


class TestFinalRule:
    def test_from_proposed_rule(self) -> None:
        proposed = _make_proposed_rule()
        rule = FinalRule.from_proposed(proposed)
        assert rule.rule_id == proposed.rule_id
        assert rule.notion_block_type == proposed.notion_block_type
        assert rule.enabled is True

    def test_disabled_rule(self) -> None:
        proposed = _make_proposed_rule()
        rule = FinalRule.from_proposed(proposed, enabled=False)
        assert rule.enabled is False

    def test_preserves_all_fields(self) -> None:
        proposed = _make_proposed_rule(confidence="low")
        rule = FinalRule.from_proposed(proposed)
        assert rule.confidence == "low"
        assert rule.source_pattern_id == proposed.source_pattern_id
        assert rule.mapping_description == proposed.mapping_description
        assert rule.example_input == proposed.example_input
        assert rule.example_output == proposed.example_output


class TestFinalRuleset:
    def test_from_proposer_output(self) -> None:
        proposer = ProposerOutput(
            source_patterns_file="output/patterns.json",
            rules=[_make_proposed_rule(), _make_proposed_rule(rule_id="rule:macro:jira")],
        )
        ruleset = FinalRuleset.from_proposer_output(proposer)
        assert len(ruleset.rules) == 2
        assert ruleset.source == "output/patterns.json"
        assert all(r.enabled for r in ruleset.rules)

    def test_empty_rules_allowed(self) -> None:
        ruleset = FinalRuleset(source="output/patterns.json", rules=[])
        assert len(ruleset.rules) == 0

    def test_enabled_rules_property(self) -> None:
        r1 = FinalRule.from_proposed(_make_proposed_rule())
        r2 = FinalRule.from_proposed(
            _make_proposed_rule(rule_id="rule:macro:jira"), enabled=False
        )
        ruleset = FinalRuleset(source="f.json", rules=[r1, r2])
        assert len(ruleset.enabled_rules) == 1
        assert ruleset.enabled_rules[0].rule_id == "rule:macro:toc"

    def test_json_roundtrip(self) -> None:
        proposer = ProposerOutput(
            source_patterns_file="output/patterns.json",
            rules=[_make_proposed_rule()],
        )
        ruleset = FinalRuleset.from_proposer_output(proposer)
        json_str = ruleset.model_dump_json(indent=2)
        parsed = FinalRuleset.model_validate_json(json_str)
        assert parsed == ruleset
