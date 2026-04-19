"""CLI entry points for confluence-to-notion."""

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import httpx
import typer
from notion_client import APIResponseError
from pydantic import ValidationError
from rich.console import Console

from confluence_to_notion.config import Settings
from confluence_to_notion.confluence.client import ConfluenceClient
from confluence_to_notion.confluence.schemas import PageTreeNode
from confluence_to_notion.converter.converter import convert_page
from confluence_to_notion.converter.resolution import ResolutionStore
from confluence_to_notion.converter.schemas import NotionPropertyType, TableRule
from confluence_to_notion.converter.table_rules import (
    TableRuleStore,
    extract_data_rows_from_xhtml,
    extract_headers_from_xhtml,
    infer_column_types,
    normalize_header_signature,
)
from confluence_to_notion.notion.client import NotionClientWrapper
from confluence_to_notion.runs import (
    StepStatus,
    finalize_run,
    start_run,
    update_step,
)

app = typer.Typer(help="confluence-to-notion: auto-discover transformation rules")
console = Console()


def _stdin_is_tty() -> bool:
    """Indirection for sys.stdin.isatty so tests can patch it through CliRunner."""
    return sys.stdin.isatty()


def _load_settings() -> Settings:
    """Load settings from .env, showing a helpful error on missing fields."""
    try:
        return Settings()
    except ValidationError as e:
        console.print("[red]Configuration error:[/red]")
        for err in e.errors():
            field = ".".join(str(loc) for loc in err["loc"])
            console.print(f"  [red]• {field}: {err['msg']}[/red]")
        console.print("\nCheck your .env file. See .env.example for required variables.")
        raise typer.Exit(code=1) from None


@app.command()
def fetch(
    space: str | None = typer.Option(None, help="Confluence space key"),
    pages: str | None = typer.Option(None, help="Comma-separated page IDs"),
    limit: int = typer.Option(25, help="Max pages when using --space"),
    out_dir: Path = typer.Option(Path("samples"), help="Output directory"),
    url: str | None = typer.Option(
        None,
        "--url",
        help="Confluence source URL; when set, writes artifacts to output/runs/<slug>/",
    ),
) -> None:
    """Fetch Confluence pages and save XHTML to disk.

    Use --space to list pages from a space, or --pages to fetch specific IDs.
    When --url is provided, artifacts land under ``output/runs/<slug>/`` (samples/,
    source.json, status.json, report.md); otherwise writes to --out-dir only.

    Examples:
        cli fetch --space KAFKA --limit 10
        cli fetch --pages 12345,67890,11111
        cli fetch --url <confluence-url> --pages 12345
    """
    if not space and not pages:
        console.print("[red]Provide --space or --pages[/red]")
        raise typer.Exit(code=1)

    settings = _load_settings()
    client = ConfluenceClient(settings)

    page_ids = [p.strip() for p in pages.split(",") if p.strip()] if pages else None

    target_dir = out_dir
    run_dir: Path | None = None
    if url is not None:
        source_type = "space" if space else "page"
        root_id = page_ids[0] if page_ids and len(page_ids) == 1 else None
        run_dir, _ = start_run(Path("output"), url, source_type, root_id=root_id)
        target_dir = run_dir / "samples"
        update_step(run_dir, "fetch", StepStatus.RUNNING)

    async def _run() -> list[Path]:
        return await client.fetch_samples_to_disk(
            target_dir,
            space_key=space,
            page_ids=page_ids,
            limit=limit,
        )

    try:
        try:
            saved = asyncio.run(_run())
        except httpx.HTTPStatusError as e:
            if run_dir is not None:
                update_step(run_dir, "fetch", StepStatus.FAILED)
            msg = f"Confluence API error: {e.response.status_code} {e.response.text}"
            console.print(f"[red]{msg}[/red]")
            raise typer.Exit(code=1) from None
        except httpx.ConnectError as e:
            if run_dir is not None:
                update_step(run_dir, "fetch", StepStatus.FAILED)
            console.print(f"[red]Cannot connect to Confluence: {e}[/red]")
            raise typer.Exit(code=1) from None

        if run_dir is not None:
            update_step(run_dir, "fetch", StepStatus.DONE, count=len(saved))

        if not saved:
            console.print("[yellow]No pages fetched[/yellow]")
        else:
            console.print(f"[green]Saved {len(saved)} pages to {target_dir}[/green]")
            for p in saved:
                console.print(f"  {p}")
    finally:
        if run_dir is not None:
            finalize_run(run_dir)


@app.command(name="fetch-tree")
def fetch_tree(
    root_id: str = typer.Option(..., "--root-id", help="Confluence root page ID"),
    output: Path = typer.Option(
        Path("output/page-tree.json"), "--output", help="Output JSON path"
    ),
    url: str | None = typer.Option(
        None,
        "--url",
        help="Confluence source URL; when set, writes artifacts to output/runs/<slug>/",
    ),
) -> None:
    """Fetch the Confluence page tree starting from a root page.

    Recursively collects child pages and writes the hierarchy as JSON.
    When --url is provided, page-tree.json lands under ``output/runs/<slug>/``
    alongside source.json, status.json, and report.md; ``--output`` is ignored
    in that mode.

    Examples:
        cli fetch-tree --root-id 12345
        cli fetch-tree --root-id 12345 --output my-tree.json
        cli fetch-tree --url <confluence-url> --root-id 12345
    """
    settings = _load_settings()
    client = ConfluenceClient(settings)

    run_dir: Path | None = None
    target = output
    if url is not None:
        run_dir, _ = start_run(Path("output"), url, "tree", root_id=root_id)
        target = run_dir / "page-tree.json"
        update_step(run_dir, "fetch", StepStatus.RUNNING)

    async def _run() -> PageTreeNode:
        async with client:
            return await client.collect_page_tree(root_id)

    try:
        try:
            tree = asyncio.run(_run())
        except httpx.HTTPStatusError as e:
            if run_dir is not None:
                update_step(run_dir, "fetch", StepStatus.FAILED)
            msg = f"Confluence API error: {e.response.status_code} {e.response.text}"
            console.print(f"[red]{msg}[/red]")
            raise typer.Exit(code=1) from None
        except httpx.ConnectError as e:
            if run_dir is not None:
                update_step(run_dir, "fetch", StepStatus.FAILED)
            console.print(f"[red]Cannot connect to Confluence: {e}[/red]")
            raise typer.Exit(code=1) from None

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(tree.model_dump_json(indent=2) + "\n")

        if run_dir is not None:
            update_step(
                run_dir, "fetch", StepStatus.DONE, count=_count_tree_nodes(tree)
            )

        console.print(f"[green]Page tree saved to {target}[/green]")
    finally:
        if run_dir is not None:
            finalize_run(run_dir)


def _count_tree_nodes(node: PageTreeNode) -> int:
    """Return the total number of nodes in ``node`` (including itself)."""
    return 1 + sum(_count_tree_nodes(child) for child in node.children)


@app.command(name="notion-ping")
def notion_ping() -> None:
    """Validate Notion API token by fetching bot user info."""
    settings = _load_settings()
    try:
        settings.require_notion()
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1) from None
    client = NotionClientWrapper(settings)

    async def _run() -> bool:
        return await client.ping()

    try:
        ok = asyncio.run(_run())
    except (OSError, TimeoutError) as e:
        console.print(f"[red]Network error: {e}[/red]")
        raise typer.Exit(code=1) from None

    if ok:
        console.print("[green]Notion connection OK[/green]")
    else:
        console.print("[red]Notion connection FAILED — check NOTION_API_TOKEN in .env[/red]")
        raise typer.Exit(code=1)


@app.command()
def discover() -> None:
    """Run pattern discovery pipeline.

    The pipeline runs via bash script orchestrating independent claude -p sessions:
        bash scripts/discover.sh samples/
    """
    console.print("[yellow]Discovery runs via scripts/discover.sh, not this CLI.[/yellow]")
    console.print("  bash scripts/discover.sh samples/")
    console.print("  bash scripts/discover.sh samples/ --from 3  # resume from step 3")
    raise typer.Exit(code=1)


@app.command(name="validate-output")
def validate_output(
    file: Path = typer.Argument(..., help="JSON file to validate"),
    schema: str = typer.Argument(
        ..., help="Schema name: 'discovery', 'proposer', or 'scout'"
    ),
) -> None:
    """Validate an agent output file against its Pydantic schema.

    Examples:
        cli validate-output output/patterns.json discovery
        cli validate-output output/proposals.json proposer
        cli validate-output output/sources.json scout
    """
    from confluence_to_notion.agents.schemas import (
        DiscoveryOutput,
        ProposerOutput,
        ScoutOutput,
    )

    if not file.exists():
        console.print(f"[red]File not found: {file}[/red]")
        raise typer.Exit(code=1)

    raw = file.read_text()

    try:
        if schema == "discovery":
            obj_d = DiscoveryOutput.model_validate_json(raw)
            console.print(
                f"[green]Valid DiscoveryOutput: {obj_d.pages_analyzed} pages, "
                f"{len(obj_d.patterns)} patterns[/green]"
            )
        elif schema == "proposer":
            obj_p = ProposerOutput.model_validate_json(raw)
            console.print(f"[green]Valid ProposerOutput: {len(obj_p.rules)} rules[/green]")
        elif schema == "scout":
            obj_s = ScoutOutput.model_validate_json(raw)
            console.print(
                f"[green]Valid ScoutOutput: {len(obj_s.sources)} sources[/green]"
            )
        else:
            console.print(
                f"[red]Unknown schema '{schema}'. Use: discovery, proposer, scout[/red]"
            )
            raise typer.Exit(code=1)
    except ValidationError as e:
        console.print(f"[red]Validation failed for {file}:[/red]")
        for err in e.errors():
            loc = " → ".join(str(loc) for loc in err["loc"])
            console.print(f"  [red]• {loc}: {err['msg']}[/red]")
        raise typer.Exit(code=1) from None


@app.command()
def finalize(
    proposals_file: Path = typer.Argument(
        Path("output/proposals.json"), help="Path to proposals.json"
    ),
    out: Path = typer.Option(Path("output/rules.json"), help="Output rules.json path"),
) -> None:
    """Convert proposals.json → rules.json (2-agent shortcut).

    Promotes all proposed rules to final rules with enabled=True.
    When critic/arbitrator agents are added, this step will be replaced.
    """
    from confluence_to_notion.agents.schemas import FinalRuleset, ProposerOutput

    if not proposals_file.exists():
        console.print(f"[red]File not found: {proposals_file}[/red]")
        raise typer.Exit(code=1)

    raw = proposals_file.read_text()
    try:
        proposer = ProposerOutput.model_validate_json(raw)
    except ValidationError as e:
        console.print(f"[red]Invalid proposals file: {e.error_count()} errors[/red]")
        raise typer.Exit(code=1) from None

    ruleset = FinalRuleset.from_proposer_output(proposer)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(ruleset.model_dump_json(indent=2) + "\n")
    console.print(
        f"[green]Finalized {len(ruleset.rules)} rules → {out}[/green]"
    )


@app.command()
def convert(
    rules_file: Path = typer.Option(
        Path("output/rules.json"), "--rules", help="Path to rules.json"
    ),
    input_dir: Path = typer.Option(
        Path("samples"), "--input", help="Directory of XHTML files"
    ),
    output_dir: Path = typer.Option(
        Path("output/converted"), "--output", help="Output directory for converted JSON"
    ),
    url: str | None = typer.Option(
        None,
        "--url",
        help="Confluence source URL; when set, writes artifacts to output/runs/<slug>/",
    ),
) -> None:
    """Convert XHTML pages to Notion blocks using finalized rules.

    When --url is provided, converted JSON lands under ``output/runs/<slug>/converted/``
    alongside source.json, status.json, and report.md; ``--output`` is ignored in
    that mode.

    Examples:
        cli convert --rules output/rules.json --input samples/ --output output/converted/
        cli convert --url <confluence-url> --rules output/rules.json --input samples/
    """
    from confluence_to_notion.agents.schemas import FinalRuleset

    if not rules_file.exists():
        console.print(f"[red]Rules file not found: {rules_file}[/red]")
        raise typer.Exit(code=1)
    if not input_dir.exists():
        console.print(f"[red]Input directory not found: {input_dir}[/red]")
        raise typer.Exit(code=1)

    try:
        ruleset = FinalRuleset.model_validate_json(rules_file.read_text())
    except ValidationError as e:
        console.print(f"[red]Invalid rules file: {e.error_count()} errors[/red]")
        raise typer.Exit(code=1) from None

    xhtml_files = sorted(input_dir.glob("*.xhtml"))
    if not xhtml_files:
        console.print(f"[yellow]No .xhtml files found in {input_dir}[/yellow]")
        raise typer.Exit(code=1)

    run_dir: Path | None = None
    target_dir = output_dir
    if url is not None:
        run_dir, _ = start_run(Path("output"), url, "page", root_id=None)
        target_dir = run_dir / "converted"
        update_step(run_dir, "convert", StepStatus.RUNNING)

    target_dir.mkdir(parents=True, exist_ok=True)

    try:
        converted = 0
        try:
            for xhtml_path in xhtml_files:
                xhtml = xhtml_path.read_text()
                result = convert_page(xhtml, ruleset, page_id=xhtml_path.stem)
                out_file = target_dir / f"{xhtml_path.stem}.json"
                out_file.write_text(
                    json.dumps(result.blocks, indent=2, ensure_ascii=False) + "\n"
                )
                converted += 1
                console.print(
                    f"  {xhtml_path.name} → {out_file.name} ({len(result.blocks)} blocks)"
                )
        except (OSError, ValueError, KeyError):
            if run_dir is not None:
                update_step(run_dir, "convert", StepStatus.FAILED)
            raise

        if run_dir is not None:
            update_step(run_dir, "convert", StepStatus.DONE, count=converted)

        console.print(f"[green]Converted {converted} pages → {target_dir}[/green]")
    finally:
        if run_dir is not None:
            finalize_run(run_dir)


@app.command()
def migrate(
    rules_file: Path = typer.Option(
        Path("output/rules.json"), "--rules", help="Path to rules.json"
    ),
    input_dir: Path = typer.Option(
        Path("samples"), "--input", help="Directory of XHTML files"
    ),
    target: str | None = typer.Option(
        None, "--target", help="Notion parent page ID (fallback: NOTION_ROOT_PAGE_ID)"
    ),
    url: str | None = typer.Option(
        None,
        "--url",
        help="Confluence source URL; when set, writes artifacts to output/runs/<slug>/",
    ),
) -> None:
    """Convert XHTML pages and publish them to Notion.

    When --url is provided, status.json and report.md land under
    ``output/runs/<slug>/`` alongside source.json; otherwise no run-dir
    artifacts are written.

    Examples:
        cli migrate --rules output/rules.json --input samples/ --target <page-id>
        cli migrate --url <confluence-url> --rules output/rules.json --input samples/
        cli migrate  # uses defaults + NOTION_ROOT_PAGE_ID from .env
    """
    from confluence_to_notion.agents.schemas import FinalRuleset
    from confluence_to_notion.converter.converter import convert_page

    # Validate inputs
    if not rules_file.exists():
        console.print(f"[red]Rules file not found: {rules_file}[/red]")
        raise typer.Exit(code=1)
    if not input_dir.exists():
        console.print(f"[red]Input directory not found: {input_dir}[/red]")
        raise typer.Exit(code=1)

    settings = _load_settings()
    parent_id = target or settings.notion_root_page_id
    if not parent_id:
        console.print(
            "[red]No target page ID. Use --target or set NOTION_ROOT_PAGE_ID in .env[/red]"
        )
        raise typer.Exit(code=1)

    try:
        ruleset = FinalRuleset.model_validate_json(rules_file.read_text())
    except ValidationError as e:
        console.print(f"[red]Invalid rules file: {e.error_count()} errors[/red]")
        raise typer.Exit(code=1) from None

    xhtml_files = sorted(input_dir.glob("*.xhtml"))
    if not xhtml_files:
        console.print(f"[yellow]No .xhtml files found in {input_dir}[/yellow]")
        raise typer.Exit(code=1)

    try:
        settings.require_notion()
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1) from None

    client = NotionClientWrapper(settings)

    async def _migrate() -> tuple[int, int]:
        from rich.progress import Progress

        succeeded = 0
        failed = 0

        with Progress(console=console) as progress:
            task = progress.add_task("Migrating pages...", total=len(xhtml_files))

            for xhtml_path in xhtml_files:
                try:
                    xhtml = xhtml_path.read_text()
                    result = convert_page(xhtml, ruleset, page_id=xhtml_path.stem)
                    title = _extract_title(result.blocks, fallback=xhtml_path.stem)

                    await client.create_page(
                        parent_id=parent_id, title=title, blocks=result.blocks
                    )
                    succeeded += 1
                    console.print(f"  [green]{xhtml_path.name}[/green] → {title}")
                except APIResponseError as e:
                    failed += 1
                    console.print(
                        f"  [red]{xhtml_path.name}: Notion API error"
                        f" {e.status} — {e.body}[/red]"
                    )
                except (OSError, ValueError, KeyError) as e:
                    failed += 1
                    console.print(f"  [red]{xhtml_path.name}: {e}[/red]")
                finally:
                    progress.advance(task)

        return succeeded, failed

    run_dir: Path | None = None
    if url is not None:
        run_dir, _ = start_run(
            Path("output"),
            url,
            "page",
            root_id=None,
            notion_target={"page_id": parent_id},
        )
        update_step(run_dir, "migrate", StepStatus.RUNNING)

    try:
        try:
            succeeded, failed = asyncio.run(_migrate())
        except (APIResponseError, OSError, ValueError, KeyError):
            if run_dir is not None:
                update_step(run_dir, "migrate", StepStatus.FAILED)
            raise

        if run_dir is not None:
            if failed > 0:
                update_step(
                    run_dir,
                    "migrate",
                    StepStatus.FAILED,
                    count=succeeded,
                    warnings=failed,
                )
            else:
                update_step(
                    run_dir, "migrate", StepStatus.DONE, count=succeeded
                )

        console.print(
            f"\n[green]Succeeded: {succeeded}[/green] | [red]Failed: {failed}[/red]"
        )

        if failed > 0:
            raise typer.Exit(code=1)
    finally:
        if run_dir is not None:
            finalize_run(run_dir)


@app.command(name="migrate-tree")
def migrate_tree(
    tree: Path = typer.Option(
        Path("output/page-tree.json"), "--tree", help="Path to page-tree.json"
    ),
    target: str | None = typer.Option(
        None,
        "--target",
        help="Notion parent page ID (fallback: NOTION_ROOT_PAGE_ID)",
    ),
    resolution_out: Path = typer.Option(
        Path("output/resolution.json"),
        "--resolution-out",
        help="Where to persist title→Notion page ID mapping",
    ),
) -> None:
    """Create an empty Notion page hierarchy mirroring a Confluence tree.

    Reads a page-tree.json produced by ``fetch-tree``, creates an empty Notion
    page for each node under --target (or NOTION_ROOT_PAGE_ID), and persists
    the resulting ``title → notion_page_id`` mapping to the resolution store
    so that later conversion passes can resolve internal page links.
    """
    if not tree.exists():
        console.print(f"[red]Tree file not found: {tree}[/red]")
        raise typer.Exit(code=1)

    settings = _load_settings()
    parent_id = target or settings.notion_root_page_id
    if not parent_id:
        console.print(
            "[red]No target page ID. Use --target or set NOTION_ROOT_PAGE_ID in .env[/red]"
        )
        raise typer.Exit(code=1)

    try:
        settings.require_notion()
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1) from None

    try:
        tree_node = PageTreeNode.model_validate_json(tree.read_text(encoding="utf-8"))
    except ValidationError as e:
        console.print(f"[red]Invalid tree file: {e.error_count()} errors[/red]")
        for err in e.errors():
            loc = " → ".join(str(loc) for loc in err["loc"])
            console.print(f"  [red]• {loc}: {err['msg']}[/red]")
        raise typer.Exit(code=1) from None

    client = NotionClientWrapper(settings)

    async def _run() -> dict[str, str]:
        return await client.create_page_tree(parent_id=parent_id, tree=tree_node)

    try:
        mapping = asyncio.run(_run())
    except APIResponseError as e:
        console.print(f"[red]Notion API error {e.status} — {e.body}[/red]")
        raise typer.Exit(code=1) from None

    store = ResolutionStore(resolution_out)
    for title, notion_page_id in mapping.items():
        store.add(
            key=f"page_link:{title}",
            resolved_by="notion_migration",
            value={"notion_page_id": notion_page_id},
        )
    store.save()

    console.print(
        f"[green]Created {len(mapping)} Notion pages → {resolution_out}[/green]"
    )


@app.command(name="migrate-tree-pages")
def migrate_tree_pages(
    root_id: str = typer.Option(
        ..., "--root-id", help="Confluence root page ID"
    ),
    target: str | None = typer.Option(
        None,
        "--target",
        help="Notion parent page ID (fallback: NOTION_ROOT_PAGE_ID)",
    ),
    resolution_out: Path = typer.Option(
        Path("output/resolution.json"),
        "--resolution-out",
        help="Where to persist title→Notion page ID mapping",
    ),
    rules_file: Path = typer.Option(
        Path("output/rules.json"), "--rules", help="Path to rules.json"
    ),
    table_rules_file: Path = typer.Option(
        Path("output/rules/table-rules.json"),
        "--table-rules",
        help="Path to table-rules.json (header-signature → Notion DB rule)",
    ),
) -> None:
    """Run the multi-pass migration: tree → table-rule discovery → body upload.

    Pass 1 collects the Confluence tree, creates empty Notion pages, and persists
    a ``page_link:{title}`` resolution store. Pass 1.5 fetches each page's XHTML,
    discovers tables whose header signatures lack a rule, and (when run on a TTY)
    prompts the operator to classify them as layout tables or Notion databases.
    Pass 2 converts each page using both stores and appends the blocks to Notion.
    """
    from confluence_to_notion.agents.schemas import FinalRuleset

    if not rules_file.exists():
        console.print(f"[red]Rules file not found: {rules_file}[/red]")
        raise typer.Exit(code=1)

    settings = _load_settings()
    parent_id = target or settings.notion_root_page_id
    if not parent_id:
        console.print(
            "[red]No target page ID. Use --target or set NOTION_ROOT_PAGE_ID in .env[/red]"
        )
        raise typer.Exit(code=1)

    try:
        settings.require_notion()
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1) from None

    try:
        ruleset = FinalRuleset.model_validate_json(rules_file.read_text())
    except ValidationError as e:
        console.print(f"[red]Invalid rules file: {e.error_count()} errors[/red]")
        raise typer.Exit(code=1) from None

    confluence = ConfluenceClient(settings)
    notion = NotionClientWrapper(settings)
    table_rule_store = TableRuleStore(table_rules_file)

    async def _run() -> tuple[int, int]:
        async with confluence:
            tree = await confluence.collect_page_tree(root_id)

            # --- Pass 1: create empty Notion pages mirroring the Confluence tree ---
            id_to_notion: dict[str, str] = {}
            id_to_title: dict[str, str] = {}
            store = ResolutionStore(resolution_out)

            async def _create_subtree(node: PageTreeNode, parent: str) -> None:
                notion_page_id = await notion.create_subpage(parent, node.title)
                id_to_notion[node.id] = notion_page_id
                id_to_title[node.id] = node.title
                store.add(
                    key=f"page_link:{node.title}",
                    resolved_by="notion_migration",
                    value={"notion_page_id": notion_page_id},
                )
                for child in node.children:
                    await _create_subtree(child, notion_page_id)

            await _create_subtree(tree, parent_id)
            store.save()

            # --- Pass 1.5: discover unresolved table signatures, prompt for rules ---
            xhtml_cache: dict[str, str] = {}
            for confluence_id in id_to_notion:
                page = await confluence.get_page(confluence_id)
                xhtml_cache[confluence_id] = page.storage_body

            # Tracks every unresolved table instance discovered during pre-convert,
            # so a single signature can be created once and applied to every instance.
            unresolved_tables: list[tuple[str, str, list[str]]] = []
            seen_signatures: set[str] = set()
            interactive = _stdin_is_tty()
            for confluence_id, xhtml in xhtml_cache.items():
                pre_result = convert_page(
                    xhtml,
                    ruleset,
                    page_id=confluence_id,
                    store=store,
                    table_rules=table_rule_store,
                )
                for item in pre_result.unresolved:
                    if item.kind != "table" or not item.context_xhtml:
                        continue
                    headers = extract_headers_from_xhtml(item.context_xhtml)
                    if not headers:
                        continue
                    unresolved_tables.append((confluence_id, item.identifier, headers))
                    sig = normalize_header_signature(headers)
                    if sig in seen_signatures:
                        continue
                    seen_signatures.add(sig)
                    if table_rule_store.lookup(headers) is not None:
                        continue
                    if not interactive:
                        console.print(
                            f"[yellow]Unresolved table signature (non-TTY, "
                            f"skipping prompt): {sig}[/yellow]"
                        )
                        continue
                    sample_rows = extract_data_rows_from_xhtml(item.context_xhtml)
                    draft = infer_column_types(sample_rows, headers)
                    rule = _prompt_table_rule(
                        headers=headers,
                        sample_rows=sample_rows,
                        column_type_draft=draft,
                    )
                    table_rule_store.upsert(headers, rule)
                    table_rule_store.save()

            # For every is_database=True signature, create the Notion database once
            # under the page where it was first observed and write a resolution
            # entry for every instance so Pass 2 emits child_database blocks.
            db_id_by_signature: dict[str, str] = {}
            for confluence_id, identifier, headers in unresolved_tables:
                resolved_rule = table_rule_store.lookup(headers)
                if resolved_rule is None or not resolved_rule.is_database:
                    continue
                if resolved_rule.column_types is None or resolved_rule.title_column is None:
                    continue
                sig = normalize_header_signature(headers)
                if sig not in db_id_by_signature:
                    parent_for_db = id_to_notion[confluence_id]
                    db_id_by_signature[sig] = await notion.create_database(
                        parent_id=parent_for_db,
                        title=resolved_rule.title_column,
                        title_column=resolved_rule.title_column,
                        column_types=resolved_rule.column_types,
                    )
                store.add(
                    key=f"table:{identifier}",
                    resolved_by="notion_migration",
                    value={"database_id": db_id_by_signature[sig]},
                )
            if db_id_by_signature:
                store.save()

            # --- Pass 2: convert with both stores and append to Notion ---
            succeeded = 0
            failed = 0
            for confluence_id, notion_page_id in id_to_notion.items():
                title = id_to_title[confluence_id]
                xhtml = xhtml_cache[confluence_id]
                try:
                    result = convert_page(
                        xhtml,
                        ruleset,
                        page_id=confluence_id,
                        store=store,
                        table_rules=table_rule_store,
                    )
                    await notion.append_blocks(notion_page_id, result.blocks)
                    succeeded += 1
                    console.print(f"  [green]{title}[/green] → {notion_page_id}")
                except APIResponseError as e:
                    failed += 1
                    console.print(
                        f"  [red]{title}: Notion API error {e.status} — {e.body}[/red]"
                    )
                    raise

            return succeeded, failed

    try:
        succeeded, failed = asyncio.run(_run())
    except APIResponseError:
        raise typer.Exit(code=1) from None

    console.print(
        f"\n[green]Succeeded: {succeeded}[/green] | [red]Failed: {failed}[/red]"
    )
    if failed > 0:
        raise typer.Exit(code=1)


def _prompt_table_rule(
    *,
    headers: list[str],
    sample_rows: list[list[str]],
    column_type_draft: dict[str, NotionPropertyType],
) -> TableRule:
    """Show a table preview and ask the operator to classify it.

    Returns a ``TableRule`` describing whether the table should become a Notion
    database and, if so, which column is the title and what type each column is.
    """
    from rich.table import Table as RichTable

    preview = RichTable(title="Confluence table preview", show_lines=True)
    for h in headers:
        preview.add_column(h)
    for row in sample_rows[:5]:
        preview.add_row(*row)
    console.print(preview)
    console.print(f"[cyan]Inferred column types:[/cyan] {column_type_draft}")

    is_db = typer.confirm("Convert to Notion database?", default=False)
    if not is_db:
        return TableRule(is_database=False)

    # Persisted signatures are lowercased/stripped (normalize_header_signature), so
    # title_column and column_types keys must match that form or TableRuleSet
    # validation rejects the store on the next load and wipes every rule.
    normalized_headers = [h.strip().lower() for h in headers]
    valid_headers = set(normalized_headers)
    normalized_types: dict[str, NotionPropertyType] = {
        k.strip().lower(): v for k, v in column_type_draft.items()
    }

    if _stdin_is_tty():
        while True:
            title_col = typer.prompt("Title column", default=headers[0])
            normalized_title = title_col.strip().lower()
            if normalized_title in valid_headers:
                break
            console.print(
                f"[yellow]'{title_col}' is not a header. "
                f"Choose one of: {', '.join(headers)}[/yellow]"
            )
    else:
        title_col = typer.prompt("Title column", default=headers[0])
        normalized_title = title_col.strip().lower()
        if normalized_title not in valid_headers:
            fallback = normalized_headers[0]
            console.print(
                f"[yellow]title_col '{title_col}' not in headers; "
                f"falling back to '{fallback}'[/yellow]"
            )
            normalized_title = fallback

    return TableRule(
        is_database=True,
        title_column=normalized_title,
        column_types=normalized_types,
    )


def _extract_title(blocks: list[dict[str, Any]], *, fallback: str) -> str:
    """Extract title from the first heading block's rich_text content."""
    for block in blocks:
        block_type = block.get("type", "")
        if block_type in ("heading_1", "heading_2", "heading_3"):
            rich_text = block.get(block_type, {}).get("rich_text", [])
            parts = [seg.get("text", {}).get("content", "") for seg in rich_text]
            title = "".join(parts).strip()
            if title:
                return title
    return fallback


if __name__ == "__main__":
    app()
