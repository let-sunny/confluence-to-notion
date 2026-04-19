"""Unit tests for the CLI convert command (--url run-dir wiring only)."""

import json
from pathlib import Path
from unittest.mock import patch

import click
import pytest
from typer.testing import CliRunner

from confluence_to_notion.agents.schemas import FinalRuleset
from confluence_to_notion.cli import app
from confluence_to_notion.converter.schemas import ConversionResult

runner = CliRunner()


@pytest.fixture(autouse=True)
def _isolate_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Run every test in a tmp cwd so ``output/`` stays isolated per test."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _fake_result() -> ConversionResult:
    return ConversionResult(
        blocks=[{"type": "paragraph", "paragraph": {"rich_text": []}}]
    )


def _seed_rules(tmp_path: Path) -> Path:
    rules_path = tmp_path / "rules.json"
    ruleset = FinalRuleset(source="proposals.json", rules=[])
    rules_path.write_text(ruleset.model_dump_json(indent=2))
    return rules_path


def _seed_samples(tmp_path: Path, names: list[str]) -> Path:
    samples_dir = tmp_path / "samples"
    samples_dir.mkdir()
    for name in names:
        (samples_dir / f"{name}.xhtml").write_text(f"<p>{name}</p>")
    return samples_dir


class TestConvertRequiresUrl:
    """`cli convert` without --url must fail and never write to output/converted/."""

    def test_convert_without_url_exits_nonzero(self, tmp_path: Path) -> None:
        rules_path = _seed_rules(tmp_path)
        samples_dir = _seed_samples(tmp_path, ["page-a", "page-b"])

        with patch(
            "confluence_to_notion.cli.convert_page",
            return_value=_fake_result(),
        ):
            result = runner.invoke(
                app,
                [
                    "convert",
                    "--rules",
                    str(rules_path),
                    "--input",
                    str(samples_dir),
                ],
                standalone_mode=False,
            )

        assert result.exit_code != 0
        assert isinstance(result.exception, click.exceptions.UsageError)
        assert "--url" in str(result.exception)
        assert not (tmp_path / "output" / "converted").exists()
        assert not (tmp_path / "output" / "runs").exists()


class TestConvertWithUrl:
    """`cli convert --url ...` writes converted artifacts under output/runs/<slug>/."""

    def test_convert_url_success_creates_run_artifacts(
        self, tmp_path: Path
    ) -> None:
        rules_path = _seed_rules(tmp_path)
        samples_dir = _seed_samples(tmp_path, ["page-a", "page-b"])
        url = (
            "https://example.atlassian.net/wiki/spaces/ENG/pages/12345/Some-Title"
        )

        with patch(
            "confluence_to_notion.cli.convert_page",
            return_value=_fake_result(),
        ):
            result = runner.invoke(
                app,
                [
                    "convert",
                    "--url",
                    url,
                    "--rules",
                    str(rules_path),
                    "--input",
                    str(samples_dir),
                ],
            )

        assert result.exit_code == 0, result.output

        run_dir = tmp_path / "output" / "runs" / "example-12345"
        assert run_dir.is_dir()

        converted_dir = run_dir / "converted"
        assert (converted_dir / "page-a.json").exists()
        assert (converted_dir / "page-b.json").exists()

        # Legacy repo-root sink must never be created in --url mode.
        assert not (tmp_path / "output" / "converted").exists()

        source_data = json.loads((run_dir / "source.json").read_text())
        assert source_data["url"] == url
        assert source_data["type"] == "page"

        status = json.loads((run_dir / "status.json").read_text())
        assert status["convert"]["status"] == "done"
        assert status["convert"]["count"] == 2
        assert status["convert"]["at"] is not None

        report = (run_dir / "report.md").read_text()
        assert "# Run Report" in report
        assert url in report

    def test_convert_url_failure_still_renders_report(
        self, tmp_path: Path
    ) -> None:
        rules_path = _seed_rules(tmp_path)
        samples_dir = _seed_samples(tmp_path, ["page-a"])
        url = (
            "https://example.atlassian.net/wiki/spaces/ENG/pages/12345/Some-Title"
        )

        with patch(
            "confluence_to_notion.cli.convert_page",
            side_effect=ValueError("boom"),
        ):
            result = runner.invoke(
                app,
                [
                    "convert",
                    "--url",
                    url,
                    "--rules",
                    str(rules_path),
                    "--input",
                    str(samples_dir),
                ],
            )

        assert result.exit_code != 0

        run_dir = tmp_path / "output" / "runs" / "example-12345"
        assert run_dir.is_dir()

        status = json.loads((run_dir / "status.json").read_text())
        assert status["convert"]["status"] == "failed"

        assert (run_dir / "report.md").exists()
        assert not (tmp_path / "output" / "converted").exists()
