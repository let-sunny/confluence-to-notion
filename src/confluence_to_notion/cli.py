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
    space: str = typer.Option(..., help="Confluence space key"),
    limit: int = typer.Option(25, help="Max number of pages to fetch"),
    out_dir: Path = typer.Option(Path("samples"), help="Output directory"),
) -> None:
    """Fetch Confluence pages and save XHTML to disk."""
    settings = _load_settings()
    client = ConfluenceClient(settings)

    async def _run() -> list[Path]:
        return await client.fetch_samples_to_disk(space, out_dir, limit=limit)

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
        console.print(f"[yellow]No pages found in space '{space}'[/yellow]")
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
    """Run pattern discovery agent. (Day 2)"""
    console.print("[yellow]Not implemented yet[/yellow]")
    raise typer.Exit(code=1)


@app.command()
def migrate() -> None:
    """Run migration pipeline. (Day 3)"""
    console.print("[yellow]Not implemented yet[/yellow]")
    raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
