"""Unit tests for the run-status / source Pydantic schemas in `runs.py`."""

import json

import pytest
from pydantic import ValidationError

from confluence_to_notion.runs import (
    RunStatus,
    SourceInfo,
    StepRecord,
    StepStatus,
)


class TestStepStatus:
    def test_enum_members(self) -> None:
        assert StepStatus.PENDING.value == "pending"
        assert StepStatus.RUNNING.value == "running"
        assert StepStatus.DONE.value == "done"
        assert StepStatus.SKIPPED.value == "skipped"
        assert StepStatus.FAILED.value == "failed"

    def test_enum_rejects_unknown_value(self) -> None:
        with pytest.raises(ValueError):
            StepStatus("bogus")


class TestStepRecord:
    def test_default_status_is_pending(self) -> None:
        record = StepRecord()
        assert record.status == StepStatus.PENDING
        assert record.at is None
        assert record.count is None
        assert record.warnings is None

    def test_optional_count_and_warnings(self) -> None:
        record = StepRecord(
            status=StepStatus.DONE,
            at="2026-04-18T10:00:00Z",
            count=12,
            warnings=3,
        )
        assert record.count == 12
        assert record.warnings == 3

    def test_rejects_unknown_status_string(self) -> None:
        with pytest.raises(ValidationError):
            StepRecord(status="bogus")  # type: ignore[arg-type]

    def test_json_round_trip_preserves_fields(self) -> None:
        record = StepRecord(
            status=StepStatus.RUNNING,
            at="2026-04-18T10:00:00Z",
            count=5,
            warnings=0,
        )
        payload = record.model_dump_json()
        restored = StepRecord.model_validate_json(payload)
        assert restored == record


class TestRunStatus:
    def test_defaults_have_pending_step_records(self) -> None:
        status = RunStatus()
        assert status.fetch.status == StepStatus.PENDING
        assert status.discover.status == StepStatus.PENDING
        assert status.convert.status == StepStatus.PENDING
        assert status.migrate.status == StepStatus.PENDING

    def test_named_step_fields(self) -> None:
        status = RunStatus(
            fetch=StepRecord(status=StepStatus.DONE, at="2026-04-18T10:00:00Z", count=8),
            discover=StepRecord(status=StepStatus.SKIPPED, at="2026-04-18T10:00:01Z"),
            convert=StepRecord(status=StepStatus.RUNNING, at="2026-04-18T10:00:02Z"),
            migrate=StepRecord(status=StepStatus.FAILED, at="2026-04-18T10:00:03Z", warnings=2),
        )
        assert status.fetch.status == StepStatus.DONE
        assert status.discover.status == StepStatus.SKIPPED
        assert status.convert.status == StepStatus.RUNNING
        assert status.migrate.status == StepStatus.FAILED

    def test_json_round_trip(self) -> None:
        status = RunStatus(
            fetch=StepRecord(status=StepStatus.DONE, at="2026-04-18T10:00:00Z", count=8),
        )
        payload = status.model_dump_json()
        restored = RunStatus.model_validate_json(payload)
        assert restored == status
        # explicitly asserts named keys serialize as expected
        decoded = json.loads(payload)
        assert set(decoded) == {"fetch", "discover", "convert", "migrate"}


class TestSourceInfo:
    def test_required_fields(self) -> None:
        source = SourceInfo(
            url="https://example.atlassian.net/wiki/spaces/ENG/pages/123",
            type="page",
        )
        assert source.url.endswith("/123")
        assert source.type == "page"
        assert source.root_id is None
        assert source.notion_target is None
        assert source.rules_source is None
        assert source.rules_generated_at is None

    def test_parses_full_payload(self) -> None:
        payload = {
            "url": "https://example.atlassian.net/wiki/spaces/ENG/pages/123",
            "type": "page",
            "root_id": "123",
            "notion_target": {"page_id": "abcd-efgh"},
        }
        source = SourceInfo.model_validate(payload)
        assert source.root_id == "123"
        assert source.notion_target == {"page_id": "abcd-efgh"}

    def test_json_round_trip(self) -> None:
        source = SourceInfo(
            url="https://example.atlassian.net/wiki/spaces/ENG/pages/123",
            type="tree",
            root_id="123",
            notion_target={"page_id": "abcd"},
        )
        restored = SourceInfo.model_validate_json(source.model_dump_json())
        assert restored == source

    @pytest.mark.parametrize("value", ["reused", "regenerated", "generated"])
    def test_accepts_rules_source_literals(self, value: str) -> None:
        source = SourceInfo(
            url="https://example.atlassian.net/wiki/spaces/ENG/pages/123",
            type="page",
            rules_source=value,  # type: ignore[arg-type]
        )
        assert source.rules_source == value

    def test_rejects_invalid_rules_source(self) -> None:
        with pytest.raises(ValidationError):
            SourceInfo(
                url="https://example.atlassian.net/wiki/spaces/ENG/pages/123",
                type="page",
                rules_source="bogus",  # type: ignore[arg-type]
            )

    def test_stores_rules_generated_at(self) -> None:
        source = SourceInfo(
            url="https://example.atlassian.net/wiki/spaces/ENG/pages/123",
            type="page",
            rules_source="reused",
            rules_generated_at="2026-04-19T12:00:00+00:00",
        )
        assert source.rules_generated_at == "2026-04-19T12:00:00+00:00"

    def test_json_round_trip_with_rules_fields(self) -> None:
        source = SourceInfo(
            url="https://example.atlassian.net/wiki/spaces/ENG/pages/123",
            type="page",
            rules_source="regenerated",
            rules_generated_at="2026-04-19T12:00:00+00:00",
        )
        restored = SourceInfo.model_validate_json(source.model_dump_json())
        assert restored == source
        payload = json.loads(source.model_dump_json())
        assert payload["rules_source"] == "regenerated"
        assert payload["rules_generated_at"] == "2026-04-19T12:00:00+00:00"
