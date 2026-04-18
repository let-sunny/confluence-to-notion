"""Pydantic models for the resolution store and unresolved items.

The resolution store persists facts discovered during conversion — JIRA server URLs,
custom macro mappings, page ID lookups — so they're not re-asked on subsequent runs.
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

NotionPropertyType = Literal["title", "rich_text", "select", "date", "people", "url"]


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

    kind: Literal["macro", "jira_server", "page_link", "synced_block", "table"] = Field(
        description=(
            "Category of the unresolved element "
            "(macro, jira_server, page_link, synced_block, or table)"
        ),
    )
    identifier: str = Field(
        description="Key identifier (macro name, server name, page title, table id)",
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


class TableRule(BaseModel):
    """Rule entry describing how a table (identified by its header signature) maps to Notion.

    When ``is_database`` is True, the converter will later emit a ``child_database`` reference
    instead of a layout table. ``column_types`` maps each (normalized) header to a Notion
    property type, and ``title_column`` picks which column becomes the database's title.
    """

    is_database: bool = Field(
        description="Whether tables matching this signature should become a Notion database",
    )
    title_column: str | None = Field(
        default=None,
        description="Column name to use as the Notion database's title property",
    )
    column_types: dict[str, NotionPropertyType] | None = Field(
        default=None,
        description="Map of column name → Notion property type",
    )


class TableRuleSet(BaseModel):
    """Root model for output/rules/table-rules.json.

    Keys are normalized header signatures (columns joined by '|', lowercased and trimmed,
    order preserved). A rule may assert ``title_column`` — it must appear in the signature's
    column list.
    """

    rules: dict[str, TableRule] = Field(
        default_factory=dict,
        description="Map of normalized header signature → table rule",
    )

    @model_validator(mode="after")
    def _validate_rules(self) -> "TableRuleSet":
        for key, rule in self.rules.items():
            if not key:
                raise ValueError("TableRuleSet rule key must be a non-empty signature")
            if rule.title_column is not None:
                columns = key.split("|")
                if rule.title_column not in columns:
                    raise ValueError(
                        f"title_column {rule.title_column!r} not in signature columns "
                        f"{columns!r}"
                    )
        return self
