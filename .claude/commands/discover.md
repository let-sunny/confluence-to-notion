Run the discovery pipeline to extract Confluence → Notion transformation rules.

Usage: /discover <samples-dir> [--from N]

## What this does

Executes `scripts/discover.sh` which runs a 4-step pipeline:

1. **Pattern Discovery** (agent) — analyze XHTML samples → `output/patterns.json`
2. **Rule Proposer** (agent) — propose mapping rules → `output/proposals.json`
3. **Finalize** (cli) — proposals → `output/rules.json`
4. **Convert** (cli) — apply rules to XHTML → `output/converted/`

## Steps

1. Parse the samples directory from `$ARGUMENTS`. Default to `samples/` if empty.
2. Run: `bash scripts/discover.sh $ARGUMENTS`
3. Stream the output so the user can follow progress.
4. When complete, report:
   - Number of patterns discovered
   - Number of rules generated
   - Number of pages converted
   - Any errors or warnings
