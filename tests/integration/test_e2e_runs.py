"""Integration test: same --url fetched twice produces two distinct run dirs.

Validates the DoD clause from #99: 'migrating the same Confluence URL twice
produces a <slug>-2 directory' for the fetch slice. No real Confluence API is
called — ConfluenceClient.fetch_samples_to_disk is mocked to write a single
stub .xhtml into whichever out_dir the CLI passes in.

Run with:
    uv run pytest -m integration tests/integration/test_e2e_runs.py
"""

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from confluence_to_notion.cli import app

runner = CliRunner()


@pytest.mark.integration
class TestFetchUrlTwice:
    """Two fetches against the same --url produce <slug>/ and <slug>-2/."""

    @patch("confluence_to_notion.cli._load_settings")
    def test_same_url_twice_creates_suffix_dir(
        self,
        mock_settings: Any,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.chdir(tmp_path)
        mock_settings.return_value = object()

        url = "https://example.atlassian.net/wiki/spaces/ENG/pages/12345/Some-Title"
        page_id = "12345"

        async def _stub_fetch(out_dir: Path, **_: Any) -> list[Path]:
            out_dir.mkdir(parents=True, exist_ok=True)
            fp = out_dir / f"{page_id}.xhtml"
            fp.write_text("<p>stub body</p>", encoding="utf-8")
            return [fp]

        with patch("confluence_to_notion.cli.ConfluenceClient") as mock_client_cls:
            mock_client_cls.return_value.fetch_samples_to_disk = AsyncMock(
                side_effect=_stub_fetch
            )
            first = runner.invoke(app, ["fetch", "--url", url, "--pages", page_id])
            assert first.exit_code == 0, first.output

            mock_client_cls.return_value.fetch_samples_to_disk = AsyncMock(
                side_effect=_stub_fetch
            )
            second = runner.invoke(app, ["fetch", "--url", url, "--pages", page_id])
            assert second.exit_code == 0, second.output

        runs_root = tmp_path / "output" / "runs"
        first_dir = runs_root / "example-12345"
        second_dir = runs_root / "example-12345-2"

        assert first_dir.is_dir()
        assert second_dir.is_dir()
        assert first_dir != second_dir

        for run_dir in (first_dir, second_dir):
            assert (run_dir / "samples" / f"{page_id}.xhtml").exists()
            assert (run_dir / "source.json").exists()
            assert (run_dir / "status.json").exists()
            assert (run_dir / "report.md").exists()

        first_source = json.loads((first_dir / "source.json").read_text())
        second_source = json.loads((second_dir / "source.json").read_text())
        assert first_source["url"] == url
        assert second_source["url"] == url
