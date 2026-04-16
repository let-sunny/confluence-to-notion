"""CLI entry points for confluence-to-notion."""

import asyncio
import json
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
from confluence_to_notion.converter.resolution import ResolutionStore
from confluence_to_notion.notion.client import NotionClientWrapper

app = typer.Typer(help="confluence-to-notion: auto-discover transformation rules")
console = Console()


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
) -> None:
    """Fetch Confluence pages and save XHTML to disk.

    Use --space to list pages from a space, or --pages to fetch specific IDs.

    Examples:
        cli fetch --space KAFKA --limit 10
        cli fetch --pages 12345,67890,11111
    """
    if not space and not pages:
        console.print("[red]Provide --space or --pages[/red]")
        raise typer.Exit(code=1)

    settings = _load_settings()
    client = ConfluenceClient(settings)

    page_ids = [p.strip() for p in pages.split(",") if p.strip()] if pages else None

    async def _run() -> list[Path]:
        return await client.fetch_samples_to_disk(
            out_dir,
            space_key=space,
            page_ids=page_ids,
            limit=limit,
        )

    try:
        saved = asyncio.run(_run())
    except httpx.HTTPStatusError as e:
        msg = f"Confluence API error: {e.response.status_code} {e.response.text}"
        console.print(f"[red]{msg}[/red]")
        raise typer.Exit(code=1) from None
    except httpx.ConnectError as e:
        console.print(f"[red]Cannot connect to Confluence: {e}[/red]")
        raise typer.Exit(code=1) from None

    if not saved:
        console.print("[yellow]No pages fetched[/yellow]")
    else:
        console.print(f"[green]Saved {len(saved)} pages to {out_dir}[/green]")
        for p in saved:
            console.print(f"  {p}")


@app.command(name="fetch-tree")
def fetch_tree(
    root_id: str = typer.Option(..., "--root-id", help="Confluence root page ID"),
    output: Path = typer.Option(
        Path("output/page-tree.json"), "--output", help="Output JSON path"
    ),
) -> None:
    """Fetch the Confluence page tree starting from a root page.

    Recursively collects child pages and writes the hierarchy as JSON.

    Examples:
        cli fetch-tree --root-id 12345
        cli fetch-tree --root-id 12345 --output my-tree.json
    """
    settings = _load_settings()
    client = ConfluenceClient(settings)

    async def _run() -> None:
        async with client:
            tree = await client.collect_page_tree(root_id)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(tree.model_dump_json(indent=2) + "\n")

    try:
        asyncio.run(_run())
    except httpx.HTTPStatusError as e:
        msg = f"Confluence API error: {e.response.status_code} {e.response.text}"
        console.print(f"[red]{msg}[/red]")
        raise typer.Exit(code=1) from None
    except httpx.ConnectError as e:
        console.print(f"[red]Cannot connect to Confluence: {e}[/red]")
        raise typer.Exit(code=1) from None

    console.print(f"[green]Page tree saved to {output}[/green]")


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
) -> None:
    """Convert XHTML pages to Notion blocks using finalized rules.

    Examples:
        cli convert --rules output/rules.json --input samples/ --output output/converted/
    """
    from confluence_to_notion.agents.schemas import FinalRuleset
    from confluence_to_notion.converter.converter import convert_page

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

    output_dir.mkdir(parents=True, exist_ok=True)
    converted = 0

    for xhtml_path in xhtml_files:
        xhtml = xhtml_path.read_text()
        result = convert_page(xhtml, ruleset, page_id=xhtml_path.stem)
        out_file = output_dir / f"{xhtml_path.stem}.json"
        out_file.write_text(
            json.dumps(result.blocks, indent=2, ensure_ascii=False) + "\n"
        )
        converted += 1
        console.print(
            f"  {xhtml_path.name} → {out_file.name} ({len(result.blocks)} blocks)"
        )

    console.print(f"[green]Converted {converted} pages → {output_dir}[/green]")


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
) -> None:
    """Convert XHTML pages and publish them to Notion.

    Examples:
        cli migrate --rules output/rules.json --input samples/ --target <page-id>
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

    succeeded, failed = asyncio.run(_migrate())
    console.print(f"\n[green]Succeeded: {succeeded}[/green] | [red]Failed: {failed}[/red]")

    if failed > 0:
        raise typer.Exit(code=1)


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
