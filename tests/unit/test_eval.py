"""Unit tests for eval framework: run_eval + prompt-change detection."""

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from confluence_to_notion.agents.schemas import (
    DiscoveryOutput,
    DiscoveryPattern,
    EvalReport,
    SemanticCoverage,
)
from confluence_to_notion.eval.comparator import (
    detect_prompt_changes,
    run_eval,
)

# --- Helpers ---


def _make_pattern(pattern_id: str, frequency: int = 1) -> DiscoveryPattern:
    return DiscoveryPattern(
        pattern_id=pattern_id,
        pattern_type=pattern_id.split(":")[0],
        description=f"Pattern {pattern_id}",
        example_snippets=[f"<example>{pattern_id}</example>"],
        source_pages=["page1"],
        frequency=frequency,
    )


def _make_discovery(*pattern_ids: str) -> DiscoveryOutput:
    return DiscoveryOutput(
        sample_dir="samples/",
        pages_analyzed=3,
        patterns=[_make_pattern(pid) for pid in pattern_ids],
    )


def _write_patterns(output_dir: Path, *pattern_ids: str) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "patterns.json").write_text(
        _make_discovery(*pattern_ids).model_dump_json()
    )


# --- detect_prompt_changes ---


class TestDetectPromptChanges:
    @patch("confluence_to_notion.eval.comparator.subprocess.run")
    def test_returns_true_when_files_changed(self, mock_run: Any) -> None:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = ".claude/agents/discover/pattern-discovery.md\n"
        assert detect_prompt_changes() is True

    @patch("confluence_to_notion.eval.comparator.subprocess.run")
    def test_returns_false_when_no_changes(self, mock_run: Any) -> None:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = ""
        assert detect_prompt_changes() is False

    @patch("confluence_to_notion.eval.comparator.subprocess.run")
    def test_returns_false_on_git_error(self, mock_run: Any) -> None:
        mock_run.return_value.returncode = 128
        mock_run.return_value.stdout = ""
        assert detect_prompt_changes() is False

    @patch("confluence_to_notion.eval.comparator.subprocess.run", side_effect=FileNotFoundError)
    def test_returns_false_when_git_not_found(self, mock_run: Any) -> None:
        assert detect_prompt_changes() is False


# --- run_eval ---


class TestRunEval:
    @patch("confluence_to_notion.eval.comparator.detect_prompt_changes", return_value=False)
    def test_run_eval_produces_report_without_samples(
        self, mock_detect: Any, tmp_path: Path
    ) -> None:
        output_dir = tmp_path / "output"
        _write_patterns(output_dir, "macro:toc")
        report = run_eval(output_dir)
        assert report.prompt_changed is False
        assert report.semantic_coverage is None
        assert report.llm_judge is None
        assert report.baseline_comparison is None

    @patch("confluence_to_notion.eval.comparator.detect_prompt_changes", return_value=True)
    def test_run_eval_detects_prompt_changes(
        self, mock_detect: Any, tmp_path: Path
    ) -> None:
        output_dir = tmp_path / "output"
        _write_patterns(output_dir, "macro:toc")
        report = run_eval(output_dir)
        assert report.prompt_changed is True

    def test_run_eval_missing_patterns_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            run_eval(tmp_path)

    @patch("confluence_to_notion.eval.comparator.detect_prompt_changes", return_value=False)
    def test_run_eval_populates_semantic_coverage_when_samples_given(
        self, mock_detect: Any, tmp_path: Path
    ) -> None:
        output_dir = tmp_path / "output"
        output_dir.mkdir(parents=True)
        toc_pattern = DiscoveryPattern(
            pattern_id="macro:toc",
            pattern_type="macro",
            description="TOC macro",
            example_snippets=['<ac:structured-macro ac:name="toc"/>'],
            source_pages=["p1"],
            frequency=1,
        )
        (output_dir / "patterns.json").write_text(
            DiscoveryOutput(
                sample_dir="samples/", pages_analyzed=1, patterns=[toc_pattern]
            ).model_dump_json()
        )
        samples_dir = tmp_path / "samples"
        samples_dir.mkdir()
        (samples_dir / "p1.xhtml").write_text(
            '<ac:structured-macro ac:name="toc"/>'
            '<ac:structured-macro ac:name="unknown-thing"/>',
            encoding="utf-8",
        )
        report = run_eval(output_dir, samples_dir=samples_dir)
        assert report.semantic_coverage is not None
        assert report.semantic_coverage.pages_analyzed == 1
        assert "macro:toc" in report.semantic_coverage.sample_elements
        assert "macro:unknown-thing" in report.semantic_coverage.sample_elements
        assert "macro:toc" in report.semantic_coverage.covered_elements
        assert "macro:unknown-thing" not in report.semantic_coverage.covered_elements
        assert report.semantic_coverage.coverage_ratio == pytest.approx(0.5)

    @patch("confluence_to_notion.eval.comparator.detect_prompt_changes", return_value=False)
    def test_run_eval_without_samples_leaves_coverage_none(
        self, mock_detect: Any, tmp_path: Path
    ) -> None:
        output_dir = tmp_path / "output"
        _write_patterns(output_dir, "macro:toc")
        report = run_eval(output_dir)
        assert report.semantic_coverage is None


# --- CLI baseline diff + opt-in regression gating ---


def _cli_coverage(ratio: float) -> SemanticCoverage:
    sample = ["macro:info", "macro:toc"]
    covered_count = round(ratio * len(sample))
    return SemanticCoverage(
        pages_analyzed=1,
        sample_elements=sample,
        covered_elements=sample[:covered_count],
        coverage_ratio=covered_count / len(sample),
    )


def _cli_report(timestamp: str, coverage_ratio: float) -> EvalReport:
    return EvalReport(
        timestamp=timestamp,
        prompt_changed=False,
        semantic_coverage=_cli_coverage(coverage_ratio),
    )


def _write_baseline_snapshot(results_dir: Path, report: EvalReport) -> None:
    results_dir.mkdir(parents=True, exist_ok=True)
    filename = report.timestamp.replace(":", "-").replace("+", "_") + ".json"
    (results_dir / filename).write_text(report.model_dump_json(indent=2))


class TestEvalCliBaselineGating:
    """main() should attach baseline_comparison and honor --fail-on-regression."""

    @staticmethod
    def _argv(output_dir: Path, results_dir: Path, *flags: str) -> list[str]:
        return [
            "confluence_to_notion.eval",
            str(output_dir),
            str(results_dir),
            *flags,
        ]

    def test_first_run_no_prior_baseline_exits_zero(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        output_dir = tmp_path / "output"
        results_dir = tmp_path / "results"
        output_dir.mkdir()

        current = _cli_report("2026-04-18T00:00:00+00:00", coverage_ratio=0.5)

        from confluence_to_notion.eval import __main__ as cli

        monkeypatch.setattr(cli, "run_eval", lambda *a, **kw: current)
        monkeypatch.setattr(
            "sys.argv",
            self._argv(output_dir, results_dir),
        )
        cli.main()  # must not raise SystemExit(1)

        written = list(results_dir.glob("*.json"))
        assert len(written) == 1
        saved = EvalReport.model_validate_json(written[0].read_text())
        assert saved.baseline_comparison is not None
        assert saved.baseline_comparison.previous_timestamp is None
        assert saved.baseline_comparison.is_regression is False

    def test_regression_without_fail_flag_exits_zero(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        output_dir = tmp_path / "output"
        results_dir = tmp_path / "results"
        output_dir.mkdir()

        baseline = _cli_report("2026-04-17T00:00:00+00:00", coverage_ratio=1.0)
        _write_baseline_snapshot(results_dir, baseline)

        current = _cli_report("2026-04-18T00:00:00+00:00", coverage_ratio=0.5)

        from confluence_to_notion.eval import __main__ as cli

        monkeypatch.setattr(cli, "run_eval", lambda *a, **kw: current)
        monkeypatch.setattr(
            "sys.argv",
            self._argv(output_dir, results_dir),
        )
        cli.main()  # no SystemExit(1) expected

        current_file = results_dir / "2026-04-18T00-00-00_00-00.json"
        assert current_file.exists()
        saved = EvalReport.model_validate_json(current_file.read_text())
        assert saved.baseline_comparison is not None
        assert saved.baseline_comparison.is_regression is True
        assert "semantic_coverage" in saved.baseline_comparison.regressions

    def test_regression_with_fail_flag_exits_one(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        output_dir = tmp_path / "output"
        results_dir = tmp_path / "results"
        output_dir.mkdir()

        baseline = _cli_report("2026-04-17T00:00:00+00:00", coverage_ratio=1.0)
        _write_baseline_snapshot(results_dir, baseline)

        current = _cli_report("2026-04-18T00:00:00+00:00", coverage_ratio=0.5)

        from confluence_to_notion.eval import __main__ as cli

        monkeypatch.setattr(cli, "run_eval", lambda *a, **kw: current)
        monkeypatch.setattr(
            "sys.argv",
            self._argv(output_dir, results_dir, "--fail-on-regression"),
        )
        with pytest.raises(SystemExit) as exc_info:
            cli.main()
        assert exc_info.value.code == 1

        current_file = results_dir / "2026-04-18T00-00-00_00-00.json"
        assert current_file.exists()

    def test_baseline_excludes_just_written_snapshot(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """load_latest_baseline must fire BEFORE the current snapshot is written."""
        output_dir = tmp_path / "output"
        results_dir = tmp_path / "results"
        output_dir.mkdir()

        current = _cli_report("2026-04-18T00:00:00+00:00", coverage_ratio=0.5)

        from confluence_to_notion.eval import __main__ as cli

        monkeypatch.setattr(cli, "run_eval", lambda *a, **kw: current)
        monkeypatch.setattr(
            "sys.argv",
            self._argv(output_dir, results_dir),
        )
        cli.main()

        current_file = results_dir / "2026-04-18T00-00-00_00-00.json"
        saved = EvalReport.model_validate_json(current_file.read_text())
        assert saved.baseline_comparison is not None
        # previous_timestamp must be None — current must not be its own baseline.
        assert saved.baseline_comparison.previous_timestamp is None
