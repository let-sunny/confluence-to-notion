"""Unit tests for the CLI migrate-tree-pages command (2-pass migration)."""

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from notion_client import APIResponseError
from typer.testing import CliRunner

from confluence_to_notion.agents.schemas import FinalRuleset
from confluence_to_notion.cli import app
from confluence_to_notion.confluence.schemas import ConfluencePage, PageTreeNode
from confluence_to_notion.converter.resolution import ResolutionStore
from confluence_to_notion.converter.schemas import ConversionResult

runner = CliRunner()


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

    # get_page returns a ConfluencePage keyed off page id
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

    # Deterministic id assignment: first call → np-root, etc.
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
    return mock


@pytest.fixture(autouse=True)
def _isolate_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)


@patch("confluence_to_notion.cli.convert_page")
@patch("confluence_to_notion.cli.NotionClientWrapper")
@patch("confluence_to_notion.cli.ConfluenceClient")
@patch("confluence_to_notion.cli._load_settings")
def test_migrate_tree_pages_happy_path(
    mock_settings: Any,
    mock_conf_cls: Any,
    mock_notion_cls: Any,
    mock_convert: Any,
    tmp_path: Path,
) -> None:
    """Happy path: tree is walked, pages are created, bodies uploaded with mention resolution."""
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
    resolution_path = tmp_path / "resolution.json"

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
            "--resolution-out",
            str(resolution_path),
        ],
    )

    assert result.exit_code == 0, result.output

    # 4 pages created, all under correct parents
    notion_mock = mock_notion_cls.return_value
    assert notion_mock.create_subpage.await_count == 4
    # 4 bodies uploaded
    assert notion_mock.append_blocks.await_count == 4
    # 4 XHTML fetches
    conf_mock = mock_conf_cls.return_value
    assert conf_mock.get_page.await_count == 4

    # Resolution store persisted with page_link:<title> keys
    assert resolution_path.exists()
    store = ResolutionStore(resolution_path)
    for title, notion_id in [
        ("Root Page", "np-root"),
        ("Child 1", "np-c1"),
        ("Child 2", "np-c2"),
        ("Grandchild 1", "np-gc1"),
    ]:
        entry = store.lookup(f"page_link:{title}")
        assert entry is not None, f"missing entry for {title}"
        assert entry.value == {"notion_page_id": notion_id}

    # convert_page got the populated ResolutionStore so internal links resolve
    assert mock_convert.call_count == 4
    for call in mock_convert.call_args_list:
        store_arg = call.kwargs.get("store")
        assert store_arg is not None
        assert isinstance(store_arg, ResolutionStore)
        # Store must contain all page_link entries BEFORE conversion runs
        assert store_arg.lookup("page_link:Root Page") is not None
        assert store_arg.lookup("page_link:Grandchild 1") is not None

    # append_blocks invoked with notion_page_id from the create pass
    appended_ids = {
        call.kwargs.get("page_id", call.args[0] if call.args else None)
        for call in notion_mock.append_blocks.await_args_list
    }
    assert appended_ids == {"np-root", "np-c1", "np-c2", "np-gc1"}


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
            "--resolution-out",
            str(tmp_path / "resolution.json"),
        ],
    )

    assert result.exit_code == 0, result.output

    # Root is created under env-root
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
            "--resolution-out",
            str(tmp_path / "resolution.json"),
        ],
    )

    assert result.exit_code != 0
    assert "NOTION_ROOT_PAGE_ID" in result.output


@patch("confluence_to_notion.cli.convert_page")
@patch("confluence_to_notion.cli.NotionClientWrapper")
@patch("confluence_to_notion.cli.ConfluenceClient")
@patch("confluence_to_notion.cli._load_settings")
def test_migrate_tree_pages_notion_api_error_on_body_upload(
    mock_settings: Any,
    mock_conf_cls: Any,
    mock_notion_cls: Any,
    mock_convert: Any,
    tmp_path: Path,
) -> None:
    """APIResponseError during append_blocks exits non-zero with a red error."""
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
            "--resolution-out",
            str(tmp_path / "resolution.json"),
        ],
    )

    assert result.exit_code != 0
    assert "Notion" in result.output or "API" in result.output
