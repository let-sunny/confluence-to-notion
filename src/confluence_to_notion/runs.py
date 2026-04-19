"""Run-directory utilities: status/source schemas, slug + dir helpers, report renderer.

This module owns the per-run artifact layout under ``output/runs/<slug>/``. It is kept
free of Confluence/Notion client coupling so CLI subcommands can wire it in without
pulling network dependencies.
"""

import json
import re
import shutil
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal
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
    rules_source: Literal["reused", "regenerated", "generated"] | None = Field(
        default=None,
        description=(
            "How output/rules.json was provisioned for this run: 'reused' (existing "
            "rules.json), 'regenerated' (--rediscover over an existing file), "
            "'generated' (first-time discover because rules.json was absent)."
        ),
    )
    rules_generated_at: str | None = Field(
        default=None,
        description=(
            "ISO-8601 UTC timestamp of the last successful rules.json generation, "
            "sourced from output/rules.json.meta.json when present."
        ),
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


StepName = Literal["fetch", "discover", "convert", "migrate"]


def start_run(
    base: Path,
    url: str,
    source_type: str,
    *,
    root_id: str | None = None,
    notion_target: dict[str, Any] | None = None,
) -> tuple[Path, SourceInfo]:
    """Allocate a new run directory under ``base/runs/`` and seed its artifacts.

    Creates ``base/runs/<slug>/`` (with ``-2``/``-3``/... on collision), writes
    the initial ``source.json`` describing where the run came from, and writes a
    fresh ``status.json`` with every step at ``pending``. Returns the run dir
    path and the ``SourceInfo`` that was persisted.
    """
    slug = slug_for_url(url)
    run_dir = init_run_dir(base, slug)
    source = SourceInfo(
        url=url,
        type=source_type,
        root_id=root_id,
        notion_target=notion_target,
    )
    (run_dir / "source.json").write_text(
        source.model_dump_json(indent=2), encoding="utf-8"
    )
    write_status(run_dir, RunStatus())
    return run_dir, source


def update_step(
    run_dir: Path,
    step: StepName,
    status: StepStatus | str,
    *,
    count: int | None = None,
    warnings: int | None = None,
) -> None:
    """Mutate a single step in ``run_dir/status.json`` and persist the result.

    Reads the existing status, replaces only ``step`` with a fresh ``StepRecord``
    whose ``at`` is ``datetime.now(UTC).isoformat()``, and writes it back. Other
    steps are preserved. Accepts either a ``StepStatus`` or the plain string
    value so callers don't need to import the enum.
    """
    current = read_status(run_dir)
    record = StepRecord(
        status=StepStatus(status) if not isinstance(status, StepStatus) else status,
        at=datetime.now(UTC).isoformat(),
        count=count,
        warnings=warnings,
    )
    updated = current.model_copy(update={step: record})
    write_status(run_dir, updated)


def finalize_run(run_dir: Path, *, rules_summary: str | None = None) -> None:
    """Render ``run_dir/report.md`` from ``source.json`` + ``status.json``.

    When ``rules_summary`` is provided, a ``## Rules usage`` section is appended
    to the rendered report; passing ``None`` (the default) omits the section.
    """
    source = SourceInfo.model_validate_json(
        (run_dir / "source.json").read_text(encoding="utf-8")
    )
    status = read_status(run_dir)
    (run_dir / "report.md").write_text(
        render_report(source, status, rules_summary=rules_summary),
        encoding="utf-8",
    )


def format_rules_summary(used_rules: dict[str, int]) -> str | None:
    """Render ``used_rules`` as sorted ``- <rule_id>: <count>`` lines.

    Returns ``None`` when ``used_rules`` is empty so callers can pass the result
    straight into ``finalize_run(..., rules_summary=...)`` without conditionals.
    """
    if not used_rules:
        return None
    return "\n".join(f"- {rule_id}: {count}" for rule_id, count in sorted(used_rules.items()))


_RULES_META_NAME = "rules.json.meta.json"
_RULES_BACKUP_PREFIX = "rules.json.prev-"


def read_rules_meta(output_dir: Path) -> str | None:
    """Return the ``generated_at`` timestamp from ``output_dir/rules.json.meta.json``.

    Returns ``None`` when the sidecar is missing so callers can treat an unknown
    generation time uniformly.
    """
    sidecar = output_dir / _RULES_META_NAME
    if not sidecar.is_file():
        return None
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    value = payload.get("generated_at")
    return value if isinstance(value, str) else None


def write_rules_meta(output_dir: Path, generated_at: str) -> None:
    """Persist ``{'generated_at': generated_at}`` to ``output_dir/rules.json.meta.json``."""
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / _RULES_META_NAME).write_text(
        json.dumps({"generated_at": generated_at}, indent=2) + "\n",
        encoding="utf-8",
    )


def backup_rules_json(output_dir: Path) -> Path | None:
    """Copy ``output_dir/rules.json`` to ``rules.json.prev-<iso-utc-ts>`` and rotate.

    Keeps exactly one backup: any older ``rules.json.prev-*`` siblings are deleted
    after the new copy is written. Returns the backup path, or ``None`` when
    ``rules.json`` is absent (noop).
    """
    rules_path = output_dir / "rules.json"
    if not rules_path.is_file():
        return None
    timestamp = datetime.now(UTC).isoformat()
    backup = output_dir / f"{_RULES_BACKUP_PREFIX}{timestamp}"
    shutil.copy2(rules_path, backup)
    for sibling in output_dir.glob(f"{_RULES_BACKUP_PREFIX}*"):
        if sibling != backup:
            sibling.unlink()
    return backup


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
    if source.rules_source is not None:
        lines.append("")
        lines.append("## Rules source")
        lines.append(f"- source: {source.rules_source}")
        if source.rules_generated_at is not None:
            lines.append(f"- last generated_at: {source.rules_generated_at}")
    if rules_summary is not None:
        lines.append("")
        lines.append("## Rules usage")
        lines.append(rules_summary)
    lines.append("")
    return "\n".join(lines)
