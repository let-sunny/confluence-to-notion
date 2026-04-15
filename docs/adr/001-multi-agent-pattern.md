# ADR-001: Multi-Agent Pipeline for Rule Discovery

**Status**: Accepted
**Date**: 2026-04-15

## Context

We need to migrate Confluence wikis to Notion while preserving page structure, macros, and formatting. Confluence stores content as XHTML with proprietary macros; Notion uses a block-based model. A naive single-pass LLM approach would require the model to simultaneously:

1. Identify all XHTML patterns and macros in the source
2. Propose appropriate Notion block mappings for each
3. Validate that mappings are consistent and complete
4. Resolve conflicts between competing mapping strategies

This is a complex reasoning task where a single prompt would exceed the optimal scope for reliable LLM output.

## Decision

Use a 4-agent pipeline where each agent has a focused responsibility:

1. **Pattern Discovery Agent** — Analyzes sample XHTML pages and extracts repeating structural patterns and Confluence macros
2. **Rule Proposer Agent** — Takes discovered patterns and proposes Confluence→Notion block mapping rules
3. **Rule Critic Agent** — Validates proposed rules against held-out sample pages, identifying gaps and conflicts
4. **Rule Arbitrator Agent** — Resolves conflicts between competing rules and produces the final ruleset

The agents communicate via typed Pydantic models. The output is a deterministic `rules.json` that is then applied by a non-LLM converter to perform the actual migration.

## Consequences

### Positive

- Each agent prompt is focused and testable independently
- Rules can be inspected, edited, and versioned as JSON before migration
- The deterministic converter step makes migrations reproducible
- Individual agents can be improved or replaced without affecting the full pipeline
- Eval can target specific agents rather than the entire pipeline

### Negative

- More complex orchestration code than a single-pass approach
- Higher total token usage due to inter-agent communication
- Requires careful schema design for agent-to-agent data contracts

## Alternatives Considered

### Single-pass LLM conversion

A single prompt that takes XHTML and outputs Notion blocks directly. Rejected because:
- Not reproducible (different outputs per run)
- No reusable rules — every page requires a full LLM call
- Hard to debug when specific patterns fail

### Manual rule authoring

Hand-write all transformation rules. Rejected because:
- Confluence macro ecosystem is large and varies per installation
- Initial discovery of all patterns is time-consuming
- LLM-assisted discovery covers more edge cases faster

### Two-agent (propose + validate)

Simpler pipeline with just a proposer and validator. Rejected because:
- Pattern discovery is a distinct task that benefits from focused prompting
- Conflict resolution needs its own decision logic when the critic rejects rules

## Prior Art

- **CanICode** (Figma design analysis): Uses a multi-agent pattern where one agent extracts design tokens, another proposes code mappings, and a third validates against a component library. Similar decomposition of "understand → propose → validate."
