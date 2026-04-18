"""CLI entry point for the eval framework.

Usage:
    uv run python -m confluence_to_notion.eval \
        <output_dir> <fixture_dir> <results_dir> [<samples_dir>] [--llm-judge]

The optional ``--llm-judge`` flag opts into the LLM-as-judge pass that scores
each converted page across the 4 quality dimensions. Results attach to
``EvalReport.llm_judge`` and are signal only (per ADR-004) — they do not flip
the overall pass/fail exit code. Default runs do not call Anthropic.
"""

import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

from confluence_to_notion.eval.comparator import run_eval
from confluence_to_notion.eval.llm_judge import run_llm_judge

console = Console()

LLM_JUDGE_FLAG = "--llm-judge"
DEFAULT_JUDGE_CACHE_DIR = Path("eval_results/llm_judge_cache")


def main() -> None:
    """Run eval and save results."""
    args = sys.argv[1:]
    llm_judge_enabled = LLM_JUDGE_FLAG in args
    positional = [a for a in args if a != LLM_JUDGE_FLAG]

    if len(positional) not in (3, 4):
        console.print(
            "[red]Usage: python -m confluence_to_notion.eval"
            " <output_dir> <fixture_dir> <results_dir> [<samples_dir>] [--llm-judge][/red]"
        )
        sys.exit(1)

    output_dir = Path(positional[0])
    fixture_dir = Path(positional[1])
    results_dir = Path(positional[2])
    samples_dir = Path(positional[3]) if len(positional) == 4 else None

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

    if report.prompt_changed:
        console.print("[yellow]⚠ Agent prompts changed since last commit[/yellow]")

    if report.overall_pass:
        console.print("[green]✓ All agents passed[/green]")
    else:
        console.print("[red]✗ Some agents failed — check missing/extra IDs above[/red]")
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


if __name__ == "__main__":
    main()
