"""Unit tests for the CLI migrate command."""

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
from notion_client import APIResponseError
from typer.testing import CliRunner

from confluence_to_notion.cli import _extract_title, app
from confluence_to_notion.converter.schemas import ConversionResult
from confluence_to_notion.notion.schemas import NotionPageResult

runner = CliRunner()

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "migrate"


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
                "migrate", "--rules", str(rules_file),
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
            ["migrate", "--rules", str(rules_file), "--input", str(input_dir)],
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
            ["migrate", "--rules", str(rules_file), "--input", str(input_dir), "--target", "t"],
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
            ["migrate", "--rules", str(tmp_path / "nonexistent.json"), "--input", str(input_dir)],
        )
        assert result.exit_code != 0

    def test_missing_input_dir(self, tmp_path: Path) -> None:
        rules_file = tmp_path / "rules.json"
        rules_file.write_text('{"source": "test", "rules": []}')

        result = runner.invoke(
            app,
            ["migrate", "--rules", str(rules_file), "--input", str(tmp_path / "nonexistent")],
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
            ["migrate", "--rules", str(rules_file), "--input", str(input_dir)],
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
            ["migrate", "--rules", str(rules_file), "--input", str(input_dir), "--target", "t"],
        )
        assert result.exit_code != 0
