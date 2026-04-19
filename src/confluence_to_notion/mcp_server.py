"""c2n MCP server — tools + c2n:// resources over stdio transport.

Exposes the run directory layout under ``output/runs/<slug>/`` and the generated
``output/rules.json`` to MCP clients (Claude Code and friends). Handlers are kept
as pure ``async`` functions so tests can drive them without wiring up an actual
FastMCP session.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path
from typing import Any

import typer
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.resources import FunctionResource
from mcp.shared.exceptions import McpError
from mcp.types import INTERNAL_ERROR, INVALID_PARAMS, ErrorData
from pydantic import AnyUrl, BaseModel

from confluence_to_notion.runs import read_status
from confluence_to_notion.url import ConfluenceUrlError, parse_confluence_url

DEFAULT_BASE = Path("output")
_C2N_SCHEME = "c2n://"
# Repo root: src/confluence_to_notion/mcp_server.py → parents[2]
_REPO_ROOT = Path(__file__).resolve().parents[2]


def _unsafe_path_segment(segment: str) -> bool:
    """True if ``segment`` must not be used as a single path component (slug, stem)."""
    return (
        not segment
        or segment in (".", "..")
        or "/" in segment
        or "\\" in segment
    )


class StatusArgs(BaseModel):
    """Arguments for the ``c2n_status`` tool."""

    slug: str | None = None


class ResolveUrlArgs(BaseModel):
    """Arguments for the ``c2n_resolve_url`` tool."""

    url: str


# --- read-only handlers ----------------------------------------------------


def _list_runs(base: Path) -> list[dict[str, Any]]:
    runs_root = base / "runs"
    if not runs_root.is_dir():
        return []
    summaries: list[dict[str, Any]] = []
    for run_dir in sorted(runs_root.iterdir()):
        if not run_dir.is_dir():
            continue
        status_path = run_dir / "status.json"
        if not status_path.is_file():
            continue
        status = read_status(run_dir)
        summaries.append(
            {
                "slug": run_dir.name,
                "status": {
                    "fetch": status.fetch.status.value,
                    "discover": status.discover.status.value,
                    "convert": status.convert.status.value,
                    "migrate": status.migrate.status.value,
                },
            }
        )
    return summaries


async def _list_runs_handler(base: Path) -> list[dict[str, Any]]:
    """Summarize every run directory under ``base/runs/`` — empty list if absent."""
    return _list_runs(base)


async def _status_handler(
    base: Path, slug: str | None
) -> dict[str, Any] | list[dict[str, Any]]:
    """Return the full ``status.json`` for ``slug``, or a summary when ``slug`` is None.

    Missing runs raise :class:`McpError` with ``INVALID_PARAMS`` so MCP clients
    surface a not-found response instead of an opaque exception.
    """
    if slug is None:
        return await _list_runs_handler(base)
    if _unsafe_path_segment(slug):
        raise McpError(
            ErrorData(code=INVALID_PARAMS, message=f"invalid run slug: {slug!r}")
        )
    runs_root = (base / "runs").resolve()
    run_dir = (base / "runs" / slug).resolve()
    try:
        if not run_dir.is_relative_to(runs_root):
            raise McpError(
                ErrorData(code=INVALID_PARAMS, message=f"run not found: {slug}")
            )
    except ValueError:
        raise McpError(
            ErrorData(code=INVALID_PARAMS, message=f"run not found: {slug}")
        ) from None
    status_path = run_dir / "status.json"
    if not status_path.is_file():
        raise McpError(
            ErrorData(code=INVALID_PARAMS, message=f"run not found: {slug}")
        )
    data: dict[str, Any] = json.loads(status_path.read_text(encoding="utf-8"))
    return data


async def _resolve_url_handler(url: str) -> dict[str, Any]:
    """Classify ``url`` via :func:`parse_confluence_url` and return it as a dict."""
    try:
        info = parse_confluence_url(url)
    except ConfluenceUrlError as exc:
        raise McpError(ErrorData(code=INVALID_PARAMS, message=str(exc))) from exc
    return info.model_dump()


# --- write-side helpers (subprocess + migrate URL flow) --------------------


def _run_uv_c2n_sync(
    args: list[str], *, cwd: Path | None
) -> subprocess.CompletedProcess[str]:
    proc: subprocess.CompletedProcess[str] = subprocess.run(
        ["uv", "run", "c2n", *args],
        cwd=cwd or Path.cwd(),
        capture_output=True,
        text=True,
        check=False,
    )
    return proc


async def _run_uv_c2n(args: list[str], *, cwd: Path | None = None) -> dict[str, Any]:
    """Run ``uv run c2n …``; raise :class:`McpError` on non-zero exit."""
    proc = await asyncio.to_thread(_run_uv_c2n_sync, args, cwd=cwd)
    if proc.returncode != 0:
        msg = (proc.stderr or "").strip() or (proc.stdout or "").strip()
        if not msg:
            msg = f"exit code {proc.returncode}"
        raise McpError(
            ErrorData(
                code=INTERNAL_ERROR,
                message=f"uv run c2n {' '.join(args[:4])}… failed: {msg[:4000]}",
            )
        )
    return {"returncode": proc.returncode, "stdout": (proc.stdout or "").strip()}


async def _c2n_migrate_handler(
    url: str,
    to: str | None = None,
    name: str | None = None,
    rediscover: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Run the same URL-driven migrate flow as ``c2n migrate <url>`` (writes under ``output/``)."""

    def _run() -> Path:
        from confluence_to_notion.cli import _migrate_url_flow

        return _migrate_url_flow(
            url,
            to=to,
            name=name,
            rediscover=rediscover,
            dry_run=dry_run,
        )

    try:
        run_dir = await asyncio.to_thread(_run)
    except typer.Exit as exc:
        code = getattr(exc, "exit_code", 1) or 1
        raise McpError(
            ErrorData(
                code=INTERNAL_ERROR,
                message=f"c2n migrate failed (exit {code})",
            )
        ) from exc
    return {"slug": run_dir.name, "run_dir": str(run_dir.resolve())}


async def _c2n_fetch_handler(
    space: str | None = None,
    pages: str | None = None,
    limit: int = 25,
    out_dir: str = "samples",
    url: str | None = None,
) -> dict[str, Any]:
    if not space and not pages:
        raise McpError(
            ErrorData(
                code=INVALID_PARAMS,
                message="Provide ``space`` or ``pages`` (comma-separated page IDs).",
            )
        )
    args: list[str] = ["fetch", "--limit", str(limit), "--out-dir", out_dir]
    if space:
        args.extend(["--space", space])
    if pages:
        args.extend(["--pages", pages])
    if url is not None:
        args.extend(["--url", url])
    return await _run_uv_c2n(args, cwd=None)


async def _c2n_discover_handler(samples: str, url: str) -> dict[str, Any]:
    """Run ``scripts/discover.sh`` (same as the CLI reminder + URL migrate path)."""

    def _run() -> subprocess.CompletedProcess[str]:
        proc: subprocess.CompletedProcess[str] = subprocess.run(
            ["bash", "scripts/discover.sh", samples, "--url", url],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        return proc

    proc = await asyncio.to_thread(_run)
    if proc.returncode != 0:
        msg = (proc.stderr or "").strip() or (proc.stdout or "").strip()
        raise McpError(
            ErrorData(
                code=INTERNAL_ERROR,
                message=f"discover.sh failed: {msg[:4000]}",
            )
        )
    return {"returncode": proc.returncode, "stdout": (proc.stdout or "").strip()}


async def _c2n_convert_handler(rules: str, input_dir: str, url: str) -> dict[str, Any]:
    args = ["convert", "--rules", rules, "--input", input_dir, "--url", url]
    return await _run_uv_c2n(args, cwd=None)


async def _c2n_push_handler(
    url: str,
    rules: str,
    input_dir: str,
    target: str,
) -> dict[str, Any]:
    """Legacy batch migrate (``c2n migrate --url … --rules … --input … --target …``)."""
    args = [
        "migrate",
        "--url",
        url,
        "--rules",
        rules,
        "--input",
        input_dir,
        "--target",
        target,
    ]
    return await _run_uv_c2n(args, cwd=None)


# --- resource handlers -----------------------------------------------------


def _converted_page_stems(run_dir: Path) -> list[str]:
    conv_dir = run_dir / "converted"
    if not conv_dir.is_dir():
        return []
    return sorted(p.stem for p in conv_dir.glob("*.json"))


def _list_resources(base: Path) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    runs_root = base / "runs"
    if runs_root.is_dir():
        has_runs = False
        for run_dir in sorted(runs_root.iterdir()):
            if not run_dir.is_dir() or not (run_dir / "status.json").is_file():
                continue
            has_runs = True
            slug = run_dir.name
            entries.append(
                {
                    "uri": f"c2n://runs/{slug}/status",
                    "name": f"run:{slug}:status",
                    "mime_type": "application/json",
                }
            )
            if (run_dir / "report.md").is_file():
                entries.append(
                    {
                        "uri": f"c2n://runs/{slug}/report",
                        "name": f"run:{slug}:report",
                        "mime_type": "text/markdown",
                    }
                )
            for stem in _converted_page_stems(run_dir):
                entries.append(
                    {
                        "uri": f"c2n://runs/{slug}/converted/{stem}",
                        "name": f"run:{slug}:converted:{stem}",
                        "mime_type": "application/json",
                    }
                )
        if has_runs:
            entries.insert(
                0,
                {"uri": "c2n://runs", "name": "runs", "mime_type": "application/json"},
            )
    if (base / "rules.json").is_file():
        entries.append(
            {"uri": "c2n://rules", "name": "rules", "mime_type": "application/json"}
        )
    return entries


async def _list_resources_handler(base: Path) -> list[dict[str, str]]:
    """Enumerate ``c2n://`` resources backed by files under ``base/``.

    Emits one entry per existing artifact: the runs index, each run's
    ``status``/``report``/``converted/<page>``, and the top-level rules JSON
    when present. Nothing is emitted when neither ``base/runs/`` nor
    ``base/rules.json`` exist.
    """
    return _list_resources(base)


def _not_found(uri: str) -> McpError:
    return McpError(ErrorData(code=INVALID_PARAMS, message=f"resource not found: {uri}"))


async def _read_resource_handler(base: Path, uri: str) -> str:
    """Resolve a ``c2n://`` URI to the underlying file contents.

    Returns raw text (JSON files are passed through unparsed). Missing files
    and unknown URI shapes both raise :class:`McpError` with ``INVALID_PARAMS``
    so MCP clients see a uniform not-found response.
    """
    if not uri.startswith(_C2N_SCHEME):
        raise _not_found(uri)
    rest = uri[len(_C2N_SCHEME):]
    segments = [s for s in rest.split("/") if s]

    base_res = base.resolve()

    if segments == ["rules"]:
        rules_path = (base / "rules.json").resolve()
        try:
            if not rules_path.is_file() or not rules_path.is_relative_to(base_res):
                raise _not_found(uri)
        except ValueError:
            raise _not_found(uri) from None
        return rules_path.read_text(encoding="utf-8")

    if segments == ["runs"]:
        return json.dumps(_list_runs(base), indent=2)

    if len(segments) >= 3 and segments[0] == "runs":
        slug = segments[1]
        if _unsafe_path_segment(slug):
            raise _not_found(uri)
        runs_root = (base / "runs").resolve()
        run_dir = (base / "runs" / slug).resolve()
        try:
            if not run_dir.is_relative_to(runs_root):
                raise _not_found(uri)
        except ValueError:
            raise _not_found(uri) from None
        status_path = (run_dir / "status.json").resolve()
        if not status_path.is_file() or not status_path.is_relative_to(run_dir):
            raise _not_found(uri)
        if segments[2] == "status" and len(segments) == 3:
            return status_path.read_text(encoding="utf-8")
        if segments[2] == "report" and len(segments) == 3:
            report = (run_dir / "report.md").resolve()
            try:
                if not report.is_file() or not report.is_relative_to(run_dir):
                    raise _not_found(uri)
            except ValueError:
                raise _not_found(uri) from None
            return report.read_text(encoding="utf-8")
        if segments[2] == "converted" and len(segments) == 4:
            stem = segments[3]
            if _unsafe_path_segment(stem):
                raise _not_found(uri)
            conv_root = (run_dir / "converted").resolve()
            target = (run_dir / "converted" / f"{stem}.json").resolve()
            try:
                if not target.is_file() or not target.is_relative_to(conv_root):
                    raise _not_found(uri)
            except ValueError:
                raise _not_found(uri) from None
            return target.read_text(encoding="utf-8")

    raise _not_found(uri)


# --- server wiring ---------------------------------------------------------


def build_server(base: Path = DEFAULT_BASE) -> FastMCP:
    """Build a FastMCP server that exposes the read-only c2n tools.

    ``base`` points at the directory containing ``runs/`` and ``rules.json``
    (defaults to ``output/``). Callers that want a different layout — tests, for
    instance — pass a ``tmp_path`` here.
    """
    server: FastMCP = FastMCP(name="c2n")

    async def c2n_list_runs() -> list[dict[str, Any]]:
        """List all run directories under output/runs/ with step statuses."""
        return await _list_runs_handler(base)

    async def c2n_status(slug: str | None = None) -> Any:
        """Return the status.json for a specific run slug, or a list summary."""
        return await _status_handler(base, slug)

    async def c2n_resolve_url(url: str) -> dict[str, Any]:
        """Classify a Confluence URL into (source_type, identifier)."""
        return await _resolve_url_handler(url)

    async def c2n_migrate(
        url: str,
        to: str | None = None,
        name: str | None = None,
        rediscover: bool = False,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """URL-driven migrate (same as ``c2n migrate <url>``); returns run slug + path."""
        return await _c2n_migrate_handler(
            url, to=to, name=name, rediscover=rediscover, dry_run=dry_run
        )

    async def c2n_fetch(
        space: str | None = None,
        pages: str | None = None,
        limit: int = 25,
        out_dir: str = "samples",
        url: str | None = None,
    ) -> dict[str, Any]:
        """Fetch Confluence XHTML (``c2n fetch``)."""
        return await _c2n_fetch_handler(
            space=space, pages=pages, limit=limit, out_dir=out_dir, url=url
        )

    async def c2n_discover(samples: str, url: str) -> dict[str, Any]:
        """Run ``bash scripts/discover.sh <samples> --url <url>``."""
        return await _c2n_discover_handler(samples, url)

    async def c2n_convert(rules: str, input_dir: str, url: str) -> dict[str, Any]:
        """Offline XHTML → blocks (``c2n convert --rules … --input … --url …``)."""
        return await _c2n_convert_handler(rules, input_dir, url)

    async def c2n_push(url: str, rules: str, input_dir: str, target: str) -> dict[str, Any]:
        """Batch publish pre-converted samples (legacy ``c2n migrate --url …`` form)."""
        return await _c2n_push_handler(url, rules, input_dir, target)

    server.add_tool(c2n_list_runs, name="c2n_list_runs")
    server.add_tool(c2n_status, name="c2n_status")
    server.add_tool(c2n_resolve_url, name="c2n_resolve_url")
    server.add_tool(c2n_migrate, name="c2n_migrate")
    server.add_tool(c2n_fetch, name="c2n_fetch")
    server.add_tool(c2n_discover, name="c2n_discover")
    server.add_tool(c2n_convert, name="c2n_convert")
    server.add_tool(c2n_push, name="c2n_push")

    _register_resources(server, base)
    return server


def _register_resources(server: FastMCP, base: Path) -> None:
    """Register static c2n:// resources discovered under ``base``.

    FastMCP resolves resources by URI up front, so only files that exist at
    build time are exposed. Each ``fn`` re-reads the file on demand so updates
    made after the server is built are visible to clients.
    """
    for entry in _list_resources(base):
        uri = entry["uri"]
        server.add_resource(
            FunctionResource(
                uri=AnyUrl(uri),
                name=entry["name"],
                mime_type=entry["mime_type"],
                fn=_make_reader(base, uri),
            )
        )


def _make_reader(base: Path, uri: str) -> Any:
    async def read() -> str:
        return await _read_resource_handler(base, uri)

    return read


def main() -> None:
    """Entry point for the ``c2n-mcp`` console script — stdio transport."""
    build_server().run(transport="stdio")
