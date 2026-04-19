"""Unit tests for the CLI migrate-tree-pages command (2-pass migration)."""

import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import click
import httpx
import pytest
from notion_client import APIResponseError
from typer.testing import CliRunner

from confluence_to_notion.agents.schemas import FinalRuleset
from confluence_to_notion.cli import _prompt_table_rule, app
from confluence_to_notion.confluence.schemas import ConfluencePage, PageTreeNode
from confluence_to_notion.converter.resolution import ResolutionStore
from confluence_to_notion.converter.schemas import (
    ConversionResult,
    TableRule,
    TableRuleSet,
    UnresolvedItem,
)
from confluence_to_notion.converter.table_rules import TableRuleStore
from confluence_to_notion.runs import SourceInfo, StepStatus, read_status

runner = CliRunner()


# Every CLI test uses this URL; matching slug is "example-root".
_URL = "https://example.atlassian.net/wiki/spaces/TEST/pages/root"


def _fixture_tree() -> PageTreeNode:
    return PageTreeNode(
        id="root",
        title="Root Page",
        children=[
            PageTreeNode(id="c1", title="Child 1"),
            PageTreeNode(
                id="c2",
                title="Child 2",
                children=[PageTreeNode(id="gc1", title="Grandchild 1")],
            ),
        ],
    )


def _fake_page(page_id: str, title: str) -> ConfluencePage:
    return ConfluencePage(
        id=page_id,
        title=title,
        space_key="TEST",
        storage_body=f"<p>body for {title}</p>",
        version=1,
        created_at=datetime(2026, 1, 1, 0, 0, 0),
    )


def _make_settings_mock(
    *,
    notion_root_page_id: str | None = "env-root",
    notion_api_token: str | None = "ntn_fake",
) -> Any:
    def _require_notion() -> None:
        if not notion_api_token:
            raise ValueError("NOTION_API_TOKEN is required. Set it in .env")
        if not notion_root_page_id:
            raise ValueError("NOTION_ROOT_PAGE_ID is required. Set it in .env")

    return SimpleNamespace(
        notion_api_token=notion_api_token,
        notion_root_page_id=notion_root_page_id,
        confluence_rest_url="https://test.atlassian.net/wiki/rest/api",
        confluence_email="x",
        confluence_api_token="y",
        confluence_auth_available=True,
        require_notion=_require_notion,
    )


def _write_rules(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ruleset = FinalRuleset(source="fake-proposals.json", rules=[])
    path.write_text(ruleset.model_dump_json(indent=2) + "\n", encoding="utf-8")


def _build_confluence_mock(tree: PageTreeNode) -> Any:
    """Create an AsyncMock ConfluenceClient instance supporting async-with."""
    mock = AsyncMock()
    mock.__aenter__.return_value = mock
    mock.__aexit__.return_value = None
    mock.collect_page_tree = AsyncMock(return_value=tree)

    title_for = {
        "root": "Root Page",
        "c1": "Child 1",
        "c2": "Child 2",
        "gc1": "Grandchild 1",
    }

    async def _get_page(page_id: str) -> ConfluencePage:
        return _fake_page(page_id, title_for.get(page_id, page_id))

    mock.get_page = AsyncMock(side_effect=_get_page)
    return mock


def _build_notion_mock() -> Any:
    """Create a NotionClientWrapper mock whose create_subpage returns np-<id>."""
    mock = AsyncMock()

    title_to_id = {
        "Root Page": "np-root",
        "Child 1": "np-c1",
        "Child 2": "np-c2",
        "Grandchild 1": "np-gc1",
    }

    async def _create_subpage(parent_id: str, title: str) -> str:
        return title_to_id[title]

    mock.create_subpage = AsyncMock(side_effect=_create_subpage)
    mock.append_blocks = AsyncMock(return_value=None)
    mock.create_database = AsyncMock(return_value="db-default")
    return mock


@pytest.fixture(autouse=True)
def _isolate_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)


def _only_run_dir(tmp_path: Path) -> Path:
    """Return the single run directory under ``tmp_path/output/runs/``."""
    run_root = tmp_path / "output" / "runs"
    dirs = [p for p in run_root.iterdir() if p.is_dir()]
    assert len(dirs) == 1, f"expected exactly one run dir, got {dirs}"
    return dirs[0]


# --- --url required guard ---


def test_migrate_tree_pages_without_url_exits(tmp_path: Path) -> None:
    """Without --url, migrate-tree-pages must fail and never write legacy sinks."""
    rules_path = tmp_path / "rules.json"
    _write_rules(rules_path)

    result = runner.invoke(
        app,
        [
            "migrate-tree-pages",
            "--root-id",
            "root",
            "--target",
            "parent-xyz",
            "--rules",
            str(rules_path),
        ],
        standalone_mode=False,
    )

    assert result.exit_code != 0
    assert isinstance(result.exception, click.exceptions.UsageError)
    assert "--url" in str(result.exception)
    assert not (tmp_path / "output" / "resolution.json").exists()
    assert not (tmp_path / "output" / "rules" / "table-rules.json").exists()
    assert not (tmp_path / "output" / "runs").exists()


# --- env-root fallback + missing target ---


@patch("confluence_to_notion.cli.convert_page")
@patch("confluence_to_notion.cli.NotionClientWrapper")
@patch("confluence_to_notion.cli.ConfluenceClient")
@patch("confluence_to_notion.cli._load_settings")
def test_migrate_tree_pages_falls_back_to_env_root(
    mock_settings: Any,
    mock_conf_cls: Any,
    mock_notion_cls: Any,
    mock_convert: Any,
    tmp_path: Path,
) -> None:
    """--target omitted → NOTION_ROOT_PAGE_ID is used as the Notion parent."""
    mock_settings.return_value = _make_settings_mock(notion_root_page_id="env-root")
    mock_conf_cls.return_value = _build_confluence_mock(
        PageTreeNode(id="root", title="Root Page")
    )
    mock_notion_cls.return_value = _build_notion_mock()
    mock_convert.return_value = ConversionResult(
        page_id="", blocks=[], unresolved=[]
    )

    rules_path = tmp_path / "rules.json"
    _write_rules(rules_path)

    result = runner.invoke(
        app,
        [
            "migrate-tree-pages",
            "--root-id",
            "root",
            "--rules",
            str(rules_path),
            "--url",
            _URL,
        ],
    )

    assert result.exit_code == 0, result.output

    notion_mock = mock_notion_cls.return_value
    first_call = notion_mock.create_subpage.await_args_list[0]
    parent_id = first_call.kwargs.get(
        "parent_id", first_call.args[0] if first_call.args else None
    )
    assert parent_id == "env-root"


@patch("confluence_to_notion.cli.convert_page")
@patch("confluence_to_notion.cli.NotionClientWrapper")
@patch("confluence_to_notion.cli.ConfluenceClient")
@patch("confluence_to_notion.cli._load_settings")
def test_migrate_tree_pages_missing_target_and_env_exits(
    mock_settings: Any,
    mock_conf_cls: Any,
    mock_notion_cls: Any,
    mock_convert: Any,
    tmp_path: Path,
) -> None:
    """No --target and no NOTION_ROOT_PAGE_ID → exits non-zero with a hint."""
    mock_settings.return_value = _make_settings_mock(notion_root_page_id=None)

    rules_path = tmp_path / "rules.json"
    _write_rules(rules_path)

    result = runner.invoke(
        app,
        [
            "migrate-tree-pages",
            "--root-id",
            "root",
            "--rules",
            str(rules_path),
            "--url",
            _URL,
        ],
    )

    assert result.exit_code != 0
    assert "NOTION_ROOT_PAGE_ID" in result.output


# --- Helpers shared by Pass 1.5 tests ---


def _table_xhtml(headers: list[str], rows: list[list[str]]) -> str:
    """Build a Confluence storage body containing a single table."""
    thead = (
        "<thead><tr>"
        + "".join(f"<th>{h}</th>" for h in headers)
        + "</tr></thead>"
    )
    tbody = (
        "<tbody>"
        + "".join(
            "<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>"
            for row in rows
        )
        + "</tbody>"
    )
    return f"<table>{thead}{tbody}</table>"


def _build_confluence_mock_with_bodies(
    tree: PageTreeNode,
    bodies: dict[str, str],
) -> Any:
    """Like _build_confluence_mock but returns custom storage bodies per page id."""
    mock = AsyncMock()
    mock.__aenter__.return_value = mock
    mock.__aexit__.return_value = None
    mock.collect_page_tree = AsyncMock(return_value=tree)

    title_for: dict[str, str] = {}

    def _walk(node: PageTreeNode) -> None:
        title_for[node.id] = node.title
        for child in node.children:
            _walk(child)

    _walk(tree)

    async def _get_page(page_id: str) -> ConfluencePage:
        return ConfluencePage(
            id=page_id,
            title=title_for.get(page_id, page_id),
            space_key="TEST",
            storage_body=bodies.get(page_id, "<p/>"),
            version=1,
            created_at=datetime(2026, 1, 1, 0, 0, 0),
        )

    mock.get_page = AsyncMock(side_effect=_get_page)
    return mock


def _make_convert_side_effect(
    unresolved_per_xhtml: dict[str, list[UnresolvedItem]],
) -> Any:
    """convert_page mock: maps storage_body → ConversionResult.unresolved list."""

    def _side(
        xhtml: str,
        ruleset: Any,
        *,
        page_id: str = "",
        store: Any = None,
        table_rules: Any = None,
    ) -> ConversionResult:
        return ConversionResult(
            blocks=[{"object": "block", "type": "paragraph"}],
            unresolved=list(unresolved_per_xhtml.get(xhtml, [])),
        )

    return _side


# --- Pass 1.5: dedup + persist + non-TTY fallback ---


@patch("confluence_to_notion.cli._prompt_table_rule")
@patch("confluence_to_notion.cli.convert_page")
@patch("confluence_to_notion.cli.NotionClientWrapper")
@patch("confluence_to_notion.cli.ConfluenceClient")
@patch("confluence_to_notion.cli._load_settings")
def test_pass15_dedups_signature_across_pages_and_persists(
    mock_settings: Any,
    mock_conf_cls: Any,
    mock_notion_cls: Any,
    mock_convert: Any,
    mock_prompt: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two pages with the same header signature → ONE prompt; rule persisted to disk."""
    monkeypatch.setattr("confluence_to_notion.cli._stdin_is_tty", lambda: True)

    tree = PageTreeNode(
        id="root",
        title="Root Page",
        children=[
            PageTreeNode(id="c1", title="Child 1"),
            PageTreeNode(id="c2", title="Child 2"),
        ],
    )
    body_a = _table_xhtml(["Name", "Role"], [["Alice", "Dev"], ["Bob", "PM"]])
    body_b = _table_xhtml(["NAME", " role "], [["Carol", "QA"], ["Dan", "PM"]])
    bodies = {"root": "<p/>", "c1": body_a, "c2": body_b}
    mock_settings.return_value = _make_settings_mock()
    mock_conf_cls.return_value = _build_confluence_mock_with_bodies(tree, bodies)
    mock_notion_cls.return_value = _build_notion_mock()

    table_unresolved_a = UnresolvedItem(
        kind="table", identifier="t-c1-0", source_page_id="c1", context_xhtml=body_a
    )
    table_unresolved_b = UnresolvedItem(
        kind="table", identifier="t-c2-0", source_page_id="c2", context_xhtml=body_b
    )
    mock_convert.side_effect = _make_convert_side_effect(
        {body_a: [table_unresolved_a], body_b: [table_unresolved_b]}
    )

    answered = TableRule(
        is_database=True,
        title_column="name",
        column_types={"name": "title", "role": "select"},
    )
    mock_prompt.return_value = answered

    rules_path = tmp_path / "rules.json"
    _write_rules(rules_path)

    result = runner.invoke(
        app,
        [
            "migrate-tree-pages",
            "--root-id",
            "root",
            "--target",
            "parent-xyz",
            "--rules",
            str(rules_path),
            "--url",
            _URL,
        ],
    )
    assert result.exit_code == 0, result.output

    # Same normalized signature (name|role) across pages → exactly ONE prompt.
    assert mock_prompt.call_count == 1

    # Rule persisted under the per-run table-rules path.
    run_dir = _only_run_dir(tmp_path)
    table_rules_path = run_dir / "rules" / "table-rules.json"
    assert table_rules_path.exists()
    persisted = TableRuleSet.model_validate_json(
        table_rules_path.read_text(encoding="utf-8")
    )
    assert "name|role" in persisted.rules
    assert persisted.rules["name|role"].is_database is True


@patch("confluence_to_notion.cli._prompt_table_rule")
@patch("confluence_to_notion.cli.convert_page")
@patch("confluence_to_notion.cli.NotionClientWrapper")
@patch("confluence_to_notion.cli.ConfluenceClient")
@patch("confluence_to_notion.cli._load_settings")
def test_pass15_prompt_receives_column_type_draft(
    mock_settings: Any,
    mock_conf_cls: Any,
    mock_notion_cls: Any,
    mock_convert: Any,
    mock_prompt: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The prompt's kwargs include a column_type_draft from infer_column_types."""
    monkeypatch.setattr("confluence_to_notion.cli._stdin_is_tty", lambda: True)

    tree = PageTreeNode(id="root", title="Root Page")
    # Date column should be inferred as 'date'.
    body = _table_xhtml(
        ["Name", "Due"],
        [
            ["A", "2026-01-15"],
            ["B", "2026-02-01"],
            ["C", "2026-03-20"],
        ],
    )
    mock_settings.return_value = _make_settings_mock()
    mock_conf_cls.return_value = _build_confluence_mock_with_bodies(
        tree, {"root": body}
    )
    mock_notion_cls.return_value = _build_notion_mock()

    mock_convert.side_effect = _make_convert_side_effect(
        {
            body: [
                UnresolvedItem(
                    kind="table",
                    identifier="t-root-0",
                    source_page_id="root",
                    context_xhtml=body,
                )
            ]
        }
    )
    mock_prompt.return_value = TableRule(
        is_database=True,
        title_column="name",
        column_types={"name": "title", "due": "date"},
    )

    rules_path = tmp_path / "rules.json"
    _write_rules(rules_path)

    result = runner.invoke(
        app,
        [
            "migrate-tree-pages",
            "--root-id",
            "root",
            "--target",
            "parent-xyz",
            "--rules",
            str(rules_path),
            "--url",
            _URL,
        ],
    )
    assert result.exit_code == 0, result.output
    assert mock_prompt.call_count == 1

    kwargs = mock_prompt.call_args.kwargs
    draft = kwargs.get("column_type_draft")
    assert draft is not None, f"missing column_type_draft in kwargs: {kwargs}"
    assert draft.get("Due") == "date"
    sample_rows = kwargs.get("sample_rows")
    assert sample_rows is not None and len(sample_rows) >= 1


@patch("confluence_to_notion.cli._prompt_table_rule")
@patch("confluence_to_notion.cli.convert_page")
@patch("confluence_to_notion.cli.NotionClientWrapper")
@patch("confluence_to_notion.cli.ConfluenceClient")
@patch("confluence_to_notion.cli._load_settings")
def test_pass15_non_tty_does_not_prompt_or_block(
    mock_settings: Any,
    mock_conf_cls: Any,
    mock_notion_cls: Any,
    mock_convert: Any,
    mock_prompt: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-TTY → no prompt, no block, page still migrates, exit 0."""
    monkeypatch.setattr("confluence_to_notion.cli._stdin_is_tty", lambda: False)

    tree = PageTreeNode(id="root", title="Root Page")
    body = _table_xhtml(["Name", "Role"], [["Alice", "Dev"]])
    mock_settings.return_value = _make_settings_mock()
    mock_conf_cls.return_value = _build_confluence_mock_with_bodies(
        tree, {"root": body}
    )
    notion_mock = _build_notion_mock()
    mock_notion_cls.return_value = notion_mock

    mock_convert.side_effect = _make_convert_side_effect(
        {
            body: [
                UnresolvedItem(
                    kind="table",
                    identifier="t-root-0",
                    source_page_id="root",
                    context_xhtml=body,
                )
            ]
        }
    )

    rules_path = tmp_path / "rules.json"
    _write_rules(rules_path)

    result = runner.invoke(
        app,
        [
            "migrate-tree-pages",
            "--root-id",
            "root",
            "--target",
            "parent-xyz",
            "--rules",
            str(rules_path),
            "--url",
            _URL,
        ],
    )

    assert result.exit_code == 0, result.output
    assert mock_prompt.call_count == 0
    assert notion_mock.append_blocks.await_count == 1
    assert "name|role" in result.output.lower()


# --- Pass 1.5: Notion database creation for is_database=True signatures ---


@patch("confluence_to_notion.cli._prompt_table_rule")
@patch("confluence_to_notion.cli.NotionClientWrapper")
@patch("confluence_to_notion.cli.ConfluenceClient")
@patch("confluence_to_notion.cli._load_settings")
def test_pass15_creates_notion_db_once_per_is_database_signature(
    mock_settings: Any,
    mock_conf_cls: Any,
    mock_notion_cls: Any,
    mock_prompt: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two pages share the same is_database=True signature → create_database called once;
    each affected table gets a resolution entry; Pass 2 emits child_database blocks."""
    monkeypatch.setattr("confluence_to_notion.cli._stdin_is_tty", lambda: True)

    tree = PageTreeNode(
        id="root",
        title="Root Page",
        children=[
            PageTreeNode(id="c1", title="Child 1"),
            PageTreeNode(id="c2", title="Child 2"),
        ],
    )
    body_a = _table_xhtml(["Name", "Role"], [["Alice", "Dev"], ["Bob", "PM"]])
    body_b = _table_xhtml(["Name", "Role"], [["Carol", "QA"], ["Dan", "PM"]])
    bodies = {"root": "<p/>", "c1": body_a, "c2": body_b}

    mock_settings.return_value = _make_settings_mock()
    mock_conf_cls.return_value = _build_confluence_mock_with_bodies(tree, bodies)
    notion_mock = _build_notion_mock()
    notion_mock.create_database = AsyncMock(return_value="db-shared-123")
    mock_notion_cls.return_value = notion_mock

    mock_prompt.return_value = TableRule(
        is_database=True,
        title_column="name",
        column_types={"name": "title", "role": "select"},
    )

    rules_path = tmp_path / "rules.json"
    _write_rules(rules_path)

    result = runner.invoke(
        app,
        [
            "migrate-tree-pages",
            "--root-id",
            "root",
            "--target",
            "parent-xyz",
            "--rules",
            str(rules_path),
            "--url",
            _URL,
        ],
    )
    assert result.exit_code == 0, result.output

    # (a) create_database invoked exactly once for the shared signature.
    assert notion_mock.create_database.await_count == 1
    db_call = notion_mock.create_database.await_args_list[0]
    db_kwargs = db_call.kwargs
    # The DB lives under the page where the signature was first observed (c1, → np-c1).
    assert db_kwargs.get("parent_id", db_call.args[0] if db_call.args else None) == "np-c1"
    assert db_kwargs["title_column"] == "name"
    assert db_kwargs["column_types"] == {"name": "title", "role": "select"}

    # (b) Resolution store carries database_id entries for the affected tables.
    run_dir = _only_run_dir(tmp_path)
    res_store = ResolutionStore(run_dir / "resolution.json")
    table_entries = [
        (k, v) for k, v in res_store.data.entries.items() if k.startswith("table:")
    ]
    assert table_entries, "expected at least one table:* entry"
    for _key, entry in table_entries:
        assert entry.value == {"database_id": "db-shared-123"}

    # (c) Pass 2 output for c1/c2 is a child_database referencing db-shared-123,
    # never a layout table block.
    blocks_per_page: dict[str, list[dict[str, Any]]] = {}
    for call in notion_mock.append_blocks.await_args_list:
        page_id = call.kwargs.get(
            "page_id", call.args[0] if call.args else None
        )
        blocks = call.kwargs.get(
            "blocks", call.args[1] if len(call.args) > 1 else []
        )
        blocks_per_page[page_id] = blocks

    for np_id in ("np-c1", "np-c2"):
        blocks = blocks_per_page[np_id]
        child_db_blocks = [b for b in blocks if b.get("type") == "child_database"]
        assert len(child_db_blocks) == 1, f"page {np_id} blocks={blocks}"
        assert child_db_blocks[0]["child_database"] == {"database_id": "db-shared-123"}
        assert not any(b.get("type") == "table" for b in blocks)


@patch("confluence_to_notion.cli._prompt_table_rule")
@patch("confluence_to_notion.cli.NotionClientWrapper")
@patch("confluence_to_notion.cli.ConfluenceClient")
@patch("confluence_to_notion.cli._load_settings")
def test_pass15_layout_signature_keeps_table_block_and_no_db_create(
    mock_settings: Any,
    mock_conf_cls: Any,
    mock_notion_cls: Any,
    mock_prompt: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """is_database=False → no create_database, page keeps layout table block."""
    monkeypatch.setattr("confluence_to_notion.cli._stdin_is_tty", lambda: True)

    tree = PageTreeNode(id="root", title="Root Page")
    body = _table_xhtml(["Name", "Role"], [["Alice", "Dev"]])
    mock_settings.return_value = _make_settings_mock()
    mock_conf_cls.return_value = _build_confluence_mock_with_bodies(tree, {"root": body})
    notion_mock = _build_notion_mock()
    notion_mock.create_database = AsyncMock(return_value="db-should-not-be-used")
    mock_notion_cls.return_value = notion_mock

    mock_prompt.return_value = TableRule(is_database=False)

    rules_path = tmp_path / "rules.json"
    _write_rules(rules_path)

    result = runner.invoke(
        app,
        [
            "migrate-tree-pages",
            "--root-id",
            "root",
            "--target",
            "parent-xyz",
            "--rules",
            str(rules_path),
            "--url",
            _URL,
        ],
    )
    assert result.exit_code == 0, result.output

    notion_mock.create_database.assert_not_awaited()
    blocks = notion_mock.append_blocks.await_args_list[0].kwargs.get(
        "blocks", notion_mock.append_blocks.await_args_list[0].args[1]
    )
    table_blocks = [b for b in blocks if b.get("type") == "table"]
    child_db_blocks = [b for b in blocks if b.get("type") == "child_database"]
    assert len(table_blocks) == 1
    assert child_db_blocks == []


@patch("confluence_to_notion.cli._prompt_table_rule")
@patch("confluence_to_notion.cli.NotionClientWrapper")
@patch("confluence_to_notion.cli.ConfluenceClient")
@patch("confluence_to_notion.cli._load_settings")
def test_pass15_non_tty_does_not_create_db(
    mock_settings: Any,
    mock_conf_cls: Any,
    mock_notion_cls: Any,
    mock_prompt: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-TTY: rule is never set → no create_database invoked."""
    monkeypatch.setattr("confluence_to_notion.cli._stdin_is_tty", lambda: False)

    tree = PageTreeNode(id="root", title="Root Page")
    body = _table_xhtml(["Name", "Role"], [["Alice", "Dev"]])
    mock_settings.return_value = _make_settings_mock()
    mock_conf_cls.return_value = _build_confluence_mock_with_bodies(tree, {"root": body})
    notion_mock = _build_notion_mock()
    notion_mock.create_database = AsyncMock(return_value="db-x")
    mock_notion_cls.return_value = notion_mock

    rules_path = tmp_path / "rules.json"
    _write_rules(rules_path)

    result = runner.invoke(
        app,
        [
            "migrate-tree-pages",
            "--root-id",
            "root",
            "--target",
            "parent-xyz",
            "--rules",
            str(rules_path),
            "--url",
            _URL,
        ],
    )
    assert result.exit_code == 0, result.output
    notion_mock.create_database.assert_not_awaited()
    mock_prompt.assert_not_called()


# --- _prompt_table_rule direct regression: store must survive round-trip ---


def test_prompt_table_rule_persists_roundtrip_with_title_cased_headers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Title-cased headers + default title column must produce a rule that survives
    save→load. Without normalization, TableRuleSet validation rejects the file
    (title_column 'Name' not in signature columns ['name', 'role']) and
    TableRuleStore._load silently wipes every previously persisted rule.
    """
    monkeypatch.setattr("typer.confirm", lambda *a, **kw: True)
    monkeypatch.setattr("typer.prompt", lambda *a, **kw: kw.get("default", a[-1]))

    headers = ["Name", "Role"]
    sample_rows = [["Alice", "Dev"], ["Bob", "PM"]]
    draft: dict[str, Any] = {"Name": "title", "Role": "select"}

    rule = _prompt_table_rule(
        headers=headers,
        sample_rows=sample_rows,
        column_type_draft=draft,
    )

    assert rule.is_database is True
    assert rule.title_column == "name"
    assert rule.column_types == {"name": "title", "role": "select"}

    store_path = tmp_path / "table-rules.json"
    store = TableRuleStore(store_path)
    store.upsert(headers, rule)
    store.save()

    reloaded = TableRuleStore(store_path)
    assert reloaded.lookup(headers) is not None
    assert reloaded.lookup(headers) == rule
    assert "name|role" in reloaded.data.rules


def test_prompt_table_rule_reprompts_on_invalid_title_col(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TTY: a typo'd title_col not in headers re-prompts until a valid header is given."""
    monkeypatch.setattr("confluence_to_notion.cli._stdin_is_tty", lambda: True)
    monkeypatch.setattr("typer.confirm", lambda *a, **kw: True)

    prompt_mock = MagicMock(side_effect=["totally_bogus", "Name"])
    monkeypatch.setattr("typer.prompt", prompt_mock)

    rule = _prompt_table_rule(
        headers=["Name", "Role"],
        sample_rows=[["Alice", "Dev"]],
        column_type_draft={"Name": "title", "Role": "select"},
    )

    assert prompt_mock.call_count >= 2
    assert rule.is_database is True
    assert rule.title_column == "name"


def test_prompt_table_rule_accepts_case_variant_without_reprompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TTY: 'NAME' for headers ['Name','Role'] resolves to 'name' on the first try."""
    monkeypatch.setattr("confluence_to_notion.cli._stdin_is_tty", lambda: True)
    monkeypatch.setattr("typer.confirm", lambda *a, **kw: True)

    prompt_mock = MagicMock(side_effect=["NAME"])
    monkeypatch.setattr("typer.prompt", prompt_mock)

    rule = _prompt_table_rule(
        headers=["Name", "Role"],
        sample_rows=[["Alice", "Dev"]],
        column_type_draft={"Name": "title", "Role": "select"},
    )

    assert prompt_mock.call_count == 1
    assert rule.title_column == "name"


def test_prompt_table_rule_non_tty_falls_back_to_first_header(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Non-TTY: a bogus title_col falls back to headers[0] (normalized) with a warning."""
    monkeypatch.setattr("confluence_to_notion.cli._stdin_is_tty", lambda: False)
    monkeypatch.setattr("typer.confirm", lambda *a, **kw: True)

    prompt_mock = MagicMock(return_value="totally_bogus")
    monkeypatch.setattr("typer.prompt", prompt_mock)

    rule = _prompt_table_rule(
        headers=["Name", "Role"],
        sample_rows=[["Alice", "Dev"]],
        column_type_draft={"Name": "title", "Role": "select"},
    )

    assert rule.title_column == "name"
    assert prompt_mock.call_count <= 1

    captured = capsys.readouterr().out
    assert "totally_bogus" in captured
    assert "name" in captured


# --- --url mode: run-dir layout wiring ---


@patch("confluence_to_notion.cli.convert_page")
@patch("confluence_to_notion.cli.NotionClientWrapper")
@patch("confluence_to_notion.cli.ConfluenceClient")
@patch("confluence_to_notion.cli._load_settings")
def test_migrate_tree_pages_url_mode_writes_run_artifacts(
    mock_settings: Any,
    mock_conf_cls: Any,
    mock_notion_cls: Any,
    mock_convert: Any,
    tmp_path: Path,
) -> None:
    """--url mode: start_run seeds source.json/status.json, converted/ holds Pass-2
    JSON per page, status.json records fetch/convert/migrate=DONE, report.md is
    rendered on finalize_run.
    """
    mock_settings.return_value = _make_settings_mock()
    mock_conf_cls.return_value = _build_confluence_mock(_fixture_tree())
    mock_notion_cls.return_value = _build_notion_mock()

    mock_convert.return_value = ConversionResult(
        page_id="",
        blocks=[{"object": "block", "type": "paragraph"}],
        unresolved=[],
    )

    rules_path = tmp_path / "rules.json"
    _write_rules(rules_path)

    url = "https://example.atlassian.net/wiki/spaces/TEST/pages/root/Root+Page"

    result = runner.invoke(
        app,
        [
            "migrate-tree-pages",
            "--root-id",
            "root",
            "--target",
            "parent-xyz",
            "--rules",
            str(rules_path),
            "--url",
            url,
        ],
    )

    assert result.exit_code == 0, result.output

    run_dir = _only_run_dir(tmp_path)
    assert (run_dir / "source.json").exists()
    assert (run_dir / "status.json").exists()
    assert (run_dir / "report.md").exists()

    source = SourceInfo.model_validate_json(
        (run_dir / "source.json").read_text(encoding="utf-8")
    )
    assert source.url == url
    assert source.type == "tree"
    assert source.root_id == "root"
    assert source.notion_target == {"page_id": "parent-xyz"}

    assert (run_dir / "resolution.json").exists()
    assert not (tmp_path / "output" / "resolution.json").exists()

    converted_dir = run_dir / "converted"
    assert converted_dir.is_dir()
    produced_ids = {p.stem for p in converted_dir.glob("*.json")}
    assert produced_ids == {"root", "c1", "c2", "gc1"}
    blocks = json.loads((converted_dir / "root.json").read_text(encoding="utf-8"))
    assert blocks == [{"object": "block", "type": "paragraph"}]

    status = read_status(run_dir)
    assert status.fetch.status == StepStatus.DONE
    assert status.fetch.count == 4
    assert status.convert.status == StepStatus.DONE
    assert status.convert.count == 4
    assert status.migrate.status == StepStatus.DONE
    assert status.migrate.count == 4

    report_text = (run_dir / "report.md").read_text(encoding="utf-8")
    assert report_text.startswith("# Run Report")
    assert url in report_text


@patch("confluence_to_notion.cli.convert_page")
@patch("confluence_to_notion.cli.NotionClientWrapper")
@patch("confluence_to_notion.cli.ConfluenceClient")
@patch("confluence_to_notion.cli._load_settings")
def test_migrate_tree_pages_report_has_summed_rules_usage(
    mock_settings: Any,
    mock_conf_cls: Any,
    mock_notion_cls: Any,
    mock_convert: Any,
    tmp_path: Path,
) -> None:
    """Pass-2 used_rules counts are summed across pages and rendered into report.md."""
    tree = PageTreeNode(
        id="root",
        title="Root Page",
        children=[
            PageTreeNode(id="c1", title="Child 1"),
            PageTreeNode(id="c2", title="Child 2"),
        ],
    )
    bodies = {
        "root": "<p>root body</p>",
        "c1": "<p>page A</p>",
        "c2": "<p>page B</p>",
    }
    used_rules_per_body = {
        "<p>root body</p>": {},
        "<p>page A</p>": {"rule:macro:toc": 1, "rule:macro:jira": 1},
        "<p>page B</p>": {"rule:macro:toc": 2},
    }

    mock_settings.return_value = _make_settings_mock()
    mock_conf_cls.return_value = _build_confluence_mock_with_bodies(tree, bodies)
    mock_notion_cls.return_value = _build_notion_mock()

    def _side(
        xhtml: str,
        ruleset: Any,
        *,
        page_id: str = "",
        store: Any = None,
        table_rules: Any = None,
    ) -> ConversionResult:
        return ConversionResult(
            blocks=[{"object": "block", "type": "paragraph"}],
            unresolved=[],
            used_rules=dict(used_rules_per_body.get(xhtml, {})),
        )

    mock_convert.side_effect = _side

    rules_path = tmp_path / "rules.json"
    _write_rules(rules_path)

    result = runner.invoke(
        app,
        [
            "migrate-tree-pages",
            "--root-id",
            "root",
            "--target",
            "parent-xyz",
            "--rules",
            str(rules_path),
            "--url",
            "https://example.atlassian.net/wiki/spaces/TEST/pages/root",
        ],
    )
    assert result.exit_code == 0, result.output

    run_dir = _only_run_dir(tmp_path)
    report_text = (run_dir / "report.md").read_text(encoding="utf-8")
    assert "## Rules usage" in report_text
    assert "- rule:macro:jira: 1" in report_text
    assert "- rule:macro:toc: 3" in report_text
    # Sorted alphabetically: jira before toc.
    jira_pos = report_text.index("- rule:macro:jira: 1")
    toc_pos = report_text.index("- rule:macro:toc: 3")
    assert jira_pos < toc_pos


@patch("confluence_to_notion.cli.convert_page")
@patch("confluence_to_notion.cli.NotionClientWrapper")
@patch("confluence_to_notion.cli.ConfluenceClient")
@patch("confluence_to_notion.cli._load_settings")
def test_migrate_tree_pages_report_omits_rules_usage_when_empty(
    mock_settings: Any,
    mock_conf_cls: Any,
    mock_notion_cls: Any,
    mock_convert: Any,
    tmp_path: Path,
) -> None:
    """When every Pass-2 convert_page returns empty used_rules, no Rules usage section."""
    mock_settings.return_value = _make_settings_mock()
    mock_conf_cls.return_value = _build_confluence_mock(_fixture_tree())
    mock_notion_cls.return_value = _build_notion_mock()

    mock_convert.return_value = ConversionResult(
        blocks=[{"object": "block", "type": "paragraph"}],
        unresolved=[],
        used_rules={},
    )

    rules_path = tmp_path / "rules.json"
    _write_rules(rules_path)

    result = runner.invoke(
        app,
        [
            "migrate-tree-pages",
            "--root-id",
            "root",
            "--target",
            "parent-xyz",
            "--rules",
            str(rules_path),
            "--url",
            "https://example.atlassian.net/wiki/spaces/TEST/pages/root",
        ],
    )
    assert result.exit_code == 0, result.output

    run_dir = _only_run_dir(tmp_path)
    report_text = (run_dir / "report.md").read_text(encoding="utf-8")
    assert "## Rules usage" not in report_text


@patch("confluence_to_notion.cli._prompt_table_rule")
@patch("confluence_to_notion.cli.convert_page")
@patch("confluence_to_notion.cli.NotionClientWrapper")
@patch("confluence_to_notion.cli.ConfluenceClient")
@patch("confluence_to_notion.cli._load_settings")
def test_migrate_tree_pages_url_mode_persists_table_rules_under_run_dir(
    mock_settings: Any,
    mock_conf_cls: Any,
    mock_notion_cls: Any,
    mock_convert: Any,
    mock_prompt: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """--url mode: table-rules store is saved under run_dir/rules/table-rules.json."""
    monkeypatch.setattr("confluence_to_notion.cli._stdin_is_tty", lambda: True)

    tree = PageTreeNode(id="root", title="Root Page")
    body = _table_xhtml(["Name", "Role"], [["Alice", "Dev"], ["Bob", "PM"]])
    mock_settings.return_value = _make_settings_mock()
    mock_conf_cls.return_value = _build_confluence_mock_with_bodies(tree, {"root": body})
    mock_notion_cls.return_value = _build_notion_mock()

    mock_convert.side_effect = _make_convert_side_effect(
        {
            body: [
                UnresolvedItem(
                    kind="table",
                    identifier="t-root-0",
                    source_page_id="root",
                    context_xhtml=body,
                )
            ]
        }
    )
    mock_prompt.return_value = TableRule(is_database=False)

    rules_path = tmp_path / "rules.json"
    _write_rules(rules_path)

    result = runner.invoke(
        app,
        [
            "migrate-tree-pages",
            "--root-id",
            "root",
            "--target",
            "parent-xyz",
            "--rules",
            str(rules_path),
            "--url",
            "https://example.atlassian.net/wiki/spaces/TEST/pages/root",
        ],
    )
    assert result.exit_code == 0, result.output

    run_dir = _only_run_dir(tmp_path)
    persisted = run_dir / "rules" / "table-rules.json"
    assert persisted.exists(), f"expected {persisted} to be written"
    body_loaded = TableRuleSet.model_validate_json(persisted.read_text(encoding="utf-8"))
    assert "name|role" in body_loaded.rules

    # Legacy repo-root sink must never be touched.
    assert not (tmp_path / "output" / "rules" / "table-rules.json").exists()


@patch("confluence_to_notion.cli.convert_page")
@patch("confluence_to_notion.cli.NotionClientWrapper")
@patch("confluence_to_notion.cli.ConfluenceClient")
@patch("confluence_to_notion.cli._load_settings")
def test_migrate_tree_pages_url_mode_marks_migrate_failed_on_api_error(
    mock_settings: Any,
    mock_conf_cls: Any,
    mock_notion_cls: Any,
    mock_convert: Any,
    tmp_path: Path,
) -> None:
    """--url mode: APIResponseError during Pass 2 flips migrate=FAILED in status.json
    and finalize_run still writes report.md.
    """
    mock_settings.return_value = _make_settings_mock()
    mock_conf_cls.return_value = _build_confluence_mock(
        PageTreeNode(id="root", title="Root Page")
    )
    notion_mock = _build_notion_mock()
    api_error = APIResponseError(
        code="validation_error",
        status=400,
        message="invalid block",
        headers=httpx.Headers(),
        raw_body_text="invalid block",
    )
    notion_mock.append_blocks = AsyncMock(side_effect=api_error)
    mock_notion_cls.return_value = notion_mock

    mock_convert.return_value = ConversionResult(
        page_id="",
        blocks=[{"object": "block", "type": "paragraph"}],
        unresolved=[],
    )

    rules_path = tmp_path / "rules.json"
    _write_rules(rules_path)
    url = "https://example.atlassian.net/wiki/spaces/TEST/pages/root"

    result = runner.invoke(
        app,
        [
            "migrate-tree-pages",
            "--root-id",
            "root",
            "--target",
            "parent-xyz",
            "--rules",
            str(rules_path),
            "--url",
            url,
        ],
    )
    assert result.exit_code != 0

    run_dir = _only_run_dir(tmp_path)
    status = read_status(run_dir)
    assert status.migrate.status == StepStatus.FAILED
    report_text = (run_dir / "report.md").read_text(encoding="utf-8")
    assert report_text.startswith("# Run Report")
    assert url in report_text
