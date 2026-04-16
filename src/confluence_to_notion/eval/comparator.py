"""Compare actual agent outputs against expected fixtures."""

import subprocess
from datetime import UTC, datetime
from pathlib import Path

from confluence_to_notion.agents.schemas import (
    DiscoveryOutput,
    EvalMatchResult,
    EvalReport,
    ProposerOutput,
)


def compare_discovery(actual: DiscoveryOutput, expected: DiscoveryOutput) -> EvalMatchResult:
    """Compare actual vs expected discovery output by pattern_id overlap."""
    expected_ids = {p.pattern_id for p in expected.patterns}
    actual_ids = {p.pattern_id for p in actual.patterns}

    matched = expected_ids & actual_ids
    missing = sorted(expected_ids - actual_ids)
    extra = sorted(actual_ids - expected_ids)
    score = len(matched) / len(expected_ids) if expected_ids else 1.0

    if score == 1.0:
        status = "pass"
    elif score > 0:
        status = "partial"
    else:
        status = "fail"

    return EvalMatchResult(
        agent_name="pattern-discovery",
        status=status,
        expected_ids=sorted(expected_ids),
        actual_ids=sorted(actual_ids),
        missing_ids=missing,
        extra_ids=extra,
        score=score,
    )


def compare_proposer(actual: ProposerOutput, expected: ProposerOutput) -> EvalMatchResult:
    """Compare actual vs expected proposer output by rule_id overlap."""
    expected_ids = {r.rule_id for r in expected.rules}
    actual_ids = {r.rule_id for r in actual.rules}

    matched = expected_ids & actual_ids
    missing = sorted(expected_ids - actual_ids)
    extra = sorted(actual_ids - expected_ids)
    score = len(matched) / len(expected_ids) if expected_ids else 1.0

    if score == 1.0:
        status = "pass"
    elif score > 0:
        status = "partial"
    else:
        status = "fail"

    return EvalMatchResult(
        agent_name="rule-proposer",
        status=status,
        expected_ids=sorted(expected_ids),
        actual_ids=sorted(actual_ids),
        missing_ids=missing,
        extra_ids=extra,
        score=score,
    )


def detect_prompt_changes() -> bool:
    """Check if agent prompt files changed since last commit."""
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD~1", "--", ".claude/agents/"],
            capture_output=True,
            text=True,
            check=False,
        )
        return bool(result.stdout.strip())
    except FileNotFoundError:
        return False


def run_eval(output_dir: Path, fixture_dir: Path) -> EvalReport:
    """Run full eval: compare actual outputs against expected fixtures."""
    actual_patterns = DiscoveryOutput.model_validate_json(
        (output_dir / "patterns.json").read_text()
    )
    expected_patterns = DiscoveryOutput.model_validate_json(
        (fixture_dir / "expected_patterns.json").read_text()
    )

    actual_proposals = ProposerOutput.model_validate_json(
        (output_dir / "proposals.json").read_text()
    )
    expected_proposals = ProposerOutput.model_validate_json(
        (fixture_dir / "expected_proposals.json").read_text()
    )

    discovery_result = compare_discovery(actual_patterns, expected_patterns)
    proposer_result = compare_proposer(actual_proposals, expected_proposals)

    results = [discovery_result, proposer_result]
    overall_pass = all(r.status == "pass" for r in results)
    prompt_changed = detect_prompt_changes()

    return EvalReport(
        timestamp=datetime.now(UTC).isoformat(),
        prompt_changed=prompt_changed,
        results=results,
        overall_pass=overall_pass,
    )
