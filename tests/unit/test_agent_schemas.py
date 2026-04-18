"""Unit tests for agent I/O schemas."""


import pytest
from pydantic import ValidationError

from confluence_to_notion.agents.schemas import (
    ConfluenceSource,
    DevDecision,
    DevImplementLog,
    DevPlan,
    DevReview,
    DevReviewIssue,
    DevStepRecord,
    DevTask,
    DiscoveryOutput,
    DiscoveryPattern,
    EvalMatchResult,
    EvalReport,
    FinalRule,
    FinalRuleset,
    PipelineState,
    ProposedRule,
    ProposerOutput,
    ScoutOutput,
    SemanticCoverage,
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


# --- DevTask / DevPlan ---


def _make_dev_task(**overrides: object) -> dict[str, object]:
    defaults: dict[str, object] = {
        "task_id": "task:1",
        "title": "Add DevPlan schema",
        "description": "Define Pydantic model for development plan",
        "affected_files": ["src/confluence_to_notion/agents/schemas.py"],
        "depends_on": [],
        "test_files": ["tests/unit/test_agent_schemas.py"],
    }
    return {**defaults, **overrides}


class TestDevTask:
    def test_minimal_task(self) -> None:
        t = DevTask(**_make_dev_task())  # type: ignore[arg-type]
        assert t.task_id == "task:1"
        assert t.title == "Add DevPlan schema"
        assert len(t.affected_files) == 1
        assert t.depends_on == []

    def test_task_with_dependencies(self) -> None:
        t = DevTask(**_make_dev_task(depends_on=["task:0"]))  # type: ignore[arg-type]
        assert t.depends_on == ["task:0"]

    def test_affected_files_required(self) -> None:
        with pytest.raises(ValidationError, match="affected_files"):
            DevTask(**_make_dev_task(affected_files=[]))  # type: ignore[arg-type]


class TestDevPlan:
    def test_valid_plan(self) -> None:
        plan = DevPlan(
            issue_number=10,
            issue_title="feat: develop pipeline",
            tasks=[DevTask(**_make_dev_task())],  # type: ignore[arg-type]
        )
        assert plan.issue_number == 10
        assert len(plan.tasks) == 1

    def test_requires_at_least_one_task(self) -> None:
        with pytest.raises(ValidationError, match="tasks"):
            DevPlan(issue_number=10, issue_title="test", tasks=[])

    def test_issue_number_must_be_positive(self) -> None:
        with pytest.raises(ValidationError, match="issue_number"):
            DevPlan(
                issue_number=0,
                issue_title="test",
                tasks=[DevTask(**_make_dev_task())],  # type: ignore[arg-type]
            )

    def test_split_defaults_false(self) -> None:
        plan = DevPlan(
            issue_number=10,
            issue_title="feat: test",
            tasks=[DevTask(**_make_dev_task())],  # type: ignore[arg-type]
        )
        assert plan.split is False
        assert plan.remaining_description is None

    def test_split_plan_with_remaining(self) -> None:
        plan = DevPlan(
            issue_number=10,
            issue_title="feat: big feature",
            split=True,
            remaining_description="Implement review agent and fix agent",
            tasks=[DevTask(**_make_dev_task())],  # type: ignore[arg-type]
        )
        assert plan.split is True
        assert plan.remaining_description == "Implement review agent and fix agent"

    def test_json_roundtrip(self) -> None:
        plan = DevPlan(
            issue_number=10,
            issue_title="feat: develop pipeline",
            split=True,
            remaining_description="Remaining work for next PR",
            tasks=[
                DevTask(**_make_dev_task()),  # type: ignore[arg-type]
                DevTask(**_make_dev_task(task_id="task:2", depends_on=["task:1"])),  # type: ignore[arg-type]
            ],
        )
        json_str = plan.model_dump_json(indent=2)
        parsed = DevPlan.model_validate_json(json_str)
        assert parsed == plan


# --- DevReviewIssue / DevReview ---


# --- DevImplementLog (why-chain) ---


class TestDevDecision:
    def test_valid_decision(self) -> None:
        d = DevDecision(
            task_id="task:1",
            description="Used stdlib xml instead of lxml",
            reason="CLAUDE.md says no lxml dependency",
        )
        assert d.task_id == "task:1"
        assert d.alternatives is None

    def test_decision_with_alternatives(self) -> None:
        d = DevDecision(
            task_id="task:2",
            description="Chose callout block for info macro",
            reason="Semantic match is better than quote block",
            alternatives=["quote", "paragraph with emoji"],
        )
        assert len(d.alternatives) == 2


class TestDevImplementLog:
    def test_valid_log(self) -> None:
        log = DevImplementLog(
            plan_file="output/dev/plan.json",
            decisions=[
                DevDecision(
                    task_id="task:1",
                    description="Used async httpx",
                    reason="Project convention",
                ),
            ],
            known_risks=["No test for concurrent access"],
        )
        assert len(log.decisions) == 1
        assert len(log.known_risks) == 1

    def test_empty_decisions_allowed(self) -> None:
        log = DevImplementLog(
            plan_file="output/dev/plan.json",
            decisions=[],
            known_risks=[],
        )
        assert len(log.decisions) == 0

    def test_json_roundtrip(self) -> None:
        log = DevImplementLog(
            plan_file="output/dev/plan.json",
            decisions=[
                DevDecision(
                    task_id="task:1",
                    description="Chose X",
                    reason="Because Y",
                    alternatives=["Z"],
                ),
            ],
            known_risks=["Edge case not covered"],
        )
        json_str = log.model_dump_json(indent=2)
        parsed = DevImplementLog.model_validate_json(json_str)
        assert parsed == log


# --- DevReviewIssue / DevReview (with intentConflict) ---


def _make_review_issue(**overrides: object) -> dict[str, object]:
    defaults: dict[str, object] = {
        "severity": "warning",
        "file": "src/confluence_to_notion/agents/schemas.py",
        "description": "Missing docstring on public method",
        "suggestion": "Add a one-line docstring",
    }
    return {**defaults, **overrides}


class TestDevReviewIssue:
    def test_valid_issue(self) -> None:
        issue = DevReviewIssue(**_make_review_issue())  # type: ignore[arg-type]
        assert issue.severity == "warning"
        assert issue.line is None

    def test_issue_with_line(self) -> None:
        issue = DevReviewIssue(**_make_review_issue(line=42))  # type: ignore[arg-type]
        assert issue.line == 42

    def test_invalid_severity(self) -> None:
        with pytest.raises(ValidationError, match="severity"):
            DevReviewIssue(**_make_review_issue(severity="critical"))  # type: ignore[arg-type]

    def test_suggestion_optional(self) -> None:
        issue = DevReviewIssue(**_make_review_issue(suggestion=None))  # type: ignore[arg-type]
        assert issue.suggestion is None

    def test_intent_conflict_default_false(self) -> None:
        issue = DevReviewIssue(**_make_review_issue())  # type: ignore[arg-type]
        assert issue.intent_conflict is False

    def test_intent_conflict_flagged(self) -> None:
        issue = DevReviewIssue(
            **_make_review_issue(  # type: ignore[arg-type]
                intent_conflict=True,
                implement_intent="Used stdlib xml per CLAUDE.md constraint",
            )
        )
        assert issue.intent_conflict is True
        assert issue.implement_intent == "Used stdlib xml per CLAUDE.md constraint"


class TestDevReview:
    def test_valid_review(self) -> None:
        review = DevReview(
            plan_file="output/dev/plan.json",
            files_reviewed=["src/confluence_to_notion/agents/schemas.py"],
            issues=[DevReviewIssue(**_make_review_issue())],  # type: ignore[arg-type]
            approved=False,
        )
        assert not review.approved
        assert len(review.issues) == 1

    def test_approved_with_no_issues(self) -> None:
        review = DevReview(
            plan_file="output/dev/plan.json",
            files_reviewed=["schemas.py"],
            issues=[],
            approved=True,
        )
        assert review.approved
        assert len(review.issues) == 0

    def test_files_reviewed_required(self) -> None:
        with pytest.raises(ValidationError, match="files_reviewed"):
            DevReview(
                plan_file="output/dev/plan.json",
                files_reviewed=[],
                issues=[],
                approved=True,
            )

    def test_json_roundtrip(self) -> None:
        review = DevReview(
            plan_file="output/dev/plan.json",
            files_reviewed=["schemas.py", "converter.py"],
            issues=[
                DevReviewIssue(**_make_review_issue()),  # type: ignore[arg-type]
                DevReviewIssue(**_make_review_issue(severity="error", line=10)),  # type: ignore[arg-type]
            ],
            approved=False,
        )
        json_str = review.model_dump_json(indent=2)
        parsed = DevReview.model_validate_json(json_str)
        assert parsed == review


# --- DevStepRecord / PipelineState (index.json) ---


class TestDevStepRecord:
    def test_completed_step(self) -> None:
        step = DevStepRecord(
            step=1,
            name="dev-planner",
            status="completed",
            started_at="2026-04-16T02:00:00Z",
            completed_at="2026-04-16T02:01:30Z",
            duration_ms=90000,
            summary="Planned 4 tasks",
        )
        assert step.status == "completed"
        assert step.error is None

    def test_failed_step(self) -> None:
        step = DevStepRecord(
            step=3,
            name="test",
            status="failed",
            started_at="2026-04-16T02:05:00Z",
            completed_at="2026-04-16T02:05:10Z",
            duration_ms=10000,
            error="pytest: 2 failures",
        )
        assert step.status == "failed"
        assert step.error == "pytest: 2 failures"

    def test_invalid_status(self) -> None:
        with pytest.raises(ValidationError, match="status"):
            DevStepRecord(
                step=1, name="plan", status="unknown",
                started_at="2026-04-16T02:00:00Z",
            )


class TestPipelineState:
    def test_valid_state(self) -> None:
        state = PipelineState(
            issue_number=10,
            branch="feat/issue-10",
            steps=[
                DevStepRecord(
                    step=1, name="dev-planner", status="completed",
                    started_at="2026-04-16T02:00:00Z",
                    completed_at="2026-04-16T02:01:30Z",
                    duration_ms=90000,
                    summary="4 tasks",
                ),
            ],
            circuit_state="CLOSED",
        )
        assert state.circuit_state == "CLOSED"
        assert len(state.steps) == 1

    def test_retries_tracked(self) -> None:
        state = PipelineState(
            issue_number=10,
            branch="feat/issue-10",
            steps=[],
            circuit_state="OPEN",
            fix_retries=2,
            error_counts=[5, 3, 3],
        )
        assert state.fix_retries == 2
        assert state.error_counts == [5, 3, 3]

    def test_json_roundtrip(self) -> None:
        state = PipelineState(
            issue_number=10,
            branch="feat/issue-10",
            steps=[
                DevStepRecord(
                    step=1, name="plan", status="completed",
                    started_at="2026-04-16T02:00:00Z",
                    duration_ms=5000,
                ),
                DevStepRecord(
                    step=2, name="implement", status="running",
                    started_at="2026-04-16T02:01:00Z",
                ),
            ],
            circuit_state="CLOSED",
            fix_retries=0,
            error_counts=[],
        )
        json_str = state.model_dump_json(indent=2)
        parsed = PipelineState.model_validate_json(json_str)
        assert parsed == state


# --- ConfluenceSource / ScoutOutput ---


class TestConfluenceSource:
    def test_valid_source(self) -> None:
        src = ConfluenceSource(
            wiki_url="https://cwiki.apache.org/confluence",
            space_key="KAFKA",
            macro_density=0.75,
            sample_macros=["toc", "code", "jira"],
            page_count=150,
            accessible=True,
        )
        assert src.wiki_url == "https://cwiki.apache.org/confluence"
        assert src.space_key == "KAFKA"
        assert src.macro_density == 0.75
        assert len(src.sample_macros) == 3
        assert src.page_count == 150
        assert src.accessible is True

    def test_required_fields(self) -> None:
        with pytest.raises(ValidationError):
            ConfluenceSource()  # type: ignore[call-arg]

    def test_macro_density_must_be_non_negative(self) -> None:
        with pytest.raises(ValidationError, match="macro_density"):
            ConfluenceSource(
                wiki_url="https://example.com",
                space_key="TEST",
                macro_density=-0.1,
                sample_macros=[],
                page_count=10,
                accessible=True,
            )

    def test_macro_density_must_not_exceed_one(self) -> None:
        with pytest.raises(ValidationError, match="macro_density"):
            ConfluenceSource(
                wiki_url="https://example.com",
                space_key="TEST",
                macro_density=1.5,
                sample_macros=[],
                page_count=10,
                accessible=True,
            )

    def test_macro_density_zero_allowed(self) -> None:
        src = ConfluenceSource(
            wiki_url="https://example.com",
            space_key="TEST",
            macro_density=0.0,
            sample_macros=[],
            page_count=10,
            accessible=True,
        )
        assert src.macro_density == 0.0

    def test_page_count_must_be_non_negative(self) -> None:
        with pytest.raises(ValidationError, match="page_count"):
            ConfluenceSource(
                wiki_url="https://example.com",
                space_key="TEST",
                macro_density=0.5,
                sample_macros=[],
                page_count=-1,
                accessible=True,
            )

    def test_page_count_zero_allowed(self) -> None:
        src = ConfluenceSource(
            wiki_url="https://example.com",
            space_key="TEST",
            macro_density=0.0,
            sample_macros=[],
            page_count=0,
            accessible=True,
        )
        assert src.page_count == 0

    def test_accessible_bool(self) -> None:
        src = ConfluenceSource(
            wiki_url="https://example.com",
            space_key="TEST",
            macro_density=0.0,
            sample_macros=[],
            page_count=0,
            accessible=False,
        )
        assert src.accessible is False

    def test_fetched_at_defaults_to_none(self) -> None:
        src = ConfluenceSource(
            wiki_url="https://example.com",
            space_key="TEST",
            macro_density=0.5,
            sample_macros=["toc"],
            page_count=10,
            accessible=True,
        )
        assert src.fetched_at is None

    def test_fetched_at_accepts_iso_timestamp(self) -> None:
        src = ConfluenceSource(
            wiki_url="https://example.com",
            space_key="TEST",
            macro_density=0.5,
            sample_macros=["toc"],
            page_count=10,
            accessible=True,
            fetched_at="2026-04-16T12:00:00Z",
        )
        assert src.fetched_at == "2026-04-16T12:00:00Z"


class TestScoutOutput:
    def test_valid_output(self) -> None:
        output = ScoutOutput(
            sources=[
                ConfluenceSource(
                    wiki_url="https://cwiki.apache.org/confluence",
                    space_key="KAFKA",
                    macro_density=0.8,
                    sample_macros=["toc", "code"],
                    page_count=200,
                    accessible=True,
                ),
            ],
        )
        assert len(output.sources) == 1

    def test_empty_sources_allowed(self) -> None:
        output = ScoutOutput(sources=[])
        assert len(output.sources) == 0

    def test_json_roundtrip(self) -> None:
        output = ScoutOutput(
            sources=[
                ConfluenceSource(
                    wiki_url="https://cwiki.apache.org/confluence",
                    space_key="KAFKA",
                    macro_density=0.8,
                    sample_macros=["toc", "code"],
                    page_count=200,
                    accessible=True,
                ),
                ConfluenceSource(
                    wiki_url="https://wiki.example.com",
                    space_key="DOCS",
                    macro_density=0.0,
                    sample_macros=[],
                    page_count=50,
                    accessible=False,
                ),
            ],
        )
        json_str = output.model_dump_json(indent=2)
        parsed = ScoutOutput.model_validate_json(json_str)
        assert parsed == output

    def test_json_roundtrip_preserves_fetched_at(self) -> None:
        output = ScoutOutput(
            sources=[
                ConfluenceSource(
                    wiki_url="https://cwiki.apache.org/confluence",
                    space_key="KAFKA",
                    macro_density=0.8,
                    sample_macros=["toc", "code"],
                    page_count=200,
                    accessible=True,
                    fetched_at="2026-04-16T12:00:00Z",
                ),
                ConfluenceSource(
                    wiki_url="https://wiki.example.com",
                    space_key="DOCS",
                    macro_density=0.0,
                    sample_macros=[],
                    page_count=50,
                    accessible=False,
                ),
            ],
        )
        json_str = output.model_dump_json(indent=2)
        parsed = ScoutOutput.model_validate_json(json_str)
        assert parsed == output
        assert parsed.sources[0].fetched_at == "2026-04-16T12:00:00Z"
        assert parsed.sources[1].fetched_at is None


# --- SemanticCoverage ---


def _make_eval_match_result(agent_name: str = "pattern-discovery") -> EvalMatchResult:
    return EvalMatchResult(
        agent_name=agent_name,
        status="pass",
        expected_ids=["a"],
        actual_ids=["a"],
        missing_ids=[],
        extra_ids=[],
        recall=1.0,
        precision=1.0,
        score=1.0,
    )


class TestSemanticCoverage:
    def test_normal_case(self) -> None:
        cov = SemanticCoverage(
            pages_analyzed=3,
            sample_elements=["macro:info", "macro:toc", "element:table"],
            covered_elements=["macro:info", "macro:toc"],
            coverage_ratio=2 / 3,
        )
        assert cov.pages_analyzed == 3
        assert cov.coverage_ratio == pytest.approx(2 / 3)

    def test_full_coverage(self) -> None:
        cov = SemanticCoverage(
            pages_analyzed=1,
            sample_elements=["macro:toc"],
            covered_elements=["macro:toc"],
            coverage_ratio=1.0,
        )
        assert cov.coverage_ratio == 1.0

    def test_empty_sample_elements_gives_ratio_one(self) -> None:
        cov = SemanticCoverage(
            pages_analyzed=1,
            sample_elements=[],
            covered_elements=[],
            coverage_ratio=1.0,
        )
        assert cov.coverage_ratio == 1.0

    def test_covered_must_be_subset_of_sample(self) -> None:
        with pytest.raises(ValidationError, match="covered_elements"):
            SemanticCoverage(
                pages_analyzed=1,
                sample_elements=["macro:info"],
                covered_elements=["macro:info", "macro:code"],
                coverage_ratio=1.0,
            )

    def test_coverage_ratio_must_match_derived(self) -> None:
        with pytest.raises(ValidationError, match="coverage_ratio"):
            SemanticCoverage(
                pages_analyzed=1,
                sample_elements=["macro:info", "macro:code"],
                covered_elements=["macro:info"],
                coverage_ratio=0.9,
            )

    def test_pages_analyzed_must_be_positive(self) -> None:
        with pytest.raises(ValidationError, match="pages_analyzed"):
            SemanticCoverage(
                pages_analyzed=0,
                sample_elements=[],
                covered_elements=[],
                coverage_ratio=1.0,
            )

    def test_coverage_ratio_bounds(self) -> None:
        with pytest.raises(ValidationError, match="coverage_ratio"):
            SemanticCoverage(
                pages_analyzed=1,
                sample_elements=[],
                covered_elements=[],
                coverage_ratio=1.5,
            )

    def test_json_roundtrip(self) -> None:
        cov = SemanticCoverage(
            pages_analyzed=5,
            sample_elements=["macro:info", "element:table"],
            covered_elements=["macro:info"],
            coverage_ratio=0.5,
        )
        json_str = cov.model_dump_json(indent=2)
        parsed = SemanticCoverage.model_validate_json(json_str)
        assert parsed == cov


class TestEvalReportSemanticCoverageField:
    def test_semantic_coverage_defaults_to_none(self) -> None:
        report = EvalReport(
            timestamp="2026-04-18T00:00:00Z",
            results=[_make_eval_match_result()],
            overall_pass=True,
        )
        assert report.semantic_coverage is None

    def test_semantic_coverage_accepted(self) -> None:
        cov = SemanticCoverage(
            pages_analyzed=2,
            sample_elements=["macro:info"],
            covered_elements=["macro:info"],
            coverage_ratio=1.0,
        )
        report = EvalReport(
            timestamp="2026-04-18T00:00:00Z",
            results=[_make_eval_match_result()],
            overall_pass=True,
            semantic_coverage=cov,
        )
        assert report.semantic_coverage == cov

    def test_legacy_report_json_still_parses(self) -> None:
        legacy_json = (
            '{"timestamp": "2026-04-18T00:00:00Z",'
            ' "prompt_changed": false,'
            ' "results": [],'
            ' "overall_pass": true}'
        )
        report = EvalReport.model_validate_json(legacy_json)
        assert report.semantic_coverage is None
