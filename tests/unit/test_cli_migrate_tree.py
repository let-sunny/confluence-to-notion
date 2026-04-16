"""Unit tests for the CLI migrate-tree command."""

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from notion_client import APIResponseError
from typer.testing import CliRunner

from confluence_to_notion.cli import app
from confluence_to_notion.confluence.schemas import PageTreeNode
from confluence_to_notion.converter.resolution import ResolutionStore

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


def _write_tree(path: Path, tree: PageTreeNode) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(tree.model_dump_json(indent=2) + "\n", encoding="utf-8")


def _make_settings_mock(
    *,
    notion_root_page_id: str | None = "env-root",
    notion_api_token: str | None = "ntn_fake",
) -> Any:
    from types import SimpleNamespace

    def _require_notion() -> None:
        if not notion_api_token:
            raise ValueError("NOTION_API_TOKEN is required. Set it in .env")
        if not notion_root_page_id:
            raise ValueError("NOTION_ROOT_PAGE_ID is required. Set it in .env")

    return SimpleNamespace(
        notion_api_token=notion_api_token,
        notion_root_page_id=notion_root_page_id,
        require_notion=_require_notion,
    )


@patch("confluence_to_notion.cli.NotionClientWrapper")
@patch("confluence_to_notion.cli._load_settings")
def test_migrate_tree_creates_hierarchy_and_writes_mapping(
    mock_settings: Any,
    mock_client_cls: Any,
    tmp_path: Path,
) -> None:
    """migrate-tree walks the tree, calls create_page_tree, and persists mappings."""
    mock_settings.return_value = _make_settings_mock()

    mock_client = mock_client_cls.return_value
    mapping = {
        "Root Page": "np-root",
        "Child 1": "np-c1",
        "Child 2": "np-c2",
        "Grandchild 1": "np-gc1",
    }
    mock_client.create_page_tree = AsyncMock(return_value=mapping)

    tree_path = tmp_path / "page-tree.json"
    _write_tree(tree_path, _fixture_tree())
    resolution_path = tmp_path / "resolution.json"

    result = runner.invoke(
        app,
        [
            "migrate-tree",
            "--tree",
            str(tree_path),
            "--target",
            "parent-xyz",
            "--resolution-out",
            str(resolution_path),
        ],
    )

    assert result.exit_code == 0, result.output

    mock_client.create_page_tree.assert_awaited_once()
    call_kwargs = mock_client.create_page_tree.await_args.kwargs
    call_args = mock_client.create_page_tree.await_args.args
    passed_parent = call_kwargs.get("parent_id", call_args[0] if call_args else None)
    passed_tree = call_kwargs.get(
        "tree", call_args[1] if len(call_args) > 1 else None
    )
    assert passed_parent == "parent-xyz"
    assert isinstance(passed_tree, PageTreeNode)
    assert passed_tree.id == "root"
    assert passed_tree.children[1].children[0].id == "gc1"

    assert resolution_path.exists()
    store = ResolutionStore(resolution_path)
    for title, notion_page_id in mapping.items():
        entry = store.lookup(f"page_link:{title}")
        assert entry is not None, f"missing entry for {title}"
        assert entry.resolved_by == "notion_migration"
        assert entry.value == {"notion_page_id": notion_page_id}
    child2 = store.lookup("page_link:Child 2")
    assert child2 is not None
    assert child2.value["notion_page_id"] == "np-c2"


@patch("confluence_to_notion.cli.NotionClientWrapper")
@patch("confluence_to_notion.cli._load_settings")
def test_migrate_tree_uses_settings_root_when_target_omitted(
    mock_settings: Any,
    mock_client_cls: Any,
    tmp_path: Path,
) -> None:
    """--target is optional when NOTION_ROOT_PAGE_ID is configured."""
    mock_settings.return_value = _make_settings_mock(notion_root_page_id="env-root")

    mock_client = mock_client_cls.return_value
    mock_client.create_page_tree = AsyncMock(return_value={"Root Page": "np-root"})

    tree_path = tmp_path / "page-tree.json"
    _write_tree(tree_path, PageTreeNode(id="root", title="Root Page"))
    resolution_path = tmp_path / "resolution.json"

    result = runner.invoke(
        app,
        [
            "migrate-tree",
            "--tree",
            str(tree_path),
            "--resolution-out",
            str(resolution_path),
        ],
    )

    assert result.exit_code == 0, result.output
    call_kwargs = mock_client.create_page_tree.await_args.kwargs
    call_args = mock_client.create_page_tree.await_args.args
    passed_parent = call_kwargs.get("parent_id", call_args[0] if call_args else None)
    assert passed_parent == "env-root"


@patch("confluence_to_notion.cli.NotionClientWrapper")
@patch("confluence_to_notion.cli._load_settings")
def test_migrate_tree_missing_target_and_env_exits(
    mock_settings: Any,
    mock_client_cls: Any,
    tmp_path: Path,
) -> None:
    """Without --target and NOTION_ROOT_PAGE_ID the command must fail with a hint."""
    mock_settings.return_value = _make_settings_mock(notion_root_page_id=None)

    tree_path = tmp_path / "page-tree.json"
    _write_tree(tree_path, PageTreeNode(id="root", title="Root Page"))

    result = runner.invoke(
        app,
        [
            "migrate-tree",
            "--tree",
            str(tree_path),
            "--resolution-out",
            str(tmp_path / "resolution.json"),
        ],
    )

    assert result.exit_code != 0
    assert "NOTION_ROOT_PAGE_ID" in result.output


@patch("confluence_to_notion.cli.NotionClientWrapper")
@patch("confluence_to_notion.cli._load_settings")
def test_migrate_tree_missing_tree_file_exits(
    mock_settings: Any,
    mock_client_cls: Any,
    tmp_path: Path,
) -> None:
    """A missing tree JSON path exits with a non-zero code."""
    mock_settings.return_value = _make_settings_mock()

    result = runner.invoke(
        app,
        [
            "migrate-tree",
            "--tree",
            str(tmp_path / "does-not-exist.json"),
            "--target",
            "parent-xyz",
            "--resolution-out",
            str(tmp_path / "resolution.json"),
        ],
    )

    assert result.exit_code != 0


@patch("confluence_to_notion.cli.NotionClientWrapper")
@patch("confluence_to_notion.cli._load_settings")
def test_migrate_tree_handles_notion_api_error(
    mock_settings: Any,
    mock_client_cls: Any,
    tmp_path: Path,
) -> None:
    """APIResponseError from Notion is reported with a red error and exit 1."""
    mock_settings.return_value = _make_settings_mock()

    mock_client = mock_client_cls.return_value
    api_error = APIResponseError(
        code="unauthorized",
        status=401,
        message="Unauthorized",
        headers=httpx.Headers(),
        raw_body_text="Unauthorized",
    )
    mock_client.create_page_tree = AsyncMock(side_effect=api_error)

    tree_path = tmp_path / "page-tree.json"
    _write_tree(tree_path, _fixture_tree())

    result = runner.invoke(
        app,
        [
            "migrate-tree",
            "--tree",
            str(tree_path),
            "--target",
            "parent-xyz",
            "--resolution-out",
            str(tmp_path / "resolution.json"),
        ],
    )

    assert result.exit_code != 0


@pytest.fixture(autouse=True)
def _isolate_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Run tests in a temporary cwd so default output paths don't collide."""
    monkeypatch.chdir(tmp_path)
