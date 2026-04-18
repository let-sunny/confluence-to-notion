"""CLI entry point for the eval framework.

Usage:
    uv run python -m confluence_to_notion.eval \
        <output_dir> <fixture_dir> <results_dir> [<samples_dir>] \
        [--llm-judge] [--fail-on-regression]

The optional ``--llm-judge`` flag opts into the LLM-as-judge pass that scores
each converted page across the 4 quality dimensions. Results attach to
``EvalReport.llm_judge`` and are signal only (per ADR-004) — they do not flip
the overall pass/fail exit code. Default runs do not call Anthropic.

``--fail-on-regression`` makes the CLI exit 1 when the baseline diff flags a
regression. Default is warn-only, matching ADR-004's signal-only posture.
"""

import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

from confluence_to_notion.agents.schemas import BaselineComparison
from confluence_to_notion.eval.baseline import (
    compare_to_baseline,
    load_latest_baseline,
)
from confluence_to_notion.eval.comparator import run_eval
from confluence_to_notion.eval.llm_judge import run_llm_judge

console = Console()

LLM_JUDGE_FLAG = "--llm-judge"
FAIL_ON_REGRESSION_FLAG = "--fail-on-regression"
DEFAULT_JUDGE_CACHE_DIR = Path("eval_results/llm_judge_cache")


def main() -> None:
    """Run eval and save results."""
    args = sys.argv[1:]
    llm_judge_enabled = LLM_JUDGE_FLAG in args
    fail_on_regression = FAIL_ON_REGRESSION_FLAG in args
    known_flags = {LLM_JUDGE_FLAG, FAIL_ON_REGRESSION_FLAG}
    positional = [a for a in args if a not in known_flags]

    if len(positional) not in (3, 4):
        console.print(
            "[red]Usage: python -m confluence_to_notion.eval"
            " <output_dir> <fixture_dir> <results_dir> [<samples_dir>]"
            " [--llm-judge] [--fail-on-regression][/red]"
        )
        sys.exit(1)

    output_dir = Path(positional[0])
    fixture_dir = Path(positional[1])
    results_dir = Path(positional[2])
    samples_dir = Path(positional[3]) if len(positional) == 4 else None

    # Load baseline BEFORE running/writing the current snapshot so the current
    # run is never picked as its own baseline.
    previous = load_latest_baseline(results_dir)

    report = run_eval(output_dir, fixture_dir, samples_dir=samples_dir)

    if llm_judge_enabled:
        if samples_dir is None:
            console.print(
                "[red]--llm-judge requires <samples_dir> to pair converted pages"
                " with originals[/red]"
            )
            sys.exit(1)
        converted_dir = output_dir / "converted"
        report.llm_judge = run_llm_judge(
            output_dir=converted_dir,
            samples_dir=samples_dir,
            cache_dir=DEFAULT_JUDGE_CACHE_DIR,
        )

    report.baseline_comparison = compare_to_baseline(report, previous)

    # Save results
    results_dir.mkdir(parents=True, exist_ok=True)
    timestamp_safe = report.timestamp.replace(":", "-").replace("+", "_")
    result_file = results_dir / f"{timestamp_safe}.json"
    result_file.write_text(report.model_dump_json(indent=2))

    # Print summary table
    table = Table(title="Eval Results")
    table.add_column("Agent", style="cyan")
    table.add_column("Status", style="bold")
    table.add_column("Recall", justify="right")
    table.add_column("Precision", justify="right")
    table.add_column("F1", justify="right")
    table.add_column("Missing", justify="right")
    table.add_column("Extra", justify="right")

    for r in report.results:
        status_style = {"pass": "green", "partial": "yellow", "fail": "red"}[r.status]
        table.add_row(
            r.agent_name,
            f"[{status_style}]{r.status}[/{status_style}]",
            f"{r.recall:.1%}",
            f"{r.precision:.1%}",
            f"{r.score:.1%}",
            str(len(r.missing_ids)),
            str(len(r.extra_ids)),
        )

    console.print(table)

    if report.semantic_coverage is not None:
        cov = report.semantic_coverage
        console.print(
            f"[cyan]Semantic coverage:[/cyan] {cov.coverage_ratio:.1%}"
            f" ({len(cov.covered_elements)}/{len(cov.sample_elements)} element kinds)"
            f" across {cov.pages_analyzed} pages"
        )

    if report.llm_judge is not None:
        _print_llm_judge_table(report.llm_judge)

    if report.baseline_comparison is not None:
        _print_baseline_summary(report.baseline_comparison)

    if report.prompt_changed:
        console.print("[yellow]⚠ Agent prompts changed since last commit[/yellow]")

    if report.overall_pass:
        console.print("[green]✓ All agents passed[/green]")
    else:
        console.print("[red]✗ Some agents failed — check missing/extra IDs above[/red]")
        sys.exit(1)

    if fail_on_regression and report.baseline_comparison is not None and (
        report.baseline_comparison.is_regression
    ):
        console.print(
            "[red]✗ Baseline regression detected and --fail-on-regression"
            " is set — exiting 1[/red]"
        )
        sys.exit(1)


def _print_llm_judge_table(judge_results: list) -> None:  # type: ignore[type-arg]
    """Render per-page LLM-as-judge scores. Signal only — never affects exit code."""
    if not judge_results:
        console.print("[yellow]LLM judge: no paired pages were scored[/yellow]")
        return

    table = Table(title="LLM-as-Judge Scores (1-5, signal only)")
    table.add_column("Page", style="cyan")
    table.add_column("Info", justify="right")
    table.add_column("Notion", justify="right")
    table.add_column("Struct", justify="right")
    table.add_column("Read", justify="right")
    table.add_column("Mean", justify="right", style="bold")
    table.add_column("Cache", justify="center")

    overall_means: list[float] = []
    for r in judge_results:
        info = r.scores["information_preservation"]
        idiom = r.scores["notion_idiom"]
        struct = r.scores["structure"]
        read = r.scores["readability"]
        mean = (info + idiom + struct + read) / 4
        overall_means.append(mean)
        table.add_row(
            r.page_id,
            str(info),
            str(idiom),
            str(struct),
            str(read),
            f"{mean:.2f}",
            "✓" if r.cache_hit else "·",
        )

    console.print(table)
    if overall_means:
        grand = sum(overall_means) / len(overall_means)
        console.print(f"[cyan]LLM judge overall mean:[/cyan] {grand:.2f}/5")


def _print_baseline_summary(cmp: BaselineComparison) -> None:
    """Render the baseline diff. Signal-only unless --fail-on-regression is set."""
    if cmp.previous_timestamp is None:
        console.print(
            "[cyan]Baseline:[/cyan] no prior snapshot — this run becomes the baseline"
        )
        return

    coverage_line = f"Δ semantic_coverage = {cmp.coverage_delta:+.1%}"
    if cmp.llm_judge_mean_delta is not None:
        judge_line = f", Δ llm_judge_mean = {cmp.llm_judge_mean_delta:+.2f}"
    else:
        judge_line = ", llm_judge delta unavailable"

    console.print(
        f"[cyan]Baseline ({cmp.previous_timestamp}):[/cyan] {coverage_line}{judge_line}"
    )

    if cmp.is_regression:
        console.print(
            f"[yellow]⚠ Baseline regression flagged:"
            f" {', '.join(cmp.regressions)}"
            f" (thresholds: {cmp.thresholds_used})[/yellow]"
        )


if __name__ == "__main__":
    main()
