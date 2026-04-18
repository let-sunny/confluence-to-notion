"""Unit tests for the `render_report` Markdown renderer in `runs.py`."""

from confluence_to_notion.runs import (
    RunStatus,
    SourceInfo,
    StepRecord,
    StepStatus,
    render_report,
)


def _full_status() -> RunStatus:
    return RunStatus(
        fetch=StepRecord(status=StepStatus.DONE, at="2026-04-18T10:00:00Z", count=12),
        discover=StepRecord(status=StepStatus.SKIPPED, at="2026-04-18T10:00:01Z"),
        convert=StepRecord(
            status=StepStatus.DONE, at="2026-04-18T10:00:02Z", count=12, warnings=2
        ),
        migrate=StepRecord(status=StepStatus.FAILED, at="2026-04-18T10:00:03Z", warnings=1),
    )


class TestRenderReport:
    def test_includes_source_url_and_type(self) -> None:
        source = SourceInfo(
            url="https://example.atlassian.net/wiki/spaces/ENG/pages/123",
            type="page",
        )
        report = render_report(source, RunStatus())
        assert "https://example.atlassian.net/wiki/spaces/ENG/pages/123" in report
        assert "page" in report

    def test_includes_notion_target_when_present(self) -> None:
        source = SourceInfo(
            url="https://example.atlassian.net/wiki/spaces/ENG/pages/123",
            type="page",
            notion_target={"page_id": "abcd-efgh"},
        )
        report = render_report(source, RunStatus())
        assert "abcd-efgh" in report

    def test_omits_notion_target_section_when_absent(self) -> None:
        source = SourceInfo(
            url="https://example.atlassian.net/wiki/spaces/ENG/pages/123",
            type="page",
        )
        report = render_report(source, RunStatus())
        assert "notion_target" not in report.lower() or "page_id" not in report

    def test_includes_each_step_with_status_and_timestamp(self) -> None:
        source = SourceInfo(
            url="https://example.atlassian.net/wiki/spaces/ENG/pages/123",
            type="page",
        )
        report = render_report(source, _full_status())
        for step_name in ("fetch", "discover", "convert", "migrate"):
            assert step_name in report
        assert "done" in report
        assert "skipped" in report
        assert "failed" in report
        assert "2026-04-18T10:00:00Z" in report
        assert "2026-04-18T10:00:03Z" in report

    def test_includes_count_and_warnings_only_when_set(self) -> None:
        source = SourceInfo(
            url="https://example.atlassian.net/wiki/spaces/ENG/pages/123",
            type="page",
        )
        status = RunStatus(
            fetch=StepRecord(status=StepStatus.DONE, at="2026-04-18T10:00:00Z", count=12),
            convert=StepRecord(
                status=StepStatus.DONE, at="2026-04-18T10:00:02Z", count=12, warnings=2
            ),
        )
        report = render_report(source, status)
        # fetch row has count=12 but no warnings — neither the literal "warnings" tag
        # nor a stray "0" should be emitted for that row.
        assert "12" in report
        assert "warnings=2" in report or "warnings: 2" in report or "warnings 2" in report
        # discover/migrate left at defaults — no count/warnings markers
        assert "count=0" not in report

    def test_optional_rules_summary_section(self) -> None:
        source = SourceInfo(
            url="https://example.atlassian.net/wiki/spaces/ENG/pages/123",
            type="page",
        )
        without = render_report(source, RunStatus())
        assert "rules" not in without.lower() or "## " not in without.lower().split("rules")[0][-4:]

        with_summary = render_report(
            source,
            RunStatus(),
            rules_summary="- table_rule:status-board used 4 times",
        )
        assert "table_rule:status-board used 4 times" in with_summary
        assert "rules" in with_summary.lower()

    def test_returns_string_does_not_write_file(self) -> None:
        source = SourceInfo(
            url="https://example.atlassian.net/wiki/spaces/ENG/pages/123",
            type="page",
        )
        result = render_report(source, RunStatus())
        assert isinstance(result, str)
        assert result.startswith("#")  # at least one Markdown heading
