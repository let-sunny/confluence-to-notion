"""Unit tests for the Table Rule store — schemas, extractors, and heuristics."""

import json
from pathlib import Path

import pytest

from confluence_to_notion.converter.schemas import TableRule, TableRuleSet


class TestTableRule:
    def test_defaults(self) -> None:
        rule = TableRule(is_database=False)
        assert rule.is_database is False
        assert rule.title_column is None
        assert rule.column_types is None

    def test_with_column_types(self) -> None:
        rule = TableRule(
            is_database=True,
            title_column="Name",
            column_types={
                "Name": "title",
                "Owner": "people",
                "Due": "date",
                "Status": "select",
                "Notes": "rich_text",
            },
        )
        assert rule.title_column == "Name"
        assert rule.column_types is not None
        assert rule.column_types["Owner"] == "people"

    def test_invalid_column_type(self) -> None:
        with pytest.raises(ValueError):
            TableRule(
                is_database=True,
                title_column="Name",
                column_types={"Name": "title", "X": "not_a_real_type"},  # type: ignore[dict-item]
            )


class TestTableRuleSet:
    def test_empty(self) -> None:
        rs = TableRuleSet()
        assert rs.rules == {}

    def test_rejects_empty_signature_key(self) -> None:
        with pytest.raises(ValueError):
            TableRuleSet(rules={"": TableRule(is_database=False)})

    def test_title_column_must_be_in_signature(self) -> None:
        with pytest.raises(ValueError):
            TableRuleSet(
                rules={
                    "name|owner|due": TableRule(
                        is_database=True,
                        title_column="Missing",
                        column_types={"Name": "title"},
                    ),
                }
            )

    def test_title_column_in_signature_ok(self) -> None:
        rs = TableRuleSet(
            rules={
                "name|owner|due": TableRule(
                    is_database=True,
                    title_column="name",
                    column_types={
                        "name": "title",
                        "owner": "people",
                        "due": "date",
                    },
                ),
            }
        )
        assert rs.rules["name|owner|due"].title_column == "name"

    def test_roundtrip_preserves_key_order(self) -> None:
        ordered_keys = [
            "alpha|beta|gamma",
            "name|owner|status",
            "a|b",
        ]
        rules = {
            key: TableRule(is_database=False) for key in ordered_keys
        }
        rs = TableRuleSet(rules=rules)
        raw = rs.model_dump_json()
        restored = TableRuleSet.model_validate_json(raw)
        assert list(restored.rules.keys()) == ordered_keys

        # Also verify underlying JSON preserves order (Python 3.7+ dict guarantees
        # insertion order; json.loads mirrors that).
        parsed = json.loads(raw)
        assert list(parsed["rules"].keys()) == ordered_keys


# --- Tests for extractors and heuristics in converter/table_rules.py ---


class TestNormalizeHeaderSignature:
    def test_basic(self) -> None:
        from confluence_to_notion.converter.table_rules import normalize_header_signature

        assert normalize_header_signature(["Name", "Owner", "Due"]) == "name|owner|due"

    def test_strip_and_lowercase(self) -> None:
        from confluence_to_notion.converter.table_rules import normalize_header_signature

        assert (
            normalize_header_signature(["  Task  ", "STATUS", " Due Date "])
            == "task|status|due date"
        )

    def test_order_preserved(self) -> None:
        from confluence_to_notion.converter.table_rules import normalize_header_signature

        assert (
            normalize_header_signature(["Z", "A", "M"]) == "z|a|m"
        )

    def test_empty_raises(self) -> None:
        from confluence_to_notion.converter.table_rules import normalize_header_signature

        with pytest.raises(ValueError):
            normalize_header_signature([])


class TestExtractHeadersFromXhtml:
    def test_thead_preferred(self) -> None:
        from confluence_to_notion.converter.table_rules import extract_headers_from_xhtml

        xhtml = (
            "<table>"
            "<thead><tr><th>Name</th><th>Owner</th></tr></thead>"
            "<tbody><tr><td>x</td><td>y</td></tr></tbody>"
            "</table>"
        )
        assert extract_headers_from_xhtml(xhtml) == ["Name", "Owner"]

    def test_first_tr_fallback(self) -> None:
        from confluence_to_notion.converter.table_rules import extract_headers_from_xhtml

        xhtml = (
            "<table>"
            "<tr><th>Task</th><th>Status</th></tr>"
            "<tr><td>a</td><td>b</td></tr>"
            "</table>"
        )
        assert extract_headers_from_xhtml(xhtml) == ["Task", "Status"]

    def test_no_th_returns_empty(self) -> None:
        from confluence_to_notion.converter.table_rules import extract_headers_from_xhtml

        xhtml = (
            "<table>"
            "<tr><td>a</td><td>b</td></tr>"
            "</table>"
        )
        assert extract_headers_from_xhtml(xhtml) == []

    def test_ignores_colspan_rowspan(self) -> None:
        from confluence_to_notion.converter.table_rules import extract_headers_from_xhtml

        xhtml = (
            "<table>"
            '<thead><tr><th colspan="2">Name</th><th rowspan="1">Owner</th></tr></thead>'
            "</table>"
        )
        assert extract_headers_from_xhtml(xhtml) == ["Name", "Owner"]

    def test_strips_inline_tags(self) -> None:
        from confluence_to_notion.converter.table_rules import extract_headers_from_xhtml

        xhtml = (
            "<table>"
            "<thead><tr><th><strong>Name</strong></th><th><em>Due</em> date</th></tr></thead>"
            "</table>"
        )
        assert extract_headers_from_xhtml(xhtml) == ["Name", "Due date"]

    def test_empty_table_returns_empty(self) -> None:
        from confluence_to_notion.converter.table_rules import extract_headers_from_xhtml

        assert extract_headers_from_xhtml("<table></table>") == []


class TestTableRuleStore:
    def test_load_missing_file_empty(self, tmp_path: Path) -> None:
        from confluence_to_notion.converter.table_rules import TableRuleStore

        store = TableRuleStore(tmp_path / "table-rules.json")
        assert store.data.rules == {}

    def test_upsert_and_save(self, tmp_path: Path) -> None:
        from confluence_to_notion.converter.table_rules import TableRuleStore

        path = tmp_path / "nested" / "table-rules.json"
        store = TableRuleStore(path)
        rule = TableRule(
            is_database=True,
            title_column="name",
            column_types={"name": "title", "owner": "people"},
        )
        store.upsert(["Name", "Owner"], rule)
        store.save()

        assert path.exists()
        reloaded = TableRuleStore(path)
        found = reloaded.lookup(["Name", "Owner"])
        assert found is not None
        assert found.is_database is True
        assert found.title_column == "name"

    def test_lookup_normalizes_headers(self, tmp_path: Path) -> None:
        from confluence_to_notion.converter.table_rules import TableRuleStore

        store = TableRuleStore(tmp_path / "table-rules.json")
        rule = TableRule(is_database=False)
        store.upsert(["Name", "Owner", "Due"], rule)

        # Different casing / whitespace but same normalized signature.
        hit = store.lookup(["  name ", "OWNER", "Due"])
        assert hit is not None
        assert hit.is_database is False

    def test_lookup_miss(self, tmp_path: Path) -> None:
        from confluence_to_notion.converter.table_rules import TableRuleStore

        store = TableRuleStore(tmp_path / "table-rules.json")
        assert store.lookup(["Name"]) is None


class TestInferColumnTypes:
    def test_date_column(self) -> None:
        from confluence_to_notion.converter.table_rules import infer_column_types

        headers = ["Name", "Due"]
        rows = [
            ["Task A", "2026-01-15"],
            ["Task B", "2026-02-01"],
            ["Task C", "2026-03-20"],
        ]
        types = infer_column_types(rows, headers)
        assert types["Due"] == "date"

    def test_select_low_cardinality(self) -> None:
        from confluence_to_notion.converter.table_rules import infer_column_types

        headers = ["Name", "Status"]
        rows = [
            ["A", "open"],
            ["B", "closed"],
            ["C", "open"],
            ["D", "in-progress"],
            ["E", "closed"],
            ["F", "open"],
        ]
        types = infer_column_types(rows, headers)
        assert types["Status"] == "select"

    def test_rich_text_default(self) -> None:
        from confluence_to_notion.converter.table_rules import infer_column_types

        headers = ["Name", "Notes"]
        rows = [
            ["A", "some long free-form note about project A"],
            ["B", "different text entirely"],
            ["C", "yet another unique note with lots of words"],
            ["D", "and another fully unique block of text"],
        ]
        types = infer_column_types(rows, headers)
        assert types["Notes"] == "rich_text"

    def test_all_headers_mapped(self) -> None:
        from confluence_to_notion.converter.table_rules import infer_column_types

        headers = ["Name", "Status", "Due"]
        rows = [
            ["a", "open", "2026-01-01"],
            ["b", "closed", "2026-02-01"],
            ["c", "open", "2026-03-01"],
        ]
        types = infer_column_types(rows, headers)
        assert set(types.keys()) == {"Name", "Status", "Due"}
