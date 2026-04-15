"""Pydantic schemas defining the file-based contracts between agents.

These schemas are the source of truth for agent I/O. Each agent reads and writes
JSON files that must validate against these models.
"""

from typing import Any, Literal

from pydantic import BaseModel, Field

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
