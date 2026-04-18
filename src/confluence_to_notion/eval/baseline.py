"""Load the most recent prior eval snapshot and compare against the current one.

Per ADR-004 this is signal only — regressions are flagged but do not flip
``EvalReport.overall_pass``. The CLI exposes ``--fail-on-regression`` for
callers that want a hard gate.
"""

from pathlib import Path

from confluence_to_notion.agents.schemas import (
    BaselineComparison,
    EvalReport,
    LLMJudgeResult,
)

_DEFAULT_COVERAGE_THRESHOLD = 0.05
_DEFAULT_LLM_JUDGE_THRESHOLD = 0.3


def load_latest_baseline(results_dir: Path) -> EvalReport | None:
    """Return the most recent prior snapshot, or ``None`` if none exists.

    Snapshot filenames are timestamp-prefixed by the CLI so ``sorted()`` gives
    chronological order. Subdirectories (e.g. ``llm_judge_cache/``) are skipped.
    """
    if not results_dir.is_dir():
        return None

    snapshots = sorted(p for p in results_dir.glob("*.json") if p.is_file())
    if not snapshots:
        return None

    latest = snapshots[-1]
    return EvalReport.model_validate_json(latest.read_text())


def _llm_judge_grand_mean(judge_results: list[LLMJudgeResult] | None) -> float | None:
    """Mean of all dimension scores across all pages, or None when empty."""
    if not judge_results:
        return None
    dim_values: list[int] = []
    for r in judge_results:
        dim_values.extend(r.scores.values())
    if not dim_values:
        return None
    return sum(dim_values) / len(dim_values)


def compare_to_baseline(
    current: EvalReport,
    previous: EvalReport | None,
    *,
    coverage_threshold: float = _DEFAULT_COVERAGE_THRESHOLD,
    llm_judge_threshold: float = _DEFAULT_LLM_JUDGE_THRESHOLD,
) -> BaselineComparison:
    """Diff ``current`` against ``previous`` and flag metrics that regressed.

    A metric regresses when it drops by ``>= threshold``. When ``previous`` is
    ``None`` or a metric is missing on either side, that metric is not counted.
    """
    thresholds_used = {
        "semantic_coverage": coverage_threshold,
        "llm_judge": llm_judge_threshold,
    }

    if previous is None:
        return BaselineComparison(
            previous_timestamp=None,
            coverage_delta=0.0,
            llm_judge_mean_delta=None,
            regressions=[],
            thresholds_used=thresholds_used,
            is_regression=False,
        )

    regressions: list[str] = []

    current_coverage = (
        current.semantic_coverage.coverage_ratio
        if current.semantic_coverage is not None
        else None
    )
    previous_coverage = (
        previous.semantic_coverage.coverage_ratio
        if previous.semantic_coverage is not None
        else None
    )
    if current_coverage is not None and previous_coverage is not None:
        coverage_delta = current_coverage - previous_coverage
    else:
        coverage_delta = 0.0
    if coverage_delta <= -coverage_threshold:
        regressions.append("semantic_coverage")

    current_judge_mean = _llm_judge_grand_mean(current.llm_judge)
    previous_judge_mean = _llm_judge_grand_mean(previous.llm_judge)
    llm_judge_mean_delta: float | None
    if current_judge_mean is not None and previous_judge_mean is not None:
        llm_judge_mean_delta = current_judge_mean - previous_judge_mean
        if llm_judge_mean_delta <= -llm_judge_threshold:
            regressions.append("llm_judge")
    else:
        llm_judge_mean_delta = None

    return BaselineComparison(
        previous_timestamp=previous.timestamp,
        coverage_delta=coverage_delta,
        llm_judge_mean_delta=llm_judge_mean_delta,
        regressions=regressions,
        thresholds_used=thresholds_used,
        is_regression=bool(regressions),
    )
