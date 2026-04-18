"""Unit tests for the eval baseline load/compare module."""

from pathlib import Path

import pytest

from confluence_to_notion.agents.schemas import (
    EvalMatchResult,
    EvalReport,
    LLMJudgeResult,
    SemanticCoverage,
)
from confluence_to_notion.eval.baseline import (
    compare_to_baseline,
    load_latest_baseline,
)

# --- Helpers ---


def _make_eval_match_result() -> EvalMatchResult:
    return EvalMatchResult(
        agent_name="pattern-discovery",
        status="pass",
        expected_ids=["a"],
        actual_ids=["a"],
        missing_ids=[],
        extra_ids=[],
        recall=1.0,
        precision=1.0,
        score=1.0,
    )


def _make_coverage(ratio: float) -> SemanticCoverage:
    sample = ["macro:info", "macro:toc"]
    # Pick covered count to match the ratio; ratio must be 0, 0.5, or 1.0.
    covered_count = round(ratio * len(sample))
    covered = sample[:covered_count]
    return SemanticCoverage(
        pages_analyzed=1,
        sample_elements=sample,
        covered_elements=covered,
        coverage_ratio=covered_count / len(sample),
    )


def _full_scores(value: int) -> dict[str, int]:
    return {
        "information_preservation": value,
        "notion_idiom": value,
        "structure": value,
        "readability": value,
    }


def _make_llm_judge(value: int, page_id: str = "p1") -> LLMJudgeResult:
    return LLMJudgeResult(
        page_id=page_id,
        scores=_full_scores(value),
        overall_comment="ok",
        model="claude-sonnet-4-6",
        cache_hit=False,
    )


def _make_report(
    *,
    timestamp: str,
    coverage_ratio: float | None = None,
    llm_judge_value: int | None = None,
) -> EvalReport:
    semantic_coverage = (
        _make_coverage(coverage_ratio) if coverage_ratio is not None else None
    )
    llm_judge = (
        [_make_llm_judge(llm_judge_value)] if llm_judge_value is not None else None
    )
    return EvalReport(
        timestamp=timestamp,
        prompt_changed=False,
        results=[_make_eval_match_result()],
        overall_pass=True,
        semantic_coverage=semantic_coverage,
        llm_judge=llm_judge,
    )


def _write_snapshot(results_dir: Path, filename: str, report: EvalReport) -> None:
    results_dir.mkdir(parents=True, exist_ok=True)
    (results_dir / filename).write_text(report.model_dump_json(indent=2))


# --- load_latest_baseline ---


class TestLoadLatestBaseline:
    def test_missing_directory_returns_none(self, tmp_path: Path) -> None:
        assert load_latest_baseline(tmp_path / "does_not_exist") is None

    def test_empty_directory_returns_none(self, tmp_path: Path) -> None:
        results_dir = tmp_path / "eval_results"
        results_dir.mkdir()
        assert load_latest_baseline(results_dir) is None

    def test_single_snapshot(self, tmp_path: Path) -> None:
        results_dir = tmp_path / "eval_results"
        report = _make_report(timestamp="2026-04-17T00:00:00+00:00", coverage_ratio=0.5)
        _write_snapshot(results_dir, "2026-04-17T00-00-00+00_00.json", report)

        loaded = load_latest_baseline(results_dir)
        assert loaded is not None
        assert loaded.timestamp == "2026-04-17T00:00:00+00:00"

    def test_returns_most_recent_of_three(self, tmp_path: Path) -> None:
        results_dir = tmp_path / "eval_results"
        _write_snapshot(
            results_dir,
            "2026-04-15T00-00-00+00_00.json",
            _make_report(timestamp="2026-04-15T00:00:00+00:00", coverage_ratio=0.5),
        )
        _write_snapshot(
            results_dir,
            "2026-04-16T00-00-00+00_00.json",
            _make_report(timestamp="2026-04-16T00:00:00+00:00", coverage_ratio=1.0),
        )
        _write_snapshot(
            results_dir,
            "2026-04-17T00-00-00+00_00.json",
            _make_report(timestamp="2026-04-17T00:00:00+00:00", coverage_ratio=0.5),
        )

        loaded = load_latest_baseline(results_dir)
        assert loaded is not None
        assert loaded.timestamp == "2026-04-17T00:00:00+00:00"

    def test_ignores_non_snapshot_entries(self, tmp_path: Path) -> None:
        """Subdirectories like llm_judge_cache/ must not be picked as baselines."""
        results_dir = tmp_path / "eval_results"
        results_dir.mkdir()
        (results_dir / "llm_judge_cache").mkdir()
        (results_dir / "llm_judge_cache" / "some_hash.json").write_text("{}")
        _write_snapshot(
            results_dir,
            "2026-04-15T00-00-00+00_00.json",
            _make_report(timestamp="2026-04-15T00:00:00+00:00", coverage_ratio=0.5),
        )

        loaded = load_latest_baseline(results_dir)
        assert loaded is not None
        assert loaded.timestamp == "2026-04-15T00:00:00+00:00"


# --- compare_to_baseline ---


class TestCompareToBaseline:
    def test_no_prior_baseline(self) -> None:
        current = _make_report(
            timestamp="2026-04-18T00:00:00+00:00", coverage_ratio=0.5
        )
        cmp = compare_to_baseline(current, None)
        assert cmp.previous_timestamp is None
        assert cmp.coverage_delta == 0.0
        assert cmp.llm_judge_mean_delta is None
        assert cmp.regressions == []
        assert cmp.is_regression is False

    def test_coverage_dropped_beyond_threshold(self) -> None:
        previous = _make_report(
            timestamp="2026-04-17T00:00:00+00:00", coverage_ratio=1.0
        )
        # Drop from 1.0 to 0.5 — beyond the 0.05 threshold.
        current = _make_report(
            timestamp="2026-04-18T00:00:00+00:00", coverage_ratio=0.5
        )
        cmp = compare_to_baseline(current, previous)
        assert cmp.previous_timestamp == "2026-04-17T00:00:00+00:00"
        assert cmp.coverage_delta == pytest.approx(-0.5)
        assert "semantic_coverage" in cmp.regressions
        assert cmp.is_regression is True

    def test_coverage_improved_is_not_regression(self) -> None:
        previous = _make_report(
            timestamp="2026-04-17T00:00:00+00:00", coverage_ratio=0.5
        )
        current = _make_report(
            timestamp="2026-04-18T00:00:00+00:00", coverage_ratio=1.0
        )
        cmp = compare_to_baseline(current, previous)
        assert cmp.coverage_delta == pytest.approx(0.5)
        assert cmp.regressions == []
        assert cmp.is_regression is False

    def test_coverage_drop_within_threshold_is_not_regression(self) -> None:
        """A 0% drop (identical ratio) must never count as a regression."""
        previous = _make_report(
            timestamp="2026-04-17T00:00:00+00:00", coverage_ratio=0.5
        )
        current = _make_report(
            timestamp="2026-04-18T00:00:00+00:00", coverage_ratio=0.5
        )
        cmp = compare_to_baseline(current, previous)
        assert cmp.coverage_delta == pytest.approx(0.0)
        assert cmp.is_regression is False

    def test_llm_judge_missing_on_current(self) -> None:
        previous = _make_report(
            timestamp="2026-04-17T00:00:00+00:00",
            coverage_ratio=0.5,
            llm_judge_value=4,
        )
        current = _make_report(
            timestamp="2026-04-18T00:00:00+00:00",
            coverage_ratio=0.5,
            llm_judge_value=None,
        )
        cmp = compare_to_baseline(current, previous)
        assert cmp.llm_judge_mean_delta is None
        assert "llm_judge" not in cmp.regressions

    def test_llm_judge_missing_on_previous(self) -> None:
        previous = _make_report(
            timestamp="2026-04-17T00:00:00+00:00",
            coverage_ratio=0.5,
            llm_judge_value=None,
        )
        current = _make_report(
            timestamp="2026-04-18T00:00:00+00:00",
            coverage_ratio=0.5,
            llm_judge_value=4,
        )
        cmp = compare_to_baseline(current, previous)
        assert cmp.llm_judge_mean_delta is None
        assert "llm_judge" not in cmp.regressions

    def test_llm_judge_drop_beyond_threshold(self) -> None:
        previous = _make_report(
            timestamp="2026-04-17T00:00:00+00:00",
            coverage_ratio=0.5,
            llm_judge_value=5,
        )
        current = _make_report(
            timestamp="2026-04-18T00:00:00+00:00",
            coverage_ratio=0.5,
            llm_judge_value=3,
        )
        cmp = compare_to_baseline(current, previous)
        assert cmp.llm_judge_mean_delta == pytest.approx(-2.0)
        assert "llm_judge" in cmp.regressions
        assert cmp.is_regression is True

    def test_llm_judge_small_drop_is_not_regression(self) -> None:
        previous = _make_report(
            timestamp="2026-04-17T00:00:00+00:00",
            coverage_ratio=0.5,
            llm_judge_value=4,
        )
        current = _make_report(
            timestamp="2026-04-18T00:00:00+00:00",
            coverage_ratio=0.5,
            llm_judge_value=4,
        )
        cmp = compare_to_baseline(current, previous)
        assert cmp.llm_judge_mean_delta == pytest.approx(0.0)
        assert "llm_judge" not in cmp.regressions

    def test_thresholds_are_recorded(self) -> None:
        previous = _make_report(
            timestamp="2026-04-17T00:00:00+00:00", coverage_ratio=0.5
        )
        current = _make_report(
            timestamp="2026-04-18T00:00:00+00:00", coverage_ratio=0.5
        )
        cmp = compare_to_baseline(
            current, previous, coverage_threshold=0.1, llm_judge_threshold=0.5
        )
        assert cmp.thresholds_used["semantic_coverage"] == pytest.approx(0.1)
        assert cmp.thresholds_used["llm_judge"] == pytest.approx(0.5)
