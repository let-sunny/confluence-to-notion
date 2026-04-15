"""CLI entry points for confluence-to-notion."""

import asyncio
from pathlib import Path

import httpx
import typer
from pydantic import ValidationError
from rich.console import Console

from confluence_to_notion.config import Settings
from confluence_to_notion.confluence.client import ConfluenceClient
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


@app.command(name="notion-ping")
def notion_ping() -> None:
    """Validate Notion API token by fetching bot user info."""
    settings = _load_settings()
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

    This is a convenience hint. The actual pipeline runs via Claude Code subagents:
        claude -p "/discover samples/"
    """
    console.print("[yellow]Discovery runs via Claude Code subagents, not this CLI.[/yellow]")
    console.print('  claude -p "/discover samples/"')
    raise typer.Exit(code=1)


@app.command()
def migrate() -> None:
    """Run migration pipeline. (Day 3)"""
    console.print("[yellow]Not implemented yet[/yellow]")
    raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
