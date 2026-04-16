"""E2E integration tests: fetch → discover → convert → migrate dry-run.

No external APIs are called. The tests use:
- Fixture XHTML pages under tests/fixtures/integration/ (simulating fetch output)
- Fixture rules.json (simulating discover pipeline output)
- Mocked NotionClientWrapper.create_page (dry-run, no real Notion writes)

Run with:
    uv run pytest -m integration
"""

import shutil
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from confluence_to_notion.agents.schemas import FinalRuleset
from confluence_to_notion.cli import app
from confluence_to_notion.converter.converter import convert_page
from confluence_to_notion.notion.schemas import NotionPageResult

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "integration"

runner = CliRunner()


@pytest.mark.integration
class TestConvertPage:
    """Step 3: call convert_page() directly to produce Notion blocks."""

    def test_page1_produces_nonempty_blocks(self) -> None:
        xhtml = (FIXTURE_DIR / "page1.xhtml").read_text()
        ruleset = FinalRuleset.model_validate_json((FIXTURE_DIR / "rules.json").read_text())

        blocks = convert_page(xhtml, ruleset).blocks

        assert len(blocks) > 0

    def test_page1_blocks_have_valid_notion_structure(self) -> None:
        xhtml = (FIXTURE_DIR / "page1.xhtml").read_text()
        ruleset = FinalRuleset.model_validate_json((FIXTURE_DIR / "rules.json").read_text())

        blocks = convert_page(xhtml, ruleset).blocks

        for block in blocks:
            assert "type" in block, f"Block missing 'type': {block}"
            block_type = block["type"]
            assert block_type in block, f"Block missing content key '{block_type}': {block}"

    def test_page1_contains_heading_and_list_blocks(self) -> None:
        xhtml = (FIXTURE_DIR / "page1.xhtml").read_text()
        ruleset = FinalRuleset.model_validate_json((FIXTURE_DIR / "rules.json").read_text())

        blocks = convert_page(xhtml, ruleset).blocks

        block_types = {b["type"] for b in blocks}
        assert any(t.startswith("heading") for t in block_types), "Expected at least one heading"
        assert "bulleted_list_item" in block_types, "Expected bulleted list items from page1.xhtml"

    def test_page2_produces_nonempty_blocks(self) -> None:
        xhtml = (FIXTURE_DIR / "page2.xhtml").read_text()
        ruleset = FinalRuleset.model_validate_json((FIXTURE_DIR / "rules.json").read_text())

        blocks = convert_page(xhtml, ruleset).blocks

        assert len(blocks) > 0

    def test_page2_contains_numbered_list_items(self) -> None:
        xhtml = (FIXTURE_DIR / "page2.xhtml").read_text()
        ruleset = FinalRuleset.model_validate_json((FIXTURE_DIR / "rules.json").read_text())

        blocks = convert_page(xhtml, ruleset).blocks

        list_items = [b for b in blocks if b["type"] == "numbered_list_item"]
        assert list_items, "Expected numbered list items in page2.xhtml"


@pytest.mark.integration
class TestMigrateDryRun:
    """Steps 4-5: mock NotionClientWrapper.create_page and invoke the migrate CLI."""

    @patch("confluence_to_notion.cli.NotionClientWrapper")
    @patch("confluence_to_notion.cli._load_settings")
    def test_create_page_called_once_per_xhtml(
        self,
        mock_load_settings: Any,
        mock_notion_cls: Any,
        tmp_path: Path,
    ) -> None:
        """create_page is called exactly once for each XHTML file in the input dir."""
        parent_id = "test-parent-page-id"
        _setup_settings(mock_load_settings, parent_id)
        mock_client = _setup_notion_client(mock_notion_cls)

        input_dir = _copy_fixtures(tmp_path, "page1.xhtml", "page2.xhtml")
        rules_file = _copy_rules(tmp_path)

        args = [
            "migrate", "--rules", str(rules_file), "--input", str(input_dir), "--target", parent_id
        ]
        result = runner.invoke(app, args)

        assert result.exit_code == 0, result.output
        assert mock_client.create_page.call_count == 2

    @patch("confluence_to_notion.cli.NotionClientWrapper")
    @patch("confluence_to_notion.cli._load_settings")
    def test_create_page_uses_correct_parent_id(
        self,
        mock_load_settings: Any,
        mock_notion_cls: Any,
        tmp_path: Path,
    ) -> None:
        """Each create_page call receives the parent_id from --target."""
        parent_id = "expected-parent-page-id"
        _setup_settings(mock_load_settings, parent_id)
        mock_client = _setup_notion_client(mock_notion_cls)

        input_dir = _copy_fixtures(tmp_path, "page1.xhtml")
        rules_file = _copy_rules(tmp_path)

        args = [
            "migrate", "--rules", str(rules_file), "--input", str(input_dir), "--target", parent_id
        ]
        result = runner.invoke(app, args)

        assert result.exit_code == 0, result.output
        call_kwargs = mock_client.create_page.call_args.kwargs
        assert call_kwargs["parent_id"] == parent_id

    @patch("confluence_to_notion.cli.NotionClientWrapper")
    @patch("confluence_to_notion.cli._load_settings")
    def test_create_page_receives_nonempty_valid_blocks(
        self,
        mock_load_settings: Any,
        mock_notion_cls: Any,
        tmp_path: Path,
    ) -> None:
        """Blocks passed to create_page are non-empty and have valid Notion structure."""
        parent_id = "test-parent-id"
        _setup_settings(mock_load_settings, parent_id)
        mock_client = _setup_notion_client(mock_notion_cls)

        input_dir = _copy_fixtures(tmp_path, "page1.xhtml")
        rules_file = _copy_rules(tmp_path)

        args = [
            "migrate", "--rules", str(rules_file), "--input", str(input_dir), "--target", parent_id
        ]
        result = runner.invoke(app, args)

        assert result.exit_code == 0, result.output
        call_kwargs = mock_client.create_page.call_args.kwargs
        blocks: list[dict[str, Any]] = call_kwargs["blocks"]
        assert blocks, "Blocks passed to create_page must be non-empty"
        for block in blocks:
            assert "type" in block, f"Block missing 'type': {block}"
            block_type = block["type"]
            assert block_type in block, f"Block missing content key '{block_type}': {block}"

    @patch("confluence_to_notion.cli.NotionClientWrapper")
    @patch("confluence_to_notion.cli._load_settings")
    def test_create_page_title_extracted_from_h1(
        self,
        mock_load_settings: Any,
        mock_notion_cls: Any,
        tmp_path: Path,
    ) -> None:
        """Title passed to create_page is extracted from the first <h1> of page1.xhtml."""
        parent_id = "test-parent-id"
        _setup_settings(mock_load_settings, parent_id)
        mock_client = _setup_notion_client(mock_notion_cls)

        input_dir = _copy_fixtures(tmp_path, "page1.xhtml")
        rules_file = _copy_rules(tmp_path)

        args = [
            "migrate", "--rules", str(rules_file), "--input", str(input_dir), "--target", parent_id
        ]
        result = runner.invoke(app, args)

        assert result.exit_code == 0, result.output
        call_kwargs = mock_client.create_page.call_args.kwargs
        assert call_kwargs["title"] == "Integration Test Page 1"


# --- Helpers ---


def _setup_settings(mock_load_settings: Any, parent_id: str) -> Any:
    settings = mock_load_settings.return_value
    settings.notion_root_page_id = parent_id
    settings.require_notion.return_value = None
    settings.notion_api_token = "ntn_fake"
    return settings


def _setup_notion_client(mock_notion_cls: Any) -> Any:
    mock_client = mock_notion_cls.return_value
    mock_client.create_page = AsyncMock(return_value=NotionPageResult(page_id="created-id"))
    return mock_client


def _copy_fixtures(tmp_path: Path, *filenames: str) -> Path:
    input_dir = tmp_path / "input"
    input_dir.mkdir(exist_ok=True)
    for fname in filenames:
        shutil.copy(FIXTURE_DIR / fname, input_dir / fname)
    return input_dir


def _copy_rules(tmp_path: Path) -> Path:
    rules_file = tmp_path / "rules.json"
    shutil.copy(FIXTURE_DIR / "rules.json", rules_file)
    return rules_file
