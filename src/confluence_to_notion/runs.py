"""Run-directory utilities: status/source schemas, slug + dir helpers, report renderer.

This module owns the per-run artifact layout under ``output/runs/<slug>/``. It is kept
free of Confluence/Notion client coupling so CLI subcommands can wire it in without
pulling network dependencies.
"""

import re
from enum import StrEnum
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from pydantic import BaseModel, Field


class StepStatus(StrEnum):
    """Lifecycle state of a single pipeline step within a run."""

    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    SKIPPED = "skipped"
    FAILED = "failed"


class StepRecord(BaseModel):
    """Status snapshot for one pipeline step (fetch / discover / convert / migrate)."""

    model_config = {"use_enum_values": False}

    status: StepStatus = Field(
        default=StepStatus.PENDING,
        description="Current lifecycle state for this step",
    )
    at: str | None = Field(
        default=None,
        description="ISO-8601 timestamp of the last status transition",
    )
    count: int | None = Field(
        default=None,
        description="Items processed in this step (pages fetched, blocks converted, ...)",
    )
    warnings: int | None = Field(
        default=None,
        description="Warnings or fallbacks emitted during this step",
    )


class RunStatus(BaseModel):
    """Aggregate status for a run — one StepRecord per pipeline phase."""

    fetch: StepRecord = Field(default_factory=StepRecord)
    discover: StepRecord = Field(default_factory=StepRecord)
    convert: StepRecord = Field(default_factory=StepRecord)
    migrate: StepRecord = Field(default_factory=StepRecord)


class SourceInfo(BaseModel):
    """Origin descriptor persisted to ``source.json`` on first touch of a run."""

    url: str = Field(description="Canonical source URL the run was launched from")
    type: str = Field(description="Source kind: 'page' | 'tree' | 'space' | ...")
    root_id: str | None = Field(
        default=None,
        description="Root Confluence ID when the source resolves to a page or tree root",
    )
    notion_target: dict[str, Any] | None = Field(
        default=None,
        description="Resolved Notion destination (e.g. {'page_id': '...'})",
    )


_KEBAB_RE = re.compile(r"[^a-z0-9]+")


def _kebab(value: str) -> str:
    """Lowercase ``value`` and collapse non-alphanumeric runs to a single '-'."""
    return _KEBAB_RE.sub("-", value.lower()).strip("-")


def slug_for_url(url: str) -> str:
    """Derive a run slug ``<host-prefix>-<key>`` from a Confluence URL.

    ``host-prefix`` is the leading hostname label (e.g. ``example`` for
    ``example.atlassian.net``). The key segment is picked, in priority order, from:
    a ``pageId`` query parameter, a ``/pages/<id>`` path segment, a ``/spaces/<KEY>``
    path segment, then the final non-empty path segment. The result is lowercased
    and kebab-sanitized.
    """
    parsed = urlparse(url)
    host_prefix = (parsed.hostname or "").split(".")[0].lower()

    query = parse_qs(parsed.query)
    page_id_values = query.get("pageId")
    if page_id_values:
        return f"{host_prefix}-{_kebab(page_id_values[0])}"

    segments = [s for s in parsed.path.split("/") if s]
    for i, seg in enumerate(segments):
        if seg == "pages" and i + 1 < len(segments):
            return f"{host_prefix}-{_kebab(segments[i + 1])}"
    for i, seg in enumerate(segments):
        if seg == "spaces" and i + 1 < len(segments):
            return f"{host_prefix}-{_kebab(segments[i + 1])}"

    if segments:
        return f"{host_prefix}-{_kebab(segments[-1])}"
    return host_prefix


def init_run_dir(base: Path, slug: str) -> Path:
    """Create ``base/runs/<slug>/`` (or ``-2``/``-3``/... on collision) and return it."""
    runs_root = base / "runs"
    runs_root.mkdir(parents=True, exist_ok=True)
    candidate = runs_root / slug
    suffix = 2
    while candidate.exists():
        candidate = runs_root / f"{slug}-{suffix}"
        suffix += 1
    candidate.mkdir()
    return candidate


def write_status(run_dir: Path, status: RunStatus) -> None:
    """Serialize ``status`` to ``run_dir/status.json`` (pretty-printed)."""
    (run_dir / "status.json").write_text(status.model_dump_json(indent=2), encoding="utf-8")


def read_status(run_dir: Path) -> RunStatus:
    """Parse ``run_dir/status.json`` back into a ``RunStatus``."""
    return RunStatus.model_validate_json((run_dir / "status.json").read_text(encoding="utf-8"))


_STEP_FIELDS: tuple[str, ...] = ("fetch", "discover", "convert", "migrate")


def _format_step_line(name: str, record: StepRecord) -> str:
    parts = [f"**{name}**: {record.status.value}"]
    if record.at is not None:
        parts.append(f"at {record.at}")
    if record.count is not None:
        parts.append(f"count={record.count}")
    if record.warnings is not None:
        parts.append(f"warnings={record.warnings}")
    return "- " + " · ".join(parts)


def render_report(
    source: SourceInfo,
    status: RunStatus,
    *,
    rules_summary: str | None = None,
) -> str:
    """Render a Claude-friendly Markdown summary of a run.

    Returned string starts with a heading and includes the source URL/type, the
    Notion target (when present), one bullet per pipeline step, and an optional
    rules-usage section. Caller decides whether to write it to ``run_dir/report.md``.
    """
    lines: list[str] = []
    lines.append("# Run Report")
    lines.append("")
    lines.append("## Source")
    lines.append(f"- url: {source.url}")
    lines.append(f"- type: {source.type}")
    if source.root_id is not None:
        lines.append(f"- root_id: {source.root_id}")
    if source.notion_target is not None:
        lines.append(f"- notion_target: {source.notion_target}")
    lines.append("")
    lines.append("## Steps")
    for name in _STEP_FIELDS:
        record: StepRecord = getattr(status, name)
        lines.append(_format_step_line(name, record))
    if rules_summary is not None:
        lines.append("")
        lines.append("## Rules usage")
        lines.append(rules_summary)
    lines.append("")
    return "\n".join(lines)
