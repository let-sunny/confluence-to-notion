# Converter golden corpus

This directory holds the equivalence corpus consumed by
`tests/converter/equivalence.test.ts`. Each `<pageId>.xhtml` is paired
with a `<pageId>.expected.json` capturing the Notion blocks the Python
converter at HEAD `635aa58` (`112afeb~1`) emits for that page. The TS
port must produce the exact same blocks (modulo key ordering, which the
custom `toMatchNotionBlocks` matcher normalises).

The 6 `2782*/2783*/2784*/2913*` ids are the original `samples/*.xhtml`
pages regenerated from Python HEAD as part of the issue #157 pre-flight
check. The `9000000*` ids are synthetic minimal pages added to cover
the categories listed below — they are deliberately small so the
expected JSON stays auditable by hand.

## Coverage map

| Page id  | Categories covered                                                |
| -------- | ----------------------------------------------------------------- |
| 27821302 (samples) | full Confluence space dump — table-of-contents, panels, expand, ac:link, mixed inline |
| 27822128 (samples) | headings, paragraphs, simple bulleted list                       |
| 27835336 (samples) | code macros, jira macros, panels, layout-cell tables             |
| 27849051 (samples) | minimal page                                                     |
| 29130755 (samples) | macro fallthroughs, ac:image                                     |
| 29130800 (samples) | nested lists, ac:image, panel + code combo                       |
| 90000001 | CDATA section inside `code` macro `plain-text-body`              |
| 90000002 | `info` panel (ac:structured-macro variant)                       |
| 90000003 | `code` macro with language parameter                             |
| 90000004 | `jira` macro                                                     |
| 90000005 | `excerpt-include` macro pointing at a page link                  |
| 90000006 | `ri:user` link inside `ac:link`                                  |
| 90000007 | `ri:attachment` link with `ac:plain-text-link-body`              |
| 90000008 | `ri:attachment` image (`ac:image` element)                       |
| 90000009 | nested table inside `ac:layout` / `ac:layout-cell`               |
| 90000010 | entity edge — non-breaking space (`&#160;`)                      |
| 90000011 | entity edge — en-dash (`&#8211;`)                                |
| 90000012 | entity edge — ellipsis (`&#8230;`)                               |
| 90000013 | entity edge — right single quotation mark (`&#x2019;`)           |
| 90000014 | `ac:emoticon` macro                                              |
| 90000015 | `ac:task-list` task list                                         |
| 90000016 | mixed inline formatting — bold inside italic inside link         |
| 90000017 | `expand` wrapping `code` (audit checklist)                       |
| 90000018 | `expand` wrapping `info` + `code` (audit checklist)              |
| 90000019 | `info` wrapping `code` (audit checklist)                         |
| 90000020 | `panel` (note) wrapping `jira` + `code` (audit checklist)        |
| 90000021 | `warning` wrapping `info` (audit checklist)                      |
| 90000022 | simple table baseline (audit checklist)                          |
| 90000023 | heading levels h1 through h6                                     |
| 90000024 | numbered list with nested bulleted children                      |

## Regenerating expected JSON

If the Python converter is updated and the TS converter must match the
new behaviour, regenerate the `.expected.json` files from the Python
HEAD worktree:

```
git worktree add ../c2n-python 112afeb~1
cd ../c2n-python
uv run c2n convert --url https://example.atlassian.net/wiki/x \
  --rules <comprehensive-rules.json> --input <fixtures-dir>
```

The "comprehensive rules.json" must enable every rule the Python
converter checks: `rule:element:heading`, `paragraph`, `list`,
`ac-image`, `rule:macro:toc`, `jira`, `code`, `expand`, `info`, `note`,
`warning`, `tip`. See `output/dev/preflight-drift.md` for the exact
invocation used in PR 2c.
