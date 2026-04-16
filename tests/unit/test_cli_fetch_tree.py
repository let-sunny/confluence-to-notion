"""Unit tests for the CLI fetch-tree command."""

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

from typer.testing import CliRunner

from confluence_to_notion.cli import app
from confluence_to_notion.confluence.schemas import PageTreeNode

runner = CliRunner()


def _fixture_tree() -> PageTreeNode:
    """Return a sample PageTreeNode tree for mocking."""
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


class TestFetchTreeCommand:
    """Tests for the fetch-tree CLI command."""

    @patch("confluence_to_notion.cli.ConfluenceClient")
    @patch("confluence_to_notion.cli._load_settings")
    def test_fetch_tree_writes_valid_json(
        self,
        mock_settings: Any,
        mock_client_cls: Any,
        tmp_path: Path,
    ) -> None:
        """fetch-tree with --root-id writes a valid PageTreeNode JSON to output."""
        mock_client = mock_client_cls.return_value
        mock_client.collect_page_tree = AsyncMock(return_value=_fixture_tree())
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        out_file = tmp_path / "tree.json"
        result = runner.invoke(
            app,
            ["fetch-tree", "--root-id", "root", "--output", str(out_file)],
        )

        assert result.exit_code == 0, result.output
        assert out_file.exists()

        data = json.loads(out_file.read_text())
        tree = PageTreeNode.model_validate(data)
        assert tree.id == "root"
        assert len(tree.children) == 2
        assert tree.children[1].children[0].id == "gc1"

    def test_fetch_tree_missing_root_id(self) -> None:
        """fetch-tree without --root-id exits with error."""
        result = runner.invoke(app, ["fetch-tree"])

        assert result.exit_code != 0
