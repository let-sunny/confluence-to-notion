"""E2E integration tests for the single-entry ``c2n migrate <url>`` command.

The tests pin down the URL → dispatch branching for #122:

1. New-Cloud page URL    → single-page fetch + convert + one ``create_page``.
2. Legacy /display URL   → same single-page dispatch, identifier is the decoded title.
3. Space-root URL        → tree/space fan-out + ``resolution.json`` written.
4. ``--dry-run``         → no Notion write methods called.
5. Pre-existing rules    → ``_run_discover`` skipped; absent → ``_run_discover`` called.

Every external side effect is mocked:
- ``ConfluenceClient`` — stub ``fetch_samples_to_disk``, ``get_page``,
  ``collect_page_tree``, ``list_pages_in_space`` so no network is hit.
- ``NotionClientWrapper`` — ``create_page`` / ``create_subpage`` / ``append_blocks``
  / ``create_database`` are ``AsyncMock``s the tests inspect.
- ``_run_discover`` — patched with ``create=True`` so pre-impl runs also no-op.

Run with:
    uv run pytest -m integration tests/integration/test_e2e_migrate_url.py
"""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from confluence_to_notion.cli import app
from confluence_to_notion.confluence.schemas import (
    ConfluencePage,
    ConfluencePageSummary,
    PageTreeNode,
)

runner = CliRunner()

STUB_XHTML = (
    "<h1>Stub Page</h1>"
    "<p>body text for integration test</p>"
    "<ul><li>one</li><li>two</li></ul>"
)

RULES_JSON = """{
  "source": "tests/fixtures/integration/rules.json",
  "rules": [
    {
      "rule_id": "rule:element:heading",
      "source_pattern_id": "element:heading",
      "source_description": "HTML heading tags",
      "notion_block_type": "heading_1",
      "mapping_description": "h1->heading_1",
      "example_input": "<h1>Title</h1>",
      "example_output": {
        "type": "heading_1",
        "heading_1": {"rich_text": [{"type": "text", "text": {"content": "T"}}]}
      },
      "confidence": "high",
      "enabled": true
    },
    {
      "rule_id": "rule:element:paragraph",
      "source_pattern_id": "element:paragraph",
      "source_description": "Paragraphs",
      "notion_block_type": "paragraph",
      "mapping_description": "p->paragraph",
      "example_input": "<p>x</p>",
      "example_output": {
        "type": "paragraph",
        "paragraph": {"rich_text": [{"type": "text", "text": {"content": "x"}}]}
      },
      "confidence": "high",
      "enabled": true
    },
    {
      "rule_id": "rule:element:list",
      "source_pattern_id": "element:list",
      "source_description": "Lists",
      "notion_block_type": "bulleted_list_item",
      "mapping_description": "ul li -> bulleted_list_item",
      "example_input": "<ul><li>x</li></ul>",
      "example_output": {
        "type": "bulleted_list_item",
        "bulleted_list_item": {
          "rich_text": [{"type": "text", "text": {"content": "x"}}]
        }
      },
      "confidence": "high",
      "enabled": true
    }
  ]
}
"""


def _seed_rules(tmp_path: Path) -> Path:
    """Drop a valid ``output/rules.json`` under ``tmp_path`` and return it."""
    rules_path = tmp_path / "output" / "rules.json"
    rules_path.parent.mkdir(parents=True, exist_ok=True)
    rules_path.write_text(RULES_JSON, encoding="utf-8")
    return rules_path


def _setup_settings(mock_load_settings: Any, parent_id: str = "notion-root") -> Any:
    settings = mock_load_settings.return_value
    settings.notion_root_page_id = parent_id
    settings.notion_api_token = "ntn_fake"
    settings.confluence_base_url = "https://example.atlassian.net/wiki"
    settings.confluence_auth_available = False
    settings.require_notion.return_value = None
    return settings


def _stub_confluence_client(page_ids: list[str] | None = None) -> MagicMock:
    """Build a MagicMock ConfluenceClient with every method a URL-dispatch impl may call."""
    ids = page_ids or ["12345"]

    async def _fetch_samples(out_dir: Path, **kwargs: Any) -> list[Path]:
        requested: list[str] | None = kwargs.get("page_ids")
        written: list[Path] = []
        target_ids = requested if requested else ids
        out_dir.mkdir(parents=True, exist_ok=True)
        for pid in target_ids:
            fp = out_dir / f"{pid}.xhtml"
            fp.write_text(STUB_XHTML, encoding="utf-8")
            written.append(fp)
        return written

    tree = PageTreeNode(
        id="root-1",
        title="Space Home",
        children=[
            PageTreeNode(id="child-1", title="Child One", children=[]),
            PageTreeNode(id="child-2", title="Child Two", children=[]),
        ],
    )

    def _page(pid: str, title: str) -> ConfluencePage:
        return ConfluencePage(
            id=pid,
            title=title,
            space_key="ENG",
            version=1,
            storage_body=STUB_XHTML,
            created_at=datetime(2025, 1, 1, tzinfo=UTC),
        )

    instance = MagicMock()
    instance.__aenter__ = AsyncMock(return_value=instance)
    instance.__aexit__ = AsyncMock(return_value=None)
    instance.fetch_samples_to_disk = AsyncMock(side_effect=_fetch_samples)
    instance.collect_page_tree = AsyncMock(return_value=tree)
    instance.get_page = AsyncMock(
        side_effect=lambda pid: _page(pid, f"Title for {pid}")
    )
    instance.get_pages = AsyncMock(
        side_effect=lambda ids_: [_page(pid, f"Title for {pid}") for pid in ids_]
    )
    instance.list_pages_in_space = AsyncMock(
        return_value=[
            ConfluencePageSummary(id="root-1", title="Space Home"),
        ]
    )
    instance.get_child_pages = AsyncMock(
        return_value=[
            ConfluencePageSummary(id="child-1", title="Child One"),
            ConfluencePageSummary(id="child-2", title="Child Two"),
        ]
    )

    cls_mock = MagicMock(return_value=instance)
    return cls_mock


def _stub_notion_client() -> MagicMock:
    instance = MagicMock()
    instance.create_page = AsyncMock(return_value=MagicMock(page_id="notion-page-id"))
    instance.create_subpage = AsyncMock(
        side_effect=lambda parent_id, title: f"notion-{title}"
    )
    instance.append_blocks = AsyncMock(return_value=None)
    instance.create_database = AsyncMock(return_value="notion-db-id")
    instance.create_page_tree = AsyncMock(return_value={"Child One": "notion-1"})
    cls_mock = MagicMock(return_value=instance)
    return cls_mock


@pytest.mark.integration
class TestMigrateSinglePageUrl:
    """A new-Cloud page URL dispatches to the single-page flow."""

    def test_new_cloud_page_url_invokes_create_page_once(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        _seed_rules(tmp_path)

        url = "https://example.atlassian.net/wiki/spaces/ENG/pages/12345/Stub-Page"
        conf_cls = _stub_confluence_client(page_ids=["12345"])
        notion_cls = _stub_notion_client()

        with (
            patch("confluence_to_notion.cli._load_settings") as load_settings,
            patch("confluence_to_notion.cli.ConfluenceClient", conf_cls),
            patch("confluence_to_notion.cli.NotionClientWrapper", notion_cls),
            patch(
                "confluence_to_notion.cli._run_discover", create=True
            ) as run_discover,
        ):
            _setup_settings(load_settings)
            result = runner.invoke(app, ["migrate", url])

        assert result.exit_code == 0, result.output
        notion_instance = notion_cls.return_value
        assert notion_instance.create_page.await_count == 1
        # Single-page dispatch MUST NOT walk the tree.
        conf_instance = conf_cls.return_value
        assert conf_instance.collect_page_tree.await_count == 0
        # Rules already exist so discover is skipped.
        run_discover.assert_not_called()

    def test_new_cloud_page_url_writes_run_artifacts(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        _seed_rules(tmp_path)

        url = "https://example.atlassian.net/wiki/spaces/ENG/pages/12345/Stub-Page"
        conf_cls = _stub_confluence_client(page_ids=["12345"])
        notion_cls = _stub_notion_client()

        with (
            patch("confluence_to_notion.cli._load_settings") as load_settings,
            patch("confluence_to_notion.cli.ConfluenceClient", conf_cls),
            patch("confluence_to_notion.cli.NotionClientWrapper", notion_cls),
            patch("confluence_to_notion.cli._run_discover", create=True),
        ):
            _setup_settings(load_settings)
            result = runner.invoke(app, ["migrate", url])

        assert result.exit_code == 0, result.output
        runs_root = tmp_path / "output" / "runs"
        run_dirs = list(runs_root.iterdir())
        assert len(run_dirs) == 1, f"expected one run dir, got {run_dirs}"
        run_dir = run_dirs[0]
        assert (run_dir / "status.json").exists()
        assert (run_dir / "source.json").exists()
        assert (run_dir / "report.md").exists()


@pytest.mark.integration
class TestMigrateLegacyDisplayUrl:
    """Legacy ``/display/<SPACE>/<Title>`` URLs follow the single-page dispatch."""

    def test_display_url_single_page_dispatch(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        _seed_rules(tmp_path)

        url = "https://example.atlassian.net/wiki/display/ENG/Some+Title"
        conf_cls = _stub_confluence_client(page_ids=["Some Title"])
        notion_cls = _stub_notion_client()

        with (
            patch("confluence_to_notion.cli._load_settings") as load_settings,
            patch("confluence_to_notion.cli.ConfluenceClient", conf_cls),
            patch("confluence_to_notion.cli.NotionClientWrapper", notion_cls),
            patch("confluence_to_notion.cli._run_discover", create=True),
        ):
            _setup_settings(load_settings)
            result = runner.invoke(app, ["migrate", url])

        assert result.exit_code == 0, result.output
        notion_instance = notion_cls.return_value
        # Single-page dispatch: one create_page (or append_blocks) write.
        total_writes = (
            notion_instance.create_page.await_count
            + notion_instance.create_subpage.await_count
        )
        assert total_writes == 1
        conf_instance = conf_cls.return_value
        # Tree fan-out MUST NOT run for /display/ single-page URLs.
        assert conf_instance.collect_page_tree.await_count == 0


@pytest.mark.integration
class TestMigrateSpaceUrl:
    """A space-root URL dispatches to the tree/space fan-out flow."""

    def test_space_url_fan_out_creates_multiple_pages(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        _seed_rules(tmp_path)

        url = "https://example.atlassian.net/wiki/spaces/ENG"
        conf_cls = _stub_confluence_client()
        notion_cls = _stub_notion_client()

        with (
            patch("confluence_to_notion.cli._load_settings") as load_settings,
            patch("confluence_to_notion.cli.ConfluenceClient", conf_cls),
            patch("confluence_to_notion.cli.NotionClientWrapper", notion_cls),
            patch("confluence_to_notion.cli._run_discover", create=True),
        ):
            _setup_settings(load_settings)
            result = runner.invoke(app, ["migrate", url])

        assert result.exit_code == 0, result.output
        conf_instance = conf_cls.return_value
        # Fan-out must walk the tree, producing N Notion writes (N == root + 2 children).
        assert conf_instance.collect_page_tree.await_count >= 1
        notion_instance = notion_cls.return_value
        total_page_writes = (
            notion_instance.create_subpage.await_count
            + notion_instance.create_page.await_count
        )
        assert total_page_writes >= 2, (
            f"fan-out should create multiple pages, got {total_page_writes}"
        )

        runs_root = tmp_path / "output" / "runs"
        run_dirs = list(runs_root.iterdir())
        assert len(run_dirs) == 1
        assert (run_dirs[0] / "resolution.json").exists()


@pytest.mark.integration
class TestMigrateDryRun:
    """``--dry-run`` skips every Notion write."""

    def test_dry_run_single_page_skips_notion_writes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        _seed_rules(tmp_path)

        url = "https://example.atlassian.net/wiki/spaces/ENG/pages/12345/Stub"
        conf_cls = _stub_confluence_client(page_ids=["12345"])
        notion_cls = _stub_notion_client()

        with (
            patch("confluence_to_notion.cli._load_settings") as load_settings,
            patch("confluence_to_notion.cli.ConfluenceClient", conf_cls),
            patch("confluence_to_notion.cli.NotionClientWrapper", notion_cls),
            patch("confluence_to_notion.cli._run_discover", create=True),
        ):
            _setup_settings(load_settings)
            result = runner.invoke(app, ["migrate", url, "--dry-run"])

        assert result.exit_code == 0, result.output
        notion_instance = notion_cls.return_value
        assert notion_instance.create_page.await_count == 0
        assert notion_instance.create_subpage.await_count == 0
        assert notion_instance.append_blocks.await_count == 0
        assert notion_instance.create_database.await_count == 0

        # Conversion artifacts still land on disk so the operator can inspect them.
        runs_root = tmp_path / "output" / "runs"
        run_dirs = list(runs_root.iterdir())
        assert len(run_dirs) == 1
        run_dir = run_dirs[0]
        assert (run_dir / "status.json").exists()
        assert (run_dir / "report.md").exists()
        converted = run_dir / "converted"
        assert converted.exists()
        assert any(converted.glob("*.json"))

    def test_dry_run_space_skips_notion_writes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        _seed_rules(tmp_path)

        url = "https://example.atlassian.net/wiki/spaces/ENG"
        conf_cls = _stub_confluence_client()
        notion_cls = _stub_notion_client()

        with (
            patch("confluence_to_notion.cli._load_settings") as load_settings,
            patch("confluence_to_notion.cli.ConfluenceClient", conf_cls),
            patch("confluence_to_notion.cli.NotionClientWrapper", notion_cls),
            patch("confluence_to_notion.cli._run_discover", create=True),
        ):
            _setup_settings(load_settings)
            result = runner.invoke(app, ["migrate", url, "--dry-run"])

        assert result.exit_code == 0, result.output
        notion_instance = notion_cls.return_value
        assert notion_instance.create_page.await_count == 0
        assert notion_instance.create_subpage.await_count == 0
        assert notion_instance.append_blocks.await_count == 0
        assert notion_instance.create_database.await_count == 0


@pytest.mark.integration
class TestMigrateDiscoverGating:
    """Pre-existing ``output/rules.json`` gates the discover shell-out."""

    def test_rules_present_skips_discover(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        _seed_rules(tmp_path)

        url = "https://example.atlassian.net/wiki/spaces/ENG/pages/12345/Stub"
        conf_cls = _stub_confluence_client(page_ids=["12345"])
        notion_cls = _stub_notion_client()

        with (
            patch("confluence_to_notion.cli._load_settings") as load_settings,
            patch("confluence_to_notion.cli.ConfluenceClient", conf_cls),
            patch("confluence_to_notion.cli.NotionClientWrapper", notion_cls),
            patch(
                "confluence_to_notion.cli._run_discover", create=True
            ) as run_discover,
        ):
            _setup_settings(load_settings)
            result = runner.invoke(app, ["migrate", url])

        assert result.exit_code == 0, result.output
        run_discover.assert_not_called()

    def test_rules_absent_triggers_discover(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        # NOTE: intentionally do NOT seed output/rules.json.

        url = "https://example.atlassian.net/wiki/spaces/ENG/pages/12345/Stub"
        conf_cls = _stub_confluence_client(page_ids=["12345"])
        notion_cls = _stub_notion_client()

        def _fake_discover(*_args: Any, **_kwargs: Any) -> None:
            # Simulate the real shell-out by dropping the rules file at the
            # expected location so downstream convert steps can proceed.
            _seed_rules(tmp_path)

        with (
            patch("confluence_to_notion.cli._load_settings") as load_settings,
            patch("confluence_to_notion.cli.ConfluenceClient", conf_cls),
            patch("confluence_to_notion.cli.NotionClientWrapper", notion_cls),
            patch(
                "confluence_to_notion.cli._run_discover",
                create=True,
                side_effect=_fake_discover,
            ) as run_discover,
        ):
            _setup_settings(load_settings)
            result = runner.invoke(app, ["migrate", url])

        assert result.exit_code == 0, result.output
        assert run_discover.call_count == 1
