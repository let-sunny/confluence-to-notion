---
'confluence-to-notion': minor
---

Initial public release of the TypeScript rewrite of `confluence-to-notion`.
This is the first npm publish for the package; it ships the full PR series
[#129](https://github.com/let-sunny/confluence-to-notion/issues/129) that
ported the project from Python to Node 20 / TypeScript and re-introduced the
end-to-end Confluence → Notion migration pipeline.

Highlights:

- Frozen CLI surface per
  [ADR-00M](../.claude/docs/ADR-00M-cli-surface-freeze.md) (`fetch`,
  `fetch-tree`, `notion-ping`, `validate-output`, `finalize`, `convert`,
  `eval`, `migrate`, `migrate-tree`, `migrate-tree-pages`).
- Deterministic XHTML → Notion converter with a golden-fixture gate
  ([#163](https://github.com/let-sunny/confluence-to-notion/pull/163),
  [#164](https://github.com/let-sunny/confluence-to-notion/pull/164)).
- Eval harness with LLM-as-judge parity gate
  ([#151](https://github.com/let-sunny/confluence-to-notion/pull/151),
  [#170](https://github.com/let-sunny/confluence-to-notion/pull/170)).
- MCP server with parity gate
  ([#171](https://github.com/let-sunny/confluence-to-notion/pull/171)) and
  read-only handlers `c2n_convert_page`, `c2n_fetch_page`, `c2n_list_runs`,
  `c2n_get_run_report`
  ([#173](https://github.com/let-sunny/confluence-to-notion/pull/173)).
