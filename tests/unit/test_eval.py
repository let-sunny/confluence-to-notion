"""Unit tests for eval framework: schemas and comparator logic."""

import pytest
from pydantic import ValidationError

from confluence_to_notion.agents.schemas import (
    DiscoveryOutput,
    DiscoveryPattern,
    EvalMatchResult,
    EvalReport,
    ProposedRule,
    ProposerOutput,
)
from confluence_to_notion.eval.comparator import compare_discovery, compare_proposer

# --- Helpers ---


def _make_pattern(pattern_id: str, frequency: int = 1) -> DiscoveryPattern:
    return DiscoveryPattern(
        pattern_id=pattern_id,
        pattern_type=pattern_id.split(":")[0],
        description=f"Pattern {pattern_id}",
        example_snippets=[f"<example>{pattern_id}</example>"],
        source_pages=["page1"],
        frequency=frequency,
    )


def _make_discovery(*pattern_ids: str) -> DiscoveryOutput:
    return DiscoveryOutput(
        sample_dir="samples/",
        pages_analyzed=3,
        patterns=[_make_pattern(pid) for pid in pattern_ids],
    )


def _make_rule(rule_id: str) -> ProposedRule:
    return ProposedRule(
        rule_id=rule_id,
        source_pattern_id=rule_id.replace("rule:", ""),
        source_description=f"Source for {rule_id}",
        notion_block_type="paragraph",
        mapping_description=f"Map {rule_id}",
        example_input="<x/>",
        example_output={"type": "paragraph"},
        confidence="high",
    )


def _make_proposer(*rule_ids: str) -> ProposerOutput:
    return ProposerOutput(
        source_patterns_file="output/patterns.json",
        rules=[_make_rule(rid) for rid in rule_ids],
    )


# --- EvalMatchResult Schema ---


class TestEvalMatchResult:
    def test_valid_pass(self) -> None:
        r = EvalMatchResult(
            agent_name="pattern-discovery",
            status="pass",
            expected_ids=["a", "b"],
            actual_ids=["a", "b"],
            missing_ids=[],
            extra_ids=[],
            score=1.0,
        )
        assert r.status == "pass"
        assert r.score == 1.0

    def test_valid_fail(self) -> None:
        r = EvalMatchResult(
            agent_name="rule-proposer",
            status="fail",
            expected_ids=["a"],
            actual_ids=["b"],
            missing_ids=["a"],
            extra_ids=["b"],
            score=0.0,
        )
        assert r.status == "fail"
        assert r.score == 0.0

    def test_valid_partial(self) -> None:
        r = EvalMatchResult(
            agent_name="pattern-discovery",
            status="partial",
            expected_ids=["a", "b"],
            actual_ids=["a", "c"],
            missing_ids=["b"],
            extra_ids=["c"],
            score=0.5,
        )
        assert r.status == "partial"

    def test_invalid_status_rejected(self) -> None:
        with pytest.raises(ValidationError, match="status"):
            EvalMatchResult(
                agent_name="test",
                status="unknown",
                expected_ids=[],
                actual_ids=[],
                missing_ids=[],
                extra_ids=[],
                score=0.0,
            )

    def test_score_must_be_between_0_and_1(self) -> None:
        with pytest.raises(ValidationError, match="score"):
            EvalMatchResult(
                agent_name="test",
                status="pass",
                expected_ids=[],
                actual_ids=[],
                missing_ids=[],
                extra_ids=[],
                score=1.5,
            )
        with pytest.raises(ValidationError, match="score"):
            EvalMatchResult(
                agent_name="test",
                status="fail",
                expected_ids=[],
                actual_ids=[],
                missing_ids=[],
                extra_ids=[],
                score=-0.1,
            )

    def test_json_roundtrip(self) -> None:
        r = EvalMatchResult(
            agent_name="pattern-discovery",
            status="partial",
            expected_ids=["a", "b", "c"],
            actual_ids=["a", "b", "d"],
            missing_ids=["c"],
            extra_ids=["d"],
            score=0.67,
        )
        json_str = r.model_dump_json(indent=2)
        parsed = EvalMatchResult.model_validate_json(json_str)
        assert parsed == r


# --- EvalReport Schema ---


class TestEvalReport:
    def test_valid_report(self) -> None:
        result = EvalMatchResult(
            agent_name="pattern-discovery",
            status="pass",
            expected_ids=["a"],
            actual_ids=["a"],
            missing_ids=[],
            extra_ids=[],
            score=1.0,
        )
        report = EvalReport(
            timestamp="2026-04-16T12:00:00Z",
            prompt_changed=False,
            results=[result],
            overall_pass=True,
        )
        assert report.overall_pass is True
        assert len(report.results) == 1

    def test_overall_pass_false_when_any_fail(self) -> None:
        report = EvalReport(
            timestamp="2026-04-16T12:00:00Z",
            prompt_changed=True,
            results=[
                EvalMatchResult(
                    agent_name="pattern-discovery",
                    status="pass",
                    expected_ids=["a"],
                    actual_ids=["a"],
                    missing_ids=[],
                    extra_ids=[],
                    score=1.0,
                ),
                EvalMatchResult(
                    agent_name="rule-proposer",
                    status="fail",
                    expected_ids=["a"],
                    actual_ids=[],
                    missing_ids=["a"],
                    extra_ids=[],
                    score=0.0,
                ),
            ],
            overall_pass=False,
        )
        assert report.overall_pass is False

    def test_prompt_changed_default_false(self) -> None:
        report = EvalReport(
            timestamp="2026-04-16T12:00:00Z",
            results=[],
            overall_pass=True,
        )
        assert report.prompt_changed is False

    def test_json_roundtrip(self) -> None:
        report = EvalReport(
            timestamp="2026-04-16T12:00:00Z",
            prompt_changed=True,
            results=[
                EvalMatchResult(
                    agent_name="pattern-discovery",
                    status="partial",
                    expected_ids=["a", "b"],
                    actual_ids=["a"],
                    missing_ids=["b"],
                    extra_ids=[],
                    score=0.5,
                ),
            ],
            overall_pass=False,
        )
        json_str = report.model_dump_json(indent=2)
        parsed = EvalReport.model_validate_json(json_str)
        assert parsed == report


# --- compare_discovery ---


class TestCompareDiscovery:
    def test_all_match(self) -> None:
        expected = _make_discovery("macro:toc", "macro:code")
        actual = _make_discovery("macro:toc", "macro:code")
        result = compare_discovery(actual, expected)
        assert result.status == "pass"
        assert result.score == 1.0
        assert result.missing_ids == []
        assert result.extra_ids == []
        assert result.agent_name == "pattern-discovery"

    def test_partial_match(self) -> None:
        expected = _make_discovery("macro:toc", "macro:code", "element:ac-link")
        actual = _make_discovery("macro:toc", "element:ac-link")
        result = compare_discovery(actual, expected)
        assert result.status == "partial"
        assert 0 < result.score < 1
        assert result.score == pytest.approx(2 / 3)
        assert result.missing_ids == ["macro:code"]
        assert result.extra_ids == []

    def test_no_match(self) -> None:
        expected = _make_discovery("macro:toc", "macro:code")
        actual = _make_discovery("element:ac-link", "formatting:bold")
        result = compare_discovery(actual, expected)
        assert result.status == "fail"
        assert result.score == 0.0
        assert sorted(result.missing_ids) == ["macro:code", "macro:toc"]
        assert sorted(result.extra_ids) == ["element:ac-link", "formatting:bold"]

    def test_extra_patterns_in_actual(self) -> None:
        expected = _make_discovery("macro:toc")
        actual = _make_discovery("macro:toc", "macro:code")
        result = compare_discovery(actual, expected)
        assert result.status == "pass"
        assert result.score == 1.0
        assert result.missing_ids == []
        assert result.extra_ids == ["macro:code"]


# --- compare_proposer ---


class TestCompareProposer:
    def test_all_match(self) -> None:
        expected = _make_proposer("rule:macro:toc", "rule:macro:code")
        actual = _make_proposer("rule:macro:toc", "rule:macro:code")
        result = compare_proposer(actual, expected)
        assert result.status == "pass"
        assert result.score == 1.0
        assert result.agent_name == "rule-proposer"

    def test_partial_match(self) -> None:
        expected = _make_proposer("rule:macro:toc", "rule:macro:code")
        actual = _make_proposer("rule:macro:toc")
        result = compare_proposer(actual, expected)
        assert result.status == "partial"
        assert result.score == pytest.approx(0.5)
        assert result.missing_ids == ["rule:macro:code"]

    def test_no_match(self) -> None:
        expected = _make_proposer("rule:macro:toc")
        actual = _make_proposer("rule:element:ac-link")
        result = compare_proposer(actual, expected)
        assert result.status == "fail"
        assert result.score == 0.0

    def test_extra_rules_in_actual(self) -> None:
        expected = _make_proposer("rule:macro:toc")
        actual = _make_proposer("rule:macro:toc", "rule:macro:code")
        result = compare_proposer(actual, expected)
        assert result.status == "pass"
        assert result.score == 1.0
        assert result.extra_ids == ["rule:macro:code"]
