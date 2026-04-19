"""Unit tests for the c2n MCP server (read-only tools + c2n:// resources)."""

import json
from pathlib import Path

import pytest
from mcp.shared.exceptions import McpError
from pydantic import ValidationError

from confluence_to_notion.mcp_server import (
    ResolveUrlArgs,
    StatusArgs,
    _list_resources_handler,
    _list_runs_handler,
    _read_resource_handler,
    _resolve_url_handler,
    _status_handler,
    build_server,
)
from confluence_to_notion.runs import RunStatus, StepRecord, StepStatus, write_status


def _seed_run(
    base: Path,
    slug: str,
    *,
    with_report: bool = False,
    converted: list[str] | None = None,
) -> Path:
    run_dir = base / "runs" / slug
    run_dir.mkdir(parents=True)
    (run_dir / "source.json").write_text(
        json.dumps({"url": f"https://example.atlassian.net/wiki/spaces/X/pages/{slug}",
                    "type": "page"}),
        encoding="utf-8",
    )
    status = RunStatus(
        fetch=StepRecord(status=StepStatus.DONE, at="2026-04-19T00:00:00+00:00"),
        discover=StepRecord(status=StepStatus.DONE, at="2026-04-19T00:01:00+00:00"),
    )
    write_status(run_dir, status)
    if with_report:
        (run_dir / "report.md").write_text("# Run Report\n", encoding="utf-8")
    if converted:
        conv_dir = run_dir / "converted"
        conv_dir.mkdir()
        for name in converted:
            (conv_dir / f"{name}.json").write_text(
                json.dumps({"page": name, "blocks": []}), encoding="utf-8"
            )
    return run_dir


# ---------- c2n_list_runs --------------------------------------------------


async def test_list_runs_returns_empty_when_runs_dir_missing(tmp_path: Path) -> None:
    result = await _list_runs_handler(tmp_path)
    assert result == []


async def test_list_runs_returns_status_summary(tmp_path: Path) -> None:
    _seed_run(tmp_path, "example-1")
    _seed_run(tmp_path, "example-2")

    result = await _list_runs_handler(tmp_path)

    slugs = {r["slug"] for r in result}
    assert slugs == {"example-1", "example-2"}
    for entry in result:
        assert entry["status"]["fetch"] == "done"
        assert entry["status"]["discover"] == "done"
        assert entry["status"]["convert"] == "pending"
        assert entry["status"]["migrate"] == "pending"


# ---------- c2n_status -----------------------------------------------------


async def test_status_returns_full_json_for_slug(tmp_path: Path) -> None:
    _seed_run(tmp_path, "my-slug")

    result = await _status_handler(tmp_path, "my-slug")

    assert result["fetch"]["status"] == "done"
    assert result["discover"]["status"] == "done"
    assert result["convert"]["status"] == "pending"


async def test_status_raises_mcp_error_for_missing_slug(tmp_path: Path) -> None:
    with pytest.raises(McpError):
        await _status_handler(tmp_path, "nope")


async def test_status_without_slug_returns_summary(tmp_path: Path) -> None:
    _seed_run(tmp_path, "example-1")

    result = await _status_handler(tmp_path, None)

    assert isinstance(result, list)
    assert result[0]["slug"] == "example-1"


def test_status_args_slug_optional() -> None:
    assert StatusArgs().slug is None
    assert StatusArgs(slug="foo").slug == "foo"


# ---------- c2n_resolve_url ------------------------------------------------


async def test_resolve_url_returns_page_for_pageid_query() -> None:
    result = await _resolve_url_handler(
        "https://cwiki.apache.org/confluence/pages/viewpage.action?pageId=12345"
    )
    assert result["source_type"] == "page"
    assert result["identifier"] == "12345"


async def test_resolve_url_raises_mcp_error_for_malformed_url() -> None:
    with pytest.raises(McpError):
        await _resolve_url_handler("not-a-url")


def test_resolve_url_args_requires_url() -> None:
    with pytest.raises(ValidationError):
        ResolveUrlArgs()  # type: ignore[call-arg]


# ---------- build_server ---------------------------------------------------


def test_build_server_registers_read_only_tools() -> None:
    server = build_server()
    names = {t.name for t in server._tool_manager.list_tools()}
    assert {"c2n_list_runs", "c2n_status", "c2n_resolve_url"}.issubset(names)


# ---------- c2n:// resources (list) ----------------------------------------


async def test_list_resources_empty_when_no_runs_or_rules(tmp_path: Path) -> None:
    result = await _list_resources_handler(tmp_path)
    assert result == []


async def test_list_resources_exposes_runs_and_rules(tmp_path: Path) -> None:
    _seed_run(tmp_path, "example-1", with_report=True, converted=["page-a", "page-b"])
    (tmp_path / "rules.json").write_text(json.dumps({"rules": []}), encoding="utf-8")

    result = await _list_resources_handler(tmp_path)
    uris = {entry["uri"] for entry in result}

    assert "c2n://runs" in uris
    assert "c2n://runs/example-1/status" in uris
    assert "c2n://runs/example-1/report" in uris
    assert "c2n://runs/example-1/converted/page-a" in uris
    assert "c2n://runs/example-1/converted/page-b" in uris
    assert "c2n://rules" in uris


async def test_list_resources_skips_report_when_missing(tmp_path: Path) -> None:
    _seed_run(tmp_path, "example-1")
    result = await _list_resources_handler(tmp_path)
    uris = {entry["uri"] for entry in result}
    assert "c2n://runs/example-1/status" in uris
    assert "c2n://runs/example-1/report" not in uris


# ---------- c2n:// resources (read) ----------------------------------------


async def test_read_resource_runs_root(tmp_path: Path) -> None:
    _seed_run(tmp_path, "example-1")

    payload = await _read_resource_handler(tmp_path, "c2n://runs")
    data = json.loads(payload)
    assert any(item["slug"] == "example-1" for item in data)


async def test_read_resource_status(tmp_path: Path) -> None:
    _seed_run(tmp_path, "example-1")

    payload = await _read_resource_handler(tmp_path, "c2n://runs/example-1/status")
    data = json.loads(payload)
    assert data["fetch"]["status"] == "done"


async def test_read_resource_report(tmp_path: Path) -> None:
    _seed_run(tmp_path, "example-1", with_report=True)

    payload = await _read_resource_handler(tmp_path, "c2n://runs/example-1/report")
    assert "# Run Report" in payload


async def test_read_resource_converted_page(tmp_path: Path) -> None:
    _seed_run(tmp_path, "example-1", converted=["page-a"])

    payload = await _read_resource_handler(
        tmp_path, "c2n://runs/example-1/converted/page-a"
    )
    data = json.loads(payload)
    assert data["page"] == "page-a"


async def test_read_resource_rules(tmp_path: Path) -> None:
    (tmp_path / "rules.json").write_text(json.dumps({"rules": [1, 2]}), encoding="utf-8")

    payload = await _read_resource_handler(tmp_path, "c2n://rules")
    data = json.loads(payload)
    assert data["rules"] == [1, 2]


async def test_read_resource_unknown_uri_raises(tmp_path: Path) -> None:
    _seed_run(tmp_path, "example-1")
    with pytest.raises(McpError):
        await _read_resource_handler(tmp_path, "c2n://runs/example-1/nope")


async def test_read_resource_unknown_scheme_raises(tmp_path: Path) -> None:
    with pytest.raises(McpError):
        await _read_resource_handler(tmp_path, "file:///etc/passwd")


async def test_read_resource_missing_slug_raises(tmp_path: Path) -> None:
    with pytest.raises(McpError):
        await _read_resource_handler(tmp_path, "c2n://runs/missing/status")


async def test_read_resource_missing_rules_raises(tmp_path: Path) -> None:
    with pytest.raises(McpError):
        await _read_resource_handler(tmp_path, "c2n://rules")
