"""Pydantic schemas defining the file-based contracts between agents.

These schemas are the source of truth for agent I/O. Each agent reads and writes
JSON files that must validate against these models.
"""

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

# --- Development Pipeline Schemas ---


class DevTask(BaseModel):
    """A single task in a development plan."""

    task_id: str = Field(description="Unique ID, e.g. 'task:1'")
    title: str = Field(description="Short imperative title")
    description: str = Field(description="What needs to be done")
    affected_files: list[str] = Field(
        min_length=1,
        description="Files to create or modify",
    )
    depends_on: list[str] = Field(
        default_factory=list,
        description="Task IDs this depends on",
    )
    test_files: list[str] = Field(
        default_factory=list,
        description="Test files to create or modify",
    )


class DevPlan(BaseModel):
    """Output of the dev-planner agent -> output/dev/plan.json."""

    issue_number: int = Field(gt=0, description="GitHub issue number")
    issue_title: str = Field(description="Issue title")
    tasks: list[DevTask] = Field(
        min_length=1,
        description="Ordered list of tasks to implement (max 5)",
    )
    split: bool = Field(
        default=False,
        description="True if the issue was too big and this plan covers only a slice",
    )
    remaining_description: str | None = Field(
        default=None,
        description="What's left for the next run, used to create a follow-up issue",
    )


class DevDecision(BaseModel):
    """A decision made by the implementer, explaining why a particular approach was chosen."""

    task_id: str = Field(description="Which task this decision relates to")
    description: str = Field(description="What was decided")
    reason: str = Field(description="Why this approach was chosen")
    alternatives: list[str] | None = Field(
        default=None,
        description="Other approaches that were considered but rejected",
    )


class DevImplementLog(BaseModel):
    """Output of the dev-implementer agent -> output/dev/implement-log.json.

    Captures the 'why' behind implementation choices so the reviewer
    can distinguish intentional decisions from mistakes.
    """

    plan_file: str = Field(description="Path to the plan that was implemented")
    decisions: list[DevDecision] = Field(
        default_factory=list,
        description="Key decisions made during implementation",
    )
    known_risks: list[str] = Field(
        default_factory=list,
        description="Known risks or limitations the implementer is aware of",
    )


class DevReviewIssue(BaseModel):
    """A single issue found during code review."""

    severity: Literal["error", "warning", "suggestion"] = Field(
        description="Issue severity",
    )
    file: str = Field(description="File path where the issue was found")
    line: int | None = Field(default=None, description="Line number, if applicable")
    description: str = Field(description="What the issue is")
    suggestion: str | None = Field(default=None, description="How to fix it")
    intent_conflict: bool = Field(
        default=False,
        description="True if this finding conflicts with an implementer's stated decision",
    )
    implement_intent: str | None = Field(
        default=None,
        description="The implementer's stated reason, if this is an intent conflict",
    )


class DevReview(BaseModel):
    """Output of the dev-reviewer agent -> output/dev/review.json."""

    plan_file: str = Field(description="Path to the plan file that was reviewed against")
    files_reviewed: list[str] = Field(
        min_length=1,
        description="Files that were reviewed",
    )
    issues: list[DevReviewIssue] = Field(
        default_factory=list,
        description="Issues found during review",
    )
    approved: bool = Field(description="Whether the changes pass review")


# --- Pipeline State Tracking ---


class DevStepRecord(BaseModel):
    """A single step execution record in the pipeline."""

    step: int = Field(description="Step number (1-7)")
    name: str = Field(description="Step name, e.g. 'dev-planner'")
    status: Literal["running", "completed", "failed", "skipped"] = Field(
        description="Step execution status",
    )
    started_at: str = Field(description="ISO 8601 timestamp")
    completed_at: str | None = Field(default=None, description="ISO 8601 timestamp")
    duration_ms: int | None = Field(default=None, description="Duration in milliseconds")
    summary: str | None = Field(default=None, description="Short result description")
    error: str | None = Field(default=None, description="Error message if failed")


class PipelineState(BaseModel):
    """Full pipeline state -> output/dev/index.json.

    Tracks every step's timing, status, and the circuit breaker state.
    Replaces the old circuit.json with a comprehensive state file.
    """

    issue_number: int = Field(description="GitHub issue being processed")
    branch: str = Field(description="Git branch name")
    steps: list[DevStepRecord] = Field(default_factory=list, description="Step execution log")
    circuit_state: Literal["CLOSED", "OPEN", "HALF_OPEN"] = Field(
        default="CLOSED", description="Circuit breaker state",
    )
    fix_retries: int = Field(default=0, description="Number of fix attempts so far")
    error_counts: list[int] = Field(
        default_factory=list,
        description="Error count history across fix attempts",
    )

# --- Scout Agent Output ---


class ConfluenceSource(BaseModel):
    """A single public Confluence wiki discovered by the scout agent."""

    wiki_url: str = Field(description="Base URL of the Confluence instance")
    space_key: str = Field(description="Confluence space key")
    macro_density: float = Field(ge=0, le=1, description="Ratio of macro-rich pages in the space")
    sample_macros: list[str] = Field(
        default_factory=list,
        description="Example macro names found (e.g. 'toc', 'code', 'jira')",
    )
    page_count: int = Field(ge=0, description="Number of pages in the space")
    accessible: bool = Field(description="Whether the wiki is publicly accessible")
    fetched_at: str | None = Field(
        default=None,
        description="ISO 8601 timestamp when pages were last fetched from this source",
    )


class ScoutOutput(BaseModel):
    """Output of the confluence-scout agent → output/sources.json."""

    sources: list[ConfluenceSource] = Field(
        default_factory=list,
        description="Discovered Confluence sources",
    )


# --- Discovery Agent Output ---


class DiscoveryPattern(BaseModel):
    """A single structural pattern or Confluence macro found in sample pages."""

    pattern_id: str = Field(description="Unique ID, e.g. 'macro:toc', 'element:ac-link'")
    pattern_type: str = Field(description="Category: 'macro', 'element', 'layout', 'formatting'")
    description: str = Field(description="Human-readable description of the pattern")
    example_snippets: list[str] = Field(
        min_length=1,
        description="Raw XHTML snippets showing this pattern in context",
    )
    source_pages: list[str] = Field(
        min_length=1,
        description="Page IDs where this pattern was found",
    )
    frequency: int = Field(gt=0, description="Total occurrence count across all analyzed pages")


class DiscoveryOutput(BaseModel):
    """Output of the Pattern Discovery agent → output/patterns.json."""

    sample_dir: str = Field(description="Directory that was analyzed")
    pages_analyzed: int = Field(gt=0, description="Number of pages analyzed")
    patterns: list[DiscoveryPattern] = Field(
        default_factory=list,
        description="Discovered patterns",
    )


# --- Rule Proposer Agent Output ---


class ProposedRule(BaseModel):
    """A single Confluence→Notion mapping rule proposed by the Rule Proposer."""

    rule_id: str = Field(description="Unique ID, e.g. 'rule:macro:toc'")
    source_pattern_id: str = Field(description="References DiscoveryPattern.pattern_id")
    source_description: str = Field(description="What the source pattern looks like")
    notion_block_type: str = Field(description="Target Notion block type")
    mapping_description: str = Field(description="How to transform source → target")
    example_input: str = Field(description="Example XHTML input")
    example_output: dict[str, Any] = Field(description="Example Notion block JSON output")
    confidence: Literal["high", "medium", "low"] = Field(
        description="Confidence level of this mapping",
    )


class ProposerOutput(BaseModel):
    """Output of the Rule Proposer agent → output/proposals.json."""

    source_patterns_file: str = Field(description="Path to the patterns file that was processed")
    rules: list[ProposedRule] = Field(
        default_factory=list,
        description="Proposed mapping rules",
    )


# --- Final Ruleset (converter input contract) ---


class FinalRule(BaseModel):
    """A confirmed transformation rule ready for the deterministic converter."""

    rule_id: str
    source_pattern_id: str
    source_description: str
    notion_block_type: str
    mapping_description: str
    example_input: str
    example_output: dict[str, Any]
    confidence: Literal["high", "medium", "low"]
    enabled: bool = Field(default=True, description="Whether this rule is active")

    @classmethod
    def from_proposed(cls, proposed: ProposedRule, *, enabled: bool = True) -> "FinalRule":
        """Promote a ProposedRule to a FinalRule."""
        return cls(**proposed.model_dump(), enabled=enabled)


class FinalRuleset(BaseModel):
    """The complete set of rules fed into the deterministic converter → output/rules.json."""

    source: str = Field(description="Path to the proposals file this was derived from")
    rules: list[FinalRule] = Field(default_factory=list)

    @property
    def enabled_rules(self) -> list[FinalRule]:
        """Return only active rules."""
        return [r for r in self.rules if r.enabled]

    @classmethod
    def from_proposer_output(cls, output: ProposerOutput) -> "FinalRuleset":
        """Convert ProposerOutput directly to a FinalRuleset (2-agent shortcut)."""
        return cls(
            source=output.source_patterns_file,
            rules=[FinalRule.from_proposed(r) for r in output.rules],
        )


# --- Eval Framework Schemas ---


class EvalMatchResult(BaseModel):
    """Result of comparing actual vs expected agent output for a single agent."""

    agent_name: str = Field(description="Name of the agent being evaluated")
    status: Literal["pass", "fail", "partial"] = Field(
        description="Overall match status",
    )
    expected_ids: list[str] = Field(description="IDs expected in the output")
    actual_ids: list[str] = Field(description="IDs found in the actual output")
    missing_ids: list[str] = Field(description="Expected IDs not found in actual output")
    extra_ids: list[str] = Field(description="Actual IDs not in expected output")
    recall: float = Field(ge=0, le=1, description="Fraction of expected IDs found (0.0 to 1.0)")
    precision: float = Field(
        ge=0, le=1, description="Fraction of actual IDs that were expected (0.0 to 1.0)"
    )
    score: float = Field(ge=0, le=1, description="F1 score — harmonic mean of recall and precision")


class SemanticCoverage(BaseModel):
    """Semantic coverage of discovered patterns against sampled element kinds.

    Complements the fixture-based rule_id match: instead of asking "did we find
    the same IDs as the fixture", it asks "of the macros/elements that actually
    appear in the samples, how many are documented by at least one pattern?"
    """

    pages_analyzed: int = Field(
        gt=0,
        description="Number of sample pages the element enumeration walked",
    )
    sample_elements: list[str] = Field(
        description="Normalized element keys enumerated from samples (e.g. 'macro:info')",
    )
    covered_elements: list[str] = Field(
        description="Subset of sample_elements covered by at least one pattern",
    )
    coverage_ratio: float = Field(
        ge=0.0,
        le=1.0,
        description="|covered ∩ sample| / |sample|; 1.0 when sample is empty",
    )

    @model_validator(mode="after")
    def _validate_derived_fields(self) -> "SemanticCoverage":
        sample = set(self.sample_elements)
        covered = set(self.covered_elements)
        extra = covered - sample
        if extra:
            raise ValueError(
                f"covered_elements must be a subset of sample_elements; extras: {sorted(extra)}"
            )
        expected_ratio = len(covered) / len(sample) if sample else 1.0
        if abs(expected_ratio - self.coverage_ratio) > 1e-9:
            raise ValueError(
                f"coverage_ratio {self.coverage_ratio} does not match derived value"
                f" {expected_ratio} from sample/covered sets"
            )
        return self


_LLM_JUDGE_DIMENSIONS: tuple[str, ...] = (
    "information_preservation",
    "notion_idiom",
    "structure",
    "readability",
)


class LLMJudgeResult(BaseModel):
    """Per-page LLM-as-judge score across the 4 conversion-quality dimensions.

    Signal-only per ADR-004 — never flips ``EvalReport.overall_pass``.
    """

    page_id: str = Field(description="Confluence page ID being judged")
    scores: dict[str, int] = Field(
        description=(
            "Score per dimension (1-5). Required keys: "
            "information_preservation, notion_idiom, structure, readability."
        )
    )
    overall_comment: str = Field(description="Free-form judge commentary")
    model: str = Field(description="Anthropic model id used to score")
    cache_hit: bool = Field(description="True if loaded from cache, no API call")

    @model_validator(mode="after")
    def _validate_scores(self) -> "LLMJudgeResult":
        required = set(_LLM_JUDGE_DIMENSIONS)
        actual = set(self.scores)
        missing = required - actual
        if missing:
            raise ValueError(f"scores missing required dimensions: {sorted(missing)}")
        extra = actual - required
        if extra:
            raise ValueError(f"scores has unknown dimensions: {sorted(extra)}")
        for dim, value in self.scores.items():
            if not 1 <= value <= 5:
                raise ValueError(
                    f"scores[{dim!r}] = {value} is out of range; must be 1<=v<=5"
                )
        return self


class BaselineComparison(BaseModel):
    """Comparison of the current eval snapshot to the most recent prior snapshot.

    Signal-only per ADR-004 — regressions are reported but do not affect
    ``EvalReport.overall_pass``. CLI exit-code gating on regressions is opt-in.
    """

    previous_timestamp: str | None = Field(
        description="Timestamp of the prior snapshot, or None when this is the first run",
    )
    coverage_delta: float = Field(
        description="current.semantic_coverage.coverage_ratio - previous; 0 when no prior",
    )
    llm_judge_mean_delta: float | None = Field(
        default=None,
        description="Delta of the llm_judge grand mean; None when either side lacks llm_judge",
    )
    regressions: list[str] = Field(
        default_factory=list,
        description="Human-readable labels of metrics that crossed their threshold",
    )
    thresholds_used: dict[str, float] = Field(
        description="Thresholds used for regression detection, e.g. {'semantic_coverage': 0.05}",
    )
    is_regression: bool = Field(
        description="True when any metric crossed its threshold",
    )


class EvalReport(BaseModel):
    """Full eval report comparing agent outputs against fixtures."""

    timestamp: str = Field(description="ISO 8601 timestamp of the eval run")
    prompt_changed: bool = Field(
        default=False,
        description="Whether agent prompts changed since last commit",
    )
    results: list[EvalMatchResult] = Field(
        default_factory=list,
        description="Per-agent comparison results",
    )
    overall_pass: bool = Field(description="Whether all agents passed")
    semantic_coverage: SemanticCoverage | None = Field(
        default=None,
        description="Semantic coverage of sample elements by discovered patterns",
    )
    llm_judge: list[LLMJudgeResult] | None = Field(
        default=None,
        description=(
            "Optional per-page LLM-as-judge scores. Signal only — does not affect "
            "overall_pass."
        ),
    )
    baseline_comparison: BaselineComparison | None = Field(
        default=None,
        description="Diff vs the most recent prior snapshot; None on first run or if unavailable",
    )
