"""Unit tests for the Resolution Store — schema and CRUD."""

import json
from pathlib import Path

import pytest

from confluence_to_notion.converter.resolution import ResolutionStore
from confluence_to_notion.converter.schemas import (
    ResolutionData,
    ResolutionEntry,
    UnresolvedItem,
)

# --- Schema tests ---


class TestResolutionEntry:
    def test_create_user_input_entry(self) -> None:
        entry = ResolutionEntry(
            resolved_by="user_input",
            value={"url": "https://issues.apache.org/jira"},
        )
        assert entry.resolved_by == "user_input"
        assert entry.confidence is None
        assert entry.resolved_at is not None

    def test_create_ai_entry_with_confidence(self) -> None:
        entry = ResolutionEntry(
            resolved_by="ai_inference",
            value={"notion_block_type": "callout"},
            confidence=0.85,
        )
        assert entry.confidence == 0.85

    def test_confidence_bounds(self) -> None:
        with pytest.raises(ValueError):
            ResolutionEntry(
                resolved_by="ai_inference",
                value={},
                confidence=1.5,
            )


class TestUnresolvedItem:
    def test_create_macro_unresolved(self) -> None:
        item = UnresolvedItem(
            kind="macro",
            identifier="custom-status-board",
            source_page_id="12345",
            context_xhtml='<ac:structured-macro ac:name="custom-status-board"/>',
        )
        assert item.kind == "macro"
        assert item.identifier == "custom-status-board"

    def test_create_jira_server_unresolved(self) -> None:
        item = UnresolvedItem(
            kind="jira_server",
            identifier="Company JIRA",
            source_page_id="67890",
        )
        assert item.kind == "jira_server"
        assert item.context_xhtml is None

    def test_create_page_link_unresolved(self) -> None:
        item = UnresolvedItem(
            kind="page_link",
            identifier="Some Page Title",
            source_page_id="11111",
        )
        assert item.kind == "page_link"


class TestResolutionData:
    def test_empty_data(self) -> None:
        data = ResolutionData()
        assert data.entries == {}

    def test_roundtrip_json(self) -> None:
        entry = ResolutionEntry(
            resolved_by="user_input",
            value={"url": "https://jira.example.com"},
        )
        data = ResolutionData(entries={"jira_server:Company JIRA": entry})
        raw = data.model_dump_json()
        restored = ResolutionData.model_validate_json(raw)
        assert restored.entries["jira_server:Company JIRA"].value == entry.value


# --- ResolutionStore tests ---


class TestResolutionStore:
    def test_load_nonexistent_returns_empty(self, tmp_path: Path) -> None:
        store = ResolutionStore(tmp_path / "resolution.json")
        assert store.data.entries == {}

    def test_load_existing_file(self, tmp_path: Path) -> None:
        path = tmp_path / "resolution.json"
        path.write_text(json.dumps({
            "entries": {
                "jira_server:ASF JIRA": {
                    "resolved_by": "user_input",
                    "value": {"url": "https://issues.apache.org/jira"},
                    "resolved_at": "2026-04-16T00:00:00",
                }
            }
        }))
        store = ResolutionStore(path)
        assert "jira_server:ASF JIRA" in store.data.entries

    def test_lookup_hit(self, tmp_path: Path) -> None:
        store = ResolutionStore(tmp_path / "resolution.json")
        store.add(
            key="macro:toc",
            resolved_by="ai_inference",
            value={"notion_block_type": "table_of_contents"},
            confidence=0.95,
        )
        result = store.lookup("macro:toc")
        assert result is not None
        assert result.value["notion_block_type"] == "table_of_contents"

    def test_lookup_miss(self, tmp_path: Path) -> None:
        store = ResolutionStore(tmp_path / "resolution.json")
        assert store.lookup("macro:nonexistent") is None

    def test_add_and_save(self, tmp_path: Path) -> None:
        path = tmp_path / "resolution.json"
        store = ResolutionStore(path)
        store.add(
            key="jira_server:My JIRA",
            resolved_by="user_input",
            value={"url": "https://jira.mycompany.com"},
        )
        store.save()

        # Reload from disk
        store2 = ResolutionStore(path)
        entry = store2.lookup("jira_server:My JIRA")
        assert entry is not None
        assert entry.value["url"] == "https://jira.mycompany.com"

    def test_add_overwrites_existing(self, tmp_path: Path) -> None:
        store = ResolutionStore(tmp_path / "resolution.json")
        store.add(key="macro:x", resolved_by="ai_inference", value={"a": 1}, confidence=0.5)
        store.add(key="macro:x", resolved_by="user_input", value={"a": 2})
        entry = store.lookup("macro:x")
        assert entry is not None
        assert entry.value == {"a": 2}
        assert entry.resolved_by == "user_input"

    def test_keys(self, tmp_path: Path) -> None:
        store = ResolutionStore(tmp_path / "resolution.json")
        store.add(key="macro:a", resolved_by="ai_inference", value={}, confidence=0.9)
        store.add(key="jira_server:b", resolved_by="user_input", value={})
        assert set(store.keys()) == {"macro:a", "jira_server:b"}
