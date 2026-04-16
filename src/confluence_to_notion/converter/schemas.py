"""Pydantic models for the resolution store and unresolved items.

The resolution store persists facts discovered during conversion — JIRA server URLs,
custom macro mappings, page ID lookups — so they're not re-asked on subsequent runs.
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class ResolutionEntry(BaseModel):
    """A single resolved fact stored in resolution.json."""

    resolved_by: Literal[
        "user_input", "ai_inference", "api_call", "auto_lookup", "notion_migration"
    ] = Field(
        description="How this entry was resolved",
    )
    value: dict[str, Any] = Field(
        description="The resolved value (structure depends on the entry kind)",
    )
    confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Confidence score for AI-inferred entries",
    )
    resolved_at: datetime = Field(
        default_factory=datetime.now,
        description="When this entry was resolved",
    )


class UnresolvedItem(BaseModel):
    """An element the converter couldn't handle deterministically.

    Collected during conversion and processed afterwards by the resolver.
    """

    kind: Literal["macro", "jira_server", "page_link"] = Field(
        description="Category of the unresolved element",
    )
    identifier: str = Field(
        description="Key identifier (macro name, server name, page title)",
    )
    source_page_id: str = Field(
        description="Confluence page ID where this was encountered",
    )
    context_xhtml: str | None = Field(
        default=None,
        description="Original XHTML snippet for context",
    )


class ResolutionData(BaseModel):
    """Root model for resolution.json — keyed map of resolved entries."""

    entries: dict[str, ResolutionEntry] = Field(
        default_factory=dict,
        description="Map of 'kind:identifier' → resolved entry",
    )


class ConversionResult(BaseModel):
    """Result of converting a Confluence page — blocks plus unresolved items."""

    blocks: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Notion API block dicts",
    )
    unresolved: list[UnresolvedItem] = Field(
        default_factory=list,
        description="Elements the converter couldn't handle deterministically",
    )
