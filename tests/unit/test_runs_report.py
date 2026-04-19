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


class TestRulesSourceSection:
    """render_report emits '## Rules source' when source.rules_source is set."""

    def _source(
        self,
        *,
        rules_source: str | None = None,
        rules_generated_at: str | None = None,
    ) -> SourceInfo:
        return SourceInfo(
            url="https://example.atlassian.net/wiki/spaces/ENG/pages/123",
            type="page",
            rules_source=rules_source,  # type: ignore[arg-type]
            rules_generated_at=rules_generated_at,
        )

    def test_omits_section_when_rules_source_is_none(self) -> None:
        report = render_report(self._source(), RunStatus())
        assert "## Rules source" not in report

    def test_reused_emits_source_bullet(self) -> None:
        report = render_report(self._source(rules_source="reused"), RunStatus())
        assert "## Rules source" in report
        assert "- source: reused" in report

    def test_regenerated_emits_source_bullet(self) -> None:
        report = render_report(self._source(rules_source="regenerated"), RunStatus())
        assert "## Rules source" in report
        assert "- source: regenerated" in report

    def test_generated_emits_source_bullet(self) -> None:
        report = render_report(self._source(rules_source="generated"), RunStatus())
        assert "## Rules source" in report
        assert "- source: generated" in report

    def test_reused_with_generated_at(self) -> None:
        report = render_report(
            self._source(
                rules_source="reused",
                rules_generated_at="2026-04-19T12:00:00+00:00",
            ),
            RunStatus(),
        )
        assert "## Rules source" in report
        assert "- source: reused" in report
        assert "- last generated_at: 2026-04-19T12:00:00+00:00" in report

    def test_generated_at_alone_without_source_is_omitted(self) -> None:
        # When rules_source is None, the entire section — including any
        # dangling generated_at — must be omitted.
        report = render_report(
            self._source(rules_generated_at="2026-04-19T12:00:00+00:00"),
            RunStatus(),
        )
        assert "## Rules source" not in report
        assert "generated_at" not in report

    def test_section_placed_between_steps_and_rules_usage(self) -> None:
        report = render_report(
            self._source(rules_source="generated"),
            RunStatus(),
            rules_summary="- rule:macro:toc: 1",
        )
        steps_idx = report.index("## Steps")
        rules_source_idx = report.index("## Rules source")
        rules_usage_idx = report.index("## Rules usage")
        assert steps_idx < rules_source_idx < rules_usage_idx
