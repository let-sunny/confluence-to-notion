"""Unit tests for the CLI migrate command."""

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import click
import httpx
import pytest
from notion_client import APIResponseError
from typer.testing import CliRunner

from confluence_to_notion.cli import _extract_title, app
from confluence_to_notion.converter.schemas import ConversionResult
from confluence_to_notion.notion.schemas import NotionPageResult

_REDISCOVER_URL = (
    "https://example.atlassian.net/wiki/spaces/ENG/pages/12345/Some-Title"
)
_RULES_PAYLOAD_EXISTING = '{"source": "existing", "rules": []}'
_RULES_PAYLOAD_NEW = '{"source": "regenerated", "rules": []}'

runner = CliRunner()

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "migrate"

_MIGRATE_URL = (
    "https://example.atlassian.net/wiki/spaces/ENG/pages/12345/Some-Title"
)


@pytest.fixture(autouse=True)
def _isolate_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Run every test in a tmp cwd so ``output/`` stays isolated per test."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _make_api_error(status: int, message: str) -> APIResponseError:
    """Create a Notion APIResponseError for testing."""
    return APIResponseError(
        code="unauthorized",
        status=status,
        message=message,
        headers=httpx.Headers(),
        raw_body_text=message,
    )


def _fake_result() -> ConversionResult:
    """Return a ConversionResult with minimal blocks for title extraction."""
    return ConversionResult(
        blocks=[
            {
                "type": "heading_1",
                "heading_1": {
                    "rich_text": [{"type": "text", "text": {"content": "Test Page Title"}}],
                },
            },
            {
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [
                        {
                            "type": "text",
                            "text": {"content": "This is a test paragraph for migration."},
                        },
                    ],
                },
            },
        ]
    )


class TestMigrateHappyPath:
    """Happy path: converts XHTML files and publishes to Notion."""

    @patch("confluence_to_notion.cli.NotionClientWrapper")
    @patch("confluence_to_notion.converter.converter.convert_page", return_value=_fake_result())
    @patch("confluence_to_notion.cli._load_settings")
    def test_migrate_success(
        self,
        mock_settings: Any,
        mock_convert: Any,
        mock_notion_cls: Any,
        tmp_path: Path,
    ) -> None:
        # Set up settings mock
        settings = mock_settings.return_value
        settings.notion_root_page_id = "root-page-id"
        settings.require_notion.return_value = None
        settings.notion_api_token = "ntn_fake_token"

        # Set up Notion client mock
        mock_client = mock_notion_cls.return_value
        mock_client.create_page = AsyncMock(
            return_value=NotionPageResult(page_id="new-page-id")
        )

        # Create a rules file
        rules_file = tmp_path / "rules.json"
        rules_file.write_text('{"source": "test", "rules": []}')

        # Copy fixture XHTML to tmp input dir
        input_dir = tmp_path / "input"
        input_dir.mkdir()
        xhtml_src = FIXTURE_DIR / "test-page.xhtml"
        (input_dir / "test-page.xhtml").write_text(xhtml_src.read_text())

        result = runner.invoke(
            app,
            [
                "migrate", "--url", _MIGRATE_URL, "--rules", str(rules_file),
                "--input", str(input_dir), "--target", "target-page-id",
            ],
        )

        assert result.exit_code == 0, result.output
        mock_convert.assert_called_once()
        mock_client.create_page.assert_called_once()
        # Verify title was extracted from heading block
        call_args = mock_client.create_page.call_args
        assert call_args.kwargs["title"] == "Test Page Title"

    @patch("confluence_to_notion.cli.NotionClientWrapper")
    @patch("confluence_to_notion.converter.converter.convert_page", return_value=_fake_result())
    @patch("confluence_to_notion.cli._load_settings")
    def test_migrate_uses_root_page_id_when_no_target(
        self,
        mock_settings: Any,
        mock_convert: Any,
        mock_notion_cls: Any,
        tmp_path: Path,
    ) -> None:
        settings = mock_settings.return_value
        settings.notion_root_page_id = "fallback-root-id"
        settings.require_notion.return_value = None
        settings.notion_api_token = "ntn_fake_token"

        mock_client = mock_notion_cls.return_value
        mock_client.create_page = AsyncMock(
            return_value=NotionPageResult(page_id="new-page-id")
        )

        rules_file = tmp_path / "rules.json"
        rules_file.write_text('{"source": "test", "rules": []}')

        input_dir = tmp_path / "input"
        input_dir.mkdir()
        (input_dir / "page.xhtml").write_text("<h1>Hello</h1>")

        result = runner.invoke(
            app,
            [
                "migrate", "--url", _MIGRATE_URL, "--rules", str(rules_file),
                "--input", str(input_dir),
            ],
        )

        assert result.exit_code == 0, result.output
        call_args = mock_client.create_page.call_args
        # parent_id should be the fallback root page id
        assert "fallback-root-id" in str(call_args)


class TestMigrateErrorHandling:
    """When create_page raises APIResponseError, that page is skipped."""

    @patch("confluence_to_notion.cli.NotionClientWrapper")
    @patch("confluence_to_notion.converter.converter.convert_page", return_value=_fake_result())
    @patch("confluence_to_notion.cli._load_settings")
    def test_api_error_skips_page_continues(
        self,
        mock_settings: Any,
        mock_convert: Any,
        mock_notion_cls: Any,
        tmp_path: Path,
    ) -> None:
        settings = mock_settings.return_value
        settings.notion_root_page_id = "root-id"
        settings.require_notion.return_value = None
        settings.notion_api_token = "ntn_fake_token"

        mock_client = mock_notion_cls.return_value
        # First call fails, second succeeds
        mock_client.create_page = AsyncMock(
            side_effect=[
                _make_api_error(400, "Bad request"),
                NotionPageResult(page_id="success-id"),
            ]
        )

        rules_file = tmp_path / "rules.json"
        rules_file.write_text('{"source": "test", "rules": []}')

        input_dir = tmp_path / "input"
        input_dir.mkdir()
        (input_dir / "a-page.xhtml").write_text("<h1>Page A</h1>")
        (input_dir / "b-page.xhtml").write_text("<h1>Page B</h1>")

        result = runner.invoke(
            app,
            [
                "migrate", "--url", _MIGRATE_URL, "--rules", str(rules_file),
                "--input", str(input_dir), "--target", "t",
            ],
        )

        # Partial failure → exit code 1
        assert result.exit_code == 1, result.output
        assert mock_client.create_page.call_count == 2
        assert "Failed: 1" in result.output
        assert "Succeeded: 1" in result.output


class TestMigrateValidation:
    """Validation: exits with error for missing rules, input dir, or target."""

    def test_missing_rules_file(self, tmp_path: Path) -> None:
        input_dir = tmp_path / "input"
        input_dir.mkdir()

        result = runner.invoke(
            app,
            [
                "migrate",
                "--rules", str(tmp_path / "nonexistent.json"),
                "--input", str(input_dir),
                "--url", _MIGRATE_URL,
            ],
        )
        assert result.exit_code != 0

    def test_missing_input_dir(self, tmp_path: Path) -> None:
        rules_file = tmp_path / "rules.json"
        rules_file.write_text('{"source": "test", "rules": []}')

        result = runner.invoke(
            app,
            [
                "migrate",
                "--rules", str(rules_file),
                "--input", str(tmp_path / "nonexistent"),
                "--url", _MIGRATE_URL,
            ],
        )
        assert result.exit_code != 0

    @patch("confluence_to_notion.cli._load_settings")
    def test_no_target_and_no_root_page_id(
        self,
        mock_settings: Any,
        tmp_path: Path,
    ) -> None:
        settings = mock_settings.return_value
        settings.notion_root_page_id = None

        rules_file = tmp_path / "rules.json"
        rules_file.write_text('{"source": "test", "rules": []}')

        input_dir = tmp_path / "input"
        input_dir.mkdir()
        (input_dir / "page.xhtml").write_text("<h1>Hello</h1>")

        result = runner.invoke(
            app,
            [
                "migrate", "--url", _MIGRATE_URL, "--rules", str(rules_file),
                "--input", str(input_dir),
            ],
        )
        assert result.exit_code != 0


class TestExtractTitle:
    """Unit tests for _extract_title helper."""

    def test_extracts_heading_1(self) -> None:
        blocks = [
            {"type": "heading_1", "heading_1": {
                "rich_text": [{"type": "text", "text": {"content": "My Title"}}],
            }},
        ]
        assert _extract_title(blocks, fallback="fallback") == "My Title"

    def test_fallback_when_no_heading(self) -> None:
        blocks = [
            {"type": "paragraph", "paragraph": {
                "rich_text": [{"type": "text", "text": {"content": "Just text"}}],
            }},
        ]
        assert _extract_title(blocks, fallback="page-123") == "page-123"

    def test_fallback_when_heading_has_empty_text(self) -> None:
        blocks = [
            {"type": "heading_2", "heading_2": {"rich_text": []}},
        ]
        assert _extract_title(blocks, fallback="empty-heading") == "empty-heading"

    def test_fallback_when_no_blocks(self) -> None:
        assert _extract_title([], fallback="no-blocks") == "no-blocks"


class TestMigrateEmptyDirectory:
    """No .xhtml files found exits with warning."""

    @patch("confluence_to_notion.cli._load_settings")
    def test_no_xhtml_files(self, mock_settings: Any, tmp_path: Path) -> None:
        settings = mock_settings.return_value
        settings.notion_root_page_id = "root-id"

        rules_file = tmp_path / "rules.json"
        rules_file.write_text('{"source": "test", "rules": []}')

        input_dir = tmp_path / "input"
        input_dir.mkdir()

        result = runner.invoke(
            app,
            [
                "migrate", "--url", _MIGRATE_URL, "--rules", str(rules_file),
                "--input", str(input_dir), "--target", "t",
            ],
        )
        assert result.exit_code != 0


class TestMigrateRequiresUrl:
    """`cli migrate` without --url must fail and never create output/runs/."""

    def test_migrate_requires_url(self, tmp_path: Path) -> None:
        rules_file = tmp_path / "rules.json"
        rules_file.write_text('{"source": "test", "rules": []}')

        input_dir = tmp_path / "input"
        input_dir.mkdir()
        (input_dir / "page.xhtml").write_text("<h1>Hello</h1>")

        result = runner.invoke(
            app,
            [
                "migrate",
                "--rules",
                str(rules_file),
                "--input",
                str(input_dir),
                "--target",
                "target-page-id",
            ],
            standalone_mode=False,
        )

        assert result.exit_code != 0
        assert isinstance(result.exception, click.exceptions.UsageError)
        assert "--url" in str(result.exception)
        assert not (tmp_path / "output" / "runs").exists()


class TestMigrateWithUrl:
    """`cli migrate --url ...` writes artifacts under output/runs/<slug>/."""

    _URL = _MIGRATE_URL

    def _seed_rules(self, tmp_path: Path) -> Path:
        rules_path = tmp_path / "rules.json"
        rules_path.write_text('{"source": "test", "rules": []}')
        return rules_path

    def _seed_samples(self, tmp_path: Path, names: list[str]) -> Path:
        input_dir = tmp_path / "input"
        input_dir.mkdir()
        for name in names:
            (input_dir / f"{name}.xhtml").write_text(f"<h1>{name}</h1>")
        return input_dir

    @patch("confluence_to_notion.cli.NotionClientWrapper")
    @patch(
        "confluence_to_notion.converter.converter.convert_page",
        return_value=_fake_result(),
    )
    @patch("confluence_to_notion.cli._load_settings")
    def test_migrate_url_success_creates_run_artifacts(
        self,
        mock_settings: Any,
        mock_convert: Any,
        mock_notion_cls: Any,
        tmp_path: Path,
    ) -> None:
        settings = mock_settings.return_value
        settings.notion_root_page_id = "root-page-id"
        settings.require_notion.return_value = None
        settings.notion_api_token = "ntn_fake_token"

        mock_client = mock_notion_cls.return_value
        mock_client.create_page = AsyncMock(
            return_value=NotionPageResult(page_id="new-page-id")
        )

        rules_path = self._seed_rules(tmp_path)
        input_dir = self._seed_samples(tmp_path, ["page-a", "page-b"])

        result = runner.invoke(
            app,
            [
                "migrate",
                "--url",
                self._URL,
                "--rules",
                str(rules_path),
                "--input",
                str(input_dir),
                "--target",
                "target-page-id",
            ],
        )

        assert result.exit_code == 0, result.output

        run_dir = tmp_path / "output" / "runs" / "example-12345"
        assert run_dir.is_dir()

        source_data = json.loads((run_dir / "source.json").read_text())
        assert source_data["url"] == self._URL
        assert source_data["type"] == "page"

        status = json.loads((run_dir / "status.json").read_text())
        assert status["migrate"]["status"] == "done"
        assert status["migrate"]["count"] == 2
        assert status["migrate"]["at"] is not None

        report = (run_dir / "report.md").read_text()
        assert "# Run Report" in report
        assert self._URL in report

        # Legacy, non-run-dir paths must not exist
        assert not (tmp_path / "output" / "converted").exists()

    @patch("confluence_to_notion.cli.NotionClientWrapper")
    @patch(
        "confluence_to_notion.converter.converter.convert_page",
        return_value=_fake_result(),
    )
    @patch("confluence_to_notion.cli._load_settings")
    def test_migrate_url_failure_still_renders_report(
        self,
        mock_settings: Any,
        mock_convert: Any,
        mock_notion_cls: Any,
        tmp_path: Path,
    ) -> None:
        settings = mock_settings.return_value
        settings.notion_root_page_id = "root-page-id"
        settings.require_notion.return_value = None
        settings.notion_api_token = "ntn_fake_token"

        mock_client = mock_notion_cls.return_value
        mock_client.create_page = AsyncMock(
            side_effect=_make_api_error(400, "Bad request")
        )

        rules_path = self._seed_rules(tmp_path)
        input_dir = self._seed_samples(tmp_path, ["page-a"])

        result = runner.invoke(
            app,
            [
                "migrate",
                "--url",
                self._URL,
                "--rules",
                str(rules_path),
                "--input",
                str(input_dir),
                "--target",
                "target-page-id",
            ],
        )

        assert result.exit_code != 0

        run_dir = tmp_path / "output" / "runs" / "example-12345"
        assert run_dir.is_dir()

        status = json.loads((run_dir / "status.json").read_text())
        assert status["migrate"]["status"] == "failed"

        assert (run_dir / "report.md").exists()


def _discover_stub_factory(
    payload: str = _RULES_PAYLOAD_NEW,
) -> Any:
    """Return a stub that mimics scripts/discover.sh writing output/rules.json."""

    def stub(run_dir: Path, url: str) -> None:
        output = Path("output")
        output.mkdir(parents=True, exist_ok=True)
        (output / "rules.json").write_text(payload)

    return stub


class TestRediscoverPolicy:
    """_migrate_url_flow: --rediscover + rules.json presence ⇒ rules_source matrix."""

    _URL = _REDISCOVER_URL
    _RUN_DIR_REL = Path("output") / "runs" / "example-12345"

    def _seed_rules(self) -> None:
        output = Path("output")
        output.mkdir(parents=True, exist_ok=True)
        (output / "rules.json").write_text(_RULES_PAYLOAD_EXISTING)

    def _source(self, tmp_path: Path) -> dict[str, Any]:
        return json.loads(
            (tmp_path / self._RUN_DIR_REL / "source.json").read_text(encoding="utf-8")
        )

    @patch("confluence_to_notion.cli._run_page_dispatch", return_value=None)
    @patch("confluence_to_notion.cli._load_settings")
    def test_rules_missing_no_flag_generates(
        self,
        mock_settings: Any,
        mock_dispatch: Any,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        settings = mock_settings.return_value
        settings.notion_root_page_id = "root"
        settings.require_notion.return_value = None
        monkeypatch.setattr(
            "confluence_to_notion.cli._run_discover", _discover_stub_factory()
        )

        result = runner.invoke(app, ["migrate", self._URL, "--dry-run"])
        assert result.exit_code == 0, result.output

        source = self._source(tmp_path)
        assert source["rules_source"] == "generated"
        assert source["rules_generated_at"] is not None

        report = (tmp_path / self._RUN_DIR_REL / "report.md").read_text()
        assert "## Rules source" in report
        assert "- source: generated" in report

        # No prev-* backup on first-time generation.
        assert not list((tmp_path / "output").glob("rules.json.prev-*"))

    @patch("confluence_to_notion.cli._run_page_dispatch", return_value=None)
    @patch("confluence_to_notion.cli._load_settings")
    def test_rules_exists_no_flag_reuses(
        self,
        mock_settings: Any,
        mock_dispatch: Any,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        settings = mock_settings.return_value
        settings.notion_root_page_id = "root"
        settings.require_notion.return_value = None
        self._seed_rules()
        called: list[bool] = []

        def _fail(run_dir: Path, url: str) -> None:
            called.append(True)
            raise AssertionError("discover must not be invoked on reuse path")

        monkeypatch.setattr("confluence_to_notion.cli._run_discover", _fail)

        result = runner.invoke(app, ["migrate", self._URL, "--dry-run"])
        assert result.exit_code == 0, result.output
        assert called == []

        source = self._source(tmp_path)
        assert source["rules_source"] == "reused"

        report = (tmp_path / self._RUN_DIR_REL / "report.md").read_text()
        assert "- source: reused" in report

        # Reuse must not create a backup.
        assert not list((tmp_path / "output").glob("rules.json.prev-*"))

    @patch("confluence_to_notion.cli._run_page_dispatch", return_value=None)
    @patch("confluence_to_notion.cli._load_settings")
    def test_rules_exists_rediscover_regenerates_with_backup(
        self,
        mock_settings: Any,
        mock_dispatch: Any,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        settings = mock_settings.return_value
        settings.notion_root_page_id = "root"
        settings.require_notion.return_value = None
        self._seed_rules()
        monkeypatch.setattr(
            "confluence_to_notion.cli._run_discover", _discover_stub_factory()
        )

        result = runner.invoke(
            app, ["migrate", self._URL, "--rediscover", "--dry-run"]
        )
        assert result.exit_code == 0, result.output

        source = self._source(tmp_path)
        assert source["rules_source"] == "regenerated"
        assert source["rules_generated_at"] is not None

        report = (tmp_path / self._RUN_DIR_REL / "report.md").read_text()
        assert "- source: regenerated" in report

        backups = list((tmp_path / "output").glob("rules.json.prev-*"))
        assert len(backups) == 1
        # Backup captures the pre-regenerate content.
        assert backups[0].read_text() == _RULES_PAYLOAD_EXISTING
        # Current rules.json is the newly generated content.
        assert (tmp_path / "output" / "rules.json").read_text() == _RULES_PAYLOAD_NEW

    @patch("confluence_to_notion.cli._run_page_dispatch", return_value=None)
    @patch("confluence_to_notion.cli._load_settings")
    def test_rules_missing_rediscover_still_generates(
        self,
        mock_settings: Any,
        mock_dispatch: Any,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        settings = mock_settings.return_value
        settings.notion_root_page_id = "root"
        settings.require_notion.return_value = None
        monkeypatch.setattr(
            "confluence_to_notion.cli._run_discover", _discover_stub_factory()
        )

        result = runner.invoke(
            app, ["migrate", self._URL, "--rediscover", "--dry-run"]
        )
        assert result.exit_code == 0, result.output

        source = self._source(tmp_path)
        # rules.json was absent: this is 'generated', not 'regenerated', even with --rediscover.
        assert source["rules_source"] == "generated"

        # No backup since there was nothing to rotate.
        assert not list((tmp_path / "output").glob("rules.json.prev-*"))

    @patch("confluence_to_notion.cli._run_page_dispatch", return_value=None)
    @patch("confluence_to_notion.cli._load_settings")
    def test_two_regenerations_keep_single_backup(
        self,
        mock_settings: Any,
        mock_dispatch: Any,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        settings = mock_settings.return_value
        settings.notion_root_page_id = "root"
        settings.require_notion.return_value = None
        self._seed_rules()
        monkeypatch.setattr(
            "confluence_to_notion.cli._run_discover", _discover_stub_factory()
        )

        first = runner.invoke(
            app, ["migrate", self._URL, "--rediscover", "--dry-run"]
        )
        assert first.exit_code == 0, first.output

        # Second --rediscover rotates the previous backup.
        second = runner.invoke(
            app, ["migrate", self._URL, "--rediscover", "--dry-run"]
        )
        assert second.exit_code == 0, second.output

        backups = list((tmp_path / "output").glob("rules.json.prev-*"))
        assert len(backups) == 1
