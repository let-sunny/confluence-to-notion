"""Unit tests for the CLI fetch-tree command."""

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest
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


class TestFetchTreeWithUrl:
    """`cli fetch-tree --url ...` writes artifacts under output/runs/<slug>/."""

    @pytest.fixture(autouse=True)
    def _isolate_cwd(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Run tests in a tmp cwd so ``output/`` stays isolated per test."""
        monkeypatch.chdir(tmp_path)

    @patch("confluence_to_notion.cli._load_settings")
    def test_fetch_tree_url_creates_run_artifacts(
        self,
        mock_settings: Any,
        tmp_path: Path,
    ) -> None:
        mock_settings.return_value = object()
        url = "https://example.atlassian.net/wiki/spaces/ENG/pages/12345/Some-Title"

        with patch(
            "confluence_to_notion.cli.ConfluenceClient"
        ) as mock_client_cls:
            mock_client = mock_client_cls.return_value
            mock_client.collect_page_tree = AsyncMock(return_value=_fixture_tree())
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)

            result = runner.invoke(
                app,
                ["fetch-tree", "--url", url, "--root-id", "root"],
            )

        assert result.exit_code == 0, result.output

        run_dir = tmp_path / "output" / "runs" / "example-12345"
        assert run_dir.is_dir()

        # page-tree.json lives inside the run dir (not at --output default)
        tree_path = run_dir / "page-tree.json"
        assert tree_path.exists()
        tree = PageTreeNode.model_validate_json(tree_path.read_text())
        assert tree.id == "root"
        assert tree.children[1].children[0].id == "gc1"

        # source.json records url + type='tree' + root_id
        source_data = json.loads((run_dir / "source.json").read_text())
        assert source_data["url"] == url
        assert source_data["type"] == "tree"
        assert source_data["root_id"] == "root"

        # status.json shows fetch.status='done', count == total nodes (4), at set
        status = json.loads((run_dir / "status.json").read_text())
        assert status["fetch"]["status"] == "done"
        assert status["fetch"]["count"] == 4
        assert status["fetch"]["at"] is not None

        # report.md exists and names the URL
        report = (run_dir / "report.md").read_text()
        assert "# Run Report" in report
        assert url in report

    @patch("confluence_to_notion.cli._load_settings")
    def test_fetch_tree_url_failure_still_renders_report(
        self,
        mock_settings: Any,
        tmp_path: Path,
    ) -> None:
        mock_settings.return_value = object()
        url = "https://example.atlassian.net/wiki/spaces/ENG/pages/12345/Some-Title"

        response = httpx.Response(
            status_code=500,
            text="boom",
            request=httpx.Request("GET", url),
        )

        with patch(
            "confluence_to_notion.cli.ConfluenceClient"
        ) as mock_client_cls:
            mock_client = mock_client_cls.return_value
            mock_client.collect_page_tree = AsyncMock(
                side_effect=httpx.HTTPStatusError(
                    "500 Server Error", request=response.request, response=response
                )
            )
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)

            result = runner.invoke(
                app,
                ["fetch-tree", "--url", url, "--root-id", "root"],
            )

        assert result.exit_code != 0

        run_dir = tmp_path / "output" / "runs" / "example-12345"
        assert run_dir.is_dir()

        status = json.loads((run_dir / "status.json").read_text())
        assert status["fetch"]["status"] == "failed"

        # finalize_run must run in finally so report.md is present even on failure
        assert (run_dir / "report.md").exists()
