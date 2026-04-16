"""Eval framework for comparing agent outputs against expected fixtures."""

from confluence_to_notion.eval.comparator import (
    compare_discovery,
    compare_proposer,
    run_eval,
)

__all__ = ["compare_discovery", "compare_proposer", "run_eval"]
