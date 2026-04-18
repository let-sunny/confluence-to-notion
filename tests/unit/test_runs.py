"""Unit tests for the slug / run-dir / status I/O helpers in `runs.py`."""

import json
from pathlib import Path

from confluence_to_notion.runs import (
    RunStatus,
    StepRecord,
    StepStatus,
    init_run_dir,
    read_status,
    slug_for_url,
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
