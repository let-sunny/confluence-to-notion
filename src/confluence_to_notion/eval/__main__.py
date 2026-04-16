"""CLI entry point for the eval framework.

Usage: uv run python -m confluence_to_notion.eval <output_dir> <fixture_dir> <results_dir>
"""

import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

from confluence_to_notion.eval.comparator import run_eval

console = Console()


def main() -> None:
    """Run eval and save results."""
    if len(sys.argv) != 4:
        console.print(
            "[red]Usage: python -m confluence_to_notion.eval"
            " <output_dir> <fixture_dir> <results_dir>[/red]"
        )
        sys.exit(1)

    output_dir = Path(sys.argv[1])
    fixture_dir = Path(sys.argv[2])
    results_dir = Path(sys.argv[3])

    report = run_eval(output_dir, fixture_dir)

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

    if report.prompt_changed:
        console.print("[yellow]⚠ Agent prompts changed since last commit[/yellow]")

    if report.overall_pass:
        console.print("[green]✓ All agents passed[/green]")
    else:
        console.print("[red]✗ Some agents failed — check missing/extra IDs above[/red]")
        sys.exit(1)


if __name__ == "__main__":
    main()
