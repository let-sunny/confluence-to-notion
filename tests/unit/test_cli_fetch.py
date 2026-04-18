"""Unit tests for the CLI fetch command (run-dir rewiring on --url)."""

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from confluence_to_notion.cli import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def _isolate_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Run tests in a tmp cwd so ``output/`` stays isolated per test."""
    monkeypatch.chdir(tmp_path)


def _make_stub_fetch(page_ids: list[str]) -> AsyncMock:
    """Return an AsyncMock that writes one stub .xhtml per page id to out_dir."""

    async def _side_effect(out_dir: Path, **_: Any) -> list[Path]:
        out_dir.mkdir(parents=True, exist_ok=True)
        saved: list[Path] = []
        for pid in page_ids:
            fp = out_dir / f"{pid}.xhtml"
            fp.write_text(f"<p>stub {pid}</p>", encoding="utf-8")
            saved.append(fp)
        return saved

    return AsyncMock(side_effect=_side_effect)


class TestFetchWithUrl:
    """`cli fetch --url ...` writes artifacts under output/runs/<slug>/."""

    @patch("confluence_to_notion.cli._load_settings")
    def test_fetch_url_creates_run_artifacts(
        self,
        mock_settings: Any,
        tmp_path: Path,
    ) -> None:
        mock_settings.return_value = object()
        url = "https://example.atlassian.net/wiki/spaces/ENG/pages/12345/Some-Title"

        stub = _make_stub_fetch(["12345"])
        with patch(
            "confluence_to_notion.cli.ConfluenceClient"
        ) as mock_client_cls:
            mock_client_cls.return_value.fetch_samples_to_disk = stub
            result = runner.invoke(
                app,
                ["fetch", "--url", url, "--pages", "12345"],
            )

        assert result.exit_code == 0, result.output

        run_dir = tmp_path / "output" / "runs" / "example-12345"
        assert run_dir.is_dir()

        # samples/ populated
        samples = sorted(p.name for p in (run_dir / "samples").glob("*.xhtml"))
        assert samples == ["12345.xhtml"]

        # source.json records the URL + type='page'
        source_data = json.loads((run_dir / "source.json").read_text())
        assert source_data["url"] == url
        assert source_data["type"] == "page"

        # status.json shows fetch done with count + at
        status = json.loads((run_dir / "status.json").read_text())
        assert status["fetch"]["status"] == "done"
        assert status["fetch"]["count"] == 1
        assert status["fetch"]["at"] is not None

        # report.md exists and names the URL
        report = (run_dir / "report.md").read_text()
        assert "# Run Report" in report
        assert url in report

    @patch("confluence_to_notion.cli._load_settings")
    def test_fetch_url_twice_produces_suffix_dir(
        self,
        mock_settings: Any,
        tmp_path: Path,
    ) -> None:
        mock_settings.return_value = object()
        url = "https://example.atlassian.net/wiki/spaces/ENG/pages/12345/Some-Title"

        with patch(
            "confluence_to_notion.cli.ConfluenceClient"
        ) as mock_client_cls:
            mock_client_cls.return_value.fetch_samples_to_disk = _make_stub_fetch(
                ["12345"]
            )
            r1 = runner.invoke(app, ["fetch", "--url", url, "--pages", "12345"])
            assert r1.exit_code == 0, r1.output

            mock_client_cls.return_value.fetch_samples_to_disk = _make_stub_fetch(
                ["12345"]
            )
            r2 = runner.invoke(app, ["fetch", "--url", url, "--pages", "12345"])
            assert r2.exit_code == 0, r2.output

        assert (tmp_path / "output" / "runs" / "example-12345").is_dir()
        assert (tmp_path / "output" / "runs" / "example-12345-2").is_dir()

    @patch("confluence_to_notion.cli._load_settings")
    def test_fetch_url_space_source_type(
        self,
        mock_settings: Any,
        tmp_path: Path,
    ) -> None:
        mock_settings.return_value = object()
        url = "https://example.atlassian.net/wiki/spaces/ENG/overview"

        with patch(
            "confluence_to_notion.cli.ConfluenceClient"
        ) as mock_client_cls:
            mock_client_cls.return_value.fetch_samples_to_disk = _make_stub_fetch(
                ["a", "b"]
            )
            result = runner.invoke(
                app, ["fetch", "--url", url, "--space", "ENG", "--limit", "2"]
            )

        assert result.exit_code == 0, result.output
        run_dir = tmp_path / "output" / "runs" / "example-eng"
        source = json.loads((run_dir / "source.json").read_text())
        assert source["type"] == "space"
        status = json.loads((run_dir / "status.json").read_text())
        assert status["fetch"]["count"] == 2


class TestFetchWithoutUrl:
    """Omitting --url keeps legacy behavior: writes to --out-dir, no runs/."""

    @patch("confluence_to_notion.cli._load_settings")
    def test_no_url_does_not_create_runs_dir(
        self,
        mock_settings: Any,
        tmp_path: Path,
    ) -> None:
        mock_settings.return_value = object()

        out_dir = tmp_path / "samples-custom"
        with patch(
            "confluence_to_notion.cli.ConfluenceClient"
        ) as mock_client_cls:
            mock_client_cls.return_value.fetch_samples_to_disk = _make_stub_fetch(
                ["77"]
            )
            result = runner.invoke(
                app,
                ["fetch", "--pages", "77", "--out-dir", str(out_dir)],
            )

        assert result.exit_code == 0, result.output
        assert (out_dir / "77.xhtml").exists()
        # No run-dir side effects
        assert not (tmp_path / "output" / "runs").exists()
