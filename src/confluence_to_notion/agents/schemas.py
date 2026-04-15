"""Pydantic schemas defining the file-based contracts between agents.

These schemas are the source of truth for agent I/O. Each agent reads and writes
JSON files that must validate against these models.
"""

from typing import Any, Literal

from pydantic import BaseModel, Field

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
