"""Produce an EvalReport: semantic coverage + prompt-change signal."""

import subprocess
from datetime import UTC, datetime
from pathlib import Path

from confluence_to_notion.agents.schemas import DiscoveryOutput, EvalReport
from confluence_to_notion.eval.semantic_coverage import analyze_coverage


def detect_prompt_changes() -> bool:
    """Check if agent prompt files changed since last commit.

    Returns False on any git error (shallow clone, initial commit, missing git).
    """
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD~1", "--", ".claude/agents/"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return False
        return bool(result.stdout.strip())
    except FileNotFoundError:
        return False


def run_eval(output_dir: Path, samples_dir: Path | None = None) -> EvalReport:
    """Build an EvalReport from actual agent outputs.

    If ``samples_dir`` is given, compute semantic coverage of the actual
    ``patterns.json`` against the element kinds enumerated in sample pages.
    Callers attach ``llm_judge`` / ``baseline_comparison`` afterward.
    """
    actual_patterns = DiscoveryOutput.model_validate_json(
        (output_dir / "patterns.json").read_text()
    )

    semantic_coverage = (
        analyze_coverage(samples_dir, actual_patterns) if samples_dir is not None else None
    )

    return EvalReport(
        timestamp=datetime.now(UTC).isoformat(),
        prompt_changed=detect_prompt_changes(),
        semantic_coverage=semantic_coverage,
    )
