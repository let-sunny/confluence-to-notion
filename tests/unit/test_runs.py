"""Unit tests for the slug / run-dir / status I/O helpers in `runs.py`."""

import json
import re
from pathlib import Path

from confluence_to_notion.runs import (
    RunStatus,
    SourceInfo,
    StepRecord,
    StepStatus,
    finalize_run,
    init_run_dir,
    read_status,
    slug_for_url,
    start_run,
    update_step,
    write_status,
)


class TestSlugForUrl:
    def test_spaces_key_url(self) -> None:
        slug = slug_for_url("https://example.atlassian.net/wiki/spaces/ENG/overview")
        assert slug == "example-eng"

    def test_pageid_query_url(self) -> None:
        slug = slug_for_url(
            "https://example.atlassian.net/pages/viewpage.action?pageId=12345"
        )
        assert slug == "example-12345"

    def test_kebab_sanitized_path_segment(self) -> None:
        slug = slug_for_url("https://example.atlassian.net/foo/My Cool Page!!")
        assert slug == "example-my-cool-page"

    def test_lowercases_hostname_label(self) -> None:
        slug = slug_for_url("https://EXAMPLE.atlassian.net/wiki/spaces/Eng/overview")
        assert slug == "example-eng"

    def test_pageid_in_path_segment(self) -> None:
        slug = slug_for_url(
            "https://example.atlassian.net/wiki/spaces/ENG/pages/98765/Some-Title"
        )
        assert slug == "example-98765"


class TestInitRunDir:
    def test_creates_directory(self, tmp_path: Path) -> None:
        run_dir = init_run_dir(tmp_path, "example-eng")
        assert run_dir == tmp_path / "runs" / "example-eng"
        assert run_dir.is_dir()

    def test_collision_appends_suffix(self, tmp_path: Path) -> None:
        first = init_run_dir(tmp_path, "example-eng")
        second = init_run_dir(tmp_path, "example-eng")
        third = init_run_dir(tmp_path, "example-eng")
        assert first == tmp_path / "runs" / "example-eng"
        assert second == tmp_path / "runs" / "example-eng-2"
        assert third == tmp_path / "runs" / "example-eng-3"
        assert first.is_dir()
        assert second.is_dir()
        assert third.is_dir()

    def test_creates_parent_runs_directory(self, tmp_path: Path) -> None:
        # base/runs/ does not yet exist
        assert not (tmp_path / "runs").exists()
        run_dir = init_run_dir(tmp_path, "example-eng")
        assert (tmp_path / "runs").is_dir()
        assert run_dir.is_dir()


class TestStatusIO:
    def test_round_trip(self, tmp_path: Path) -> None:
        run_dir = init_run_dir(tmp_path, "example-eng")
        original = RunStatus(
            fetch=StepRecord(status=StepStatus.DONE, at="2026-04-18T10:00:00Z", count=5),
            convert=StepRecord(status=StepStatus.RUNNING, at="2026-04-18T10:00:01Z"),
        )
        write_status(run_dir, original)
        restored = read_status(run_dir)
        assert restored == original

    def test_write_creates_indented_json(self, tmp_path: Path) -> None:
        run_dir = init_run_dir(tmp_path, "example-eng")
        write_status(run_dir, RunStatus())
        text = (run_dir / "status.json").read_text(encoding="utf-8")
        assert "\n" in text  # indent=2 produces a multi-line file
        decoded = json.loads(text)
        assert set(decoded) == {"fetch", "discover", "convert", "migrate"}


_ISO_UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:\+00:00|Z)$")


class TestRunLifecycle:
    """Tests for start_run / update_step / finalize_run helpers."""

    def test_start_run_creates_artifacts(self, tmp_path: Path) -> None:
        url = "https://example.atlassian.net/wiki/spaces/ENG/pages/12345/Some-Title"
        run_dir, source = start_run(tmp_path, url, "page", root_id="12345")

        assert run_dir == tmp_path / "runs" / "example-12345"
        assert run_dir.is_dir()

        assert isinstance(source, SourceInfo)
        assert source.url == url
        assert source.type == "page"
        assert source.root_id == "12345"
        assert source.notion_target is None

        source_data = json.loads((run_dir / "source.json").read_text(encoding="utf-8"))
        assert source_data["url"] == url
        assert source_data["type"] == "page"
        assert source_data["root_id"] == "12345"

        status = read_status(run_dir)
        assert status == RunStatus()
        for step in ("fetch", "discover", "convert", "migrate"):
            record: StepRecord = getattr(status, step)
            assert record.status == StepStatus.PENDING
            assert record.at is None

    def test_start_run_second_call_same_url_gets_suffix(self, tmp_path: Path) -> None:
        url = "https://example.atlassian.net/wiki/spaces/ENG/pages/12345/Some-Title"
        first_dir, _ = start_run(tmp_path, url, "page")
        second_dir, _ = start_run(tmp_path, url, "page")

        assert first_dir == tmp_path / "runs" / "example-12345"
        assert second_dir == tmp_path / "runs" / "example-12345-2"
        assert (first_dir / "source.json").exists()
        assert (second_dir / "source.json").exists()
        assert (first_dir / "status.json").exists()
        assert (second_dir / "status.json").exists()

    def test_start_run_persists_notion_target(self, tmp_path: Path) -> None:
        run_dir, _ = start_run(
            tmp_path,
            "https://example.atlassian.net/wiki/spaces/ENG/overview",
            "space",
            notion_target={"page_id": "abc-def"},
        )
        data = json.loads((run_dir / "source.json").read_text(encoding="utf-8"))
        assert data["notion_target"] == {"page_id": "abc-def"}

    def test_update_step_mutates_only_named_step(self, tmp_path: Path) -> None:
        run_dir, _ = start_run(
            tmp_path,
            "https://example.atlassian.net/wiki/spaces/ENG/pages/12345/Some",
            "page",
        )

        update_step(run_dir, "fetch", StepStatus.DONE, count=7, warnings=1)

        status = read_status(run_dir)
        assert status.fetch.status == StepStatus.DONE
        assert status.fetch.count == 7
        assert status.fetch.warnings == 1
        assert status.fetch.at is not None
        assert _ISO_UTC_RE.match(status.fetch.at), status.fetch.at

        # Non-mutated steps remain at defaults
        for step in ("discover", "convert", "migrate"):
            record: StepRecord = getattr(status, step)
            assert record.status == StepStatus.PENDING
            assert record.at is None
            assert record.count is None
            assert record.warnings is None

    def test_update_step_preserves_other_steps_across_calls(self, tmp_path: Path) -> None:
        run_dir, _ = start_run(
            tmp_path,
            "https://example.atlassian.net/wiki/spaces/ENG/pages/1/T",
            "page",
        )
        update_step(run_dir, "fetch", StepStatus.DONE, count=3)
        update_step(run_dir, "convert", StepStatus.RUNNING)

        status = read_status(run_dir)
        assert status.fetch.status == StepStatus.DONE
        assert status.fetch.count == 3
        assert status.convert.status == StepStatus.RUNNING
        assert status.discover.status == StepStatus.PENDING
        assert status.migrate.status == StepStatus.PENDING

    def test_update_step_accepts_plain_status_string(self, tmp_path: Path) -> None:
        run_dir, _ = start_run(
            tmp_path,
            "https://example.atlassian.net/wiki/spaces/ENG/pages/1/T",
            "page",
        )
        update_step(run_dir, "migrate", "failed")
        status = read_status(run_dir)
        assert status.migrate.status == StepStatus.FAILED

    def test_finalize_run_writes_report(self, tmp_path: Path) -> None:
        url = "https://example.atlassian.net/wiki/spaces/ENG/pages/9/Page"
        run_dir, _ = start_run(tmp_path, url, "page", root_id="9")
        update_step(run_dir, "fetch", StepStatus.DONE, count=2)

        finalize_run(run_dir)

        report = (run_dir / "report.md").read_text(encoding="utf-8")
        assert "# Run Report" in report
        assert url in report
        assert "page" in report
        assert "fetch" in report
        assert "done" in report
