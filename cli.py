"""
FDA Recall Monitor CLI — built with Typer.

Commands:
  run       One-shot poll (use --dry-run to skip DB writes)
  watch     Start the scheduler (continuous polling on cron schedule)
  report    Print the last N recalls from the database
  export    Export the database to CSV or JSON
  stats     Show database statistics
"""

from __future__ import annotations

import asyncio
import csv
import json
import logging
import sys
from enum import Enum
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.logging import RichHandler

from agent.config import AgentConfig
from agent.database import Database
from agent.reporter import TerminalReporter
from agent.scheduler import run_pipeline, start_scheduler

app = typer.Typer(
    name="fda-monitor",
    help="FDA Recall Monitoring Agent -- poll, deduplicate, and log FDA recalls.",
    add_completion=False,
    pretty_exceptions_enable=True,
)

console = Console()
_DEFAULT_CONFIG = Path("config.yaml")


def _setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(rich_tracebacks=True, markup=True)],
    )


def _load_config(config_path: Path) -> AgentConfig:
    return AgentConfig(config_path if config_path.exists() else None)


# ─────────────────────────────────────────────────────────────────────────────
# run
# ─────────────────────────────────────────────────────────────────────────────

@app.command()
def run(
    config: Path = typer.Option(_DEFAULT_CONFIG, "--config", "-c", help="Path to config.yaml"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Fetch & parse but do not persist or notify"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable DEBUG logging"),
) -> None:
    """Run a one-shot recall poll cycle."""
    cfg = _load_config(config)
    _setup_logging("DEBUG" if verbose else cfg.log_level)
    asyncio.run(run_pipeline(cfg, dry_run=dry_run))


# ─────────────────────────────────────────────────────────────────────────────
# watch
# ─────────────────────────────────────────────────────────────────────────────

@app.command()
def watch(
    config: Path = typer.Option(_DEFAULT_CONFIG, "--config", "-c", help="Path to config.yaml"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable DEBUG logging"),
) -> None:
    """Start the continuous scheduler (polls on configured cron schedule)."""
    cfg = _load_config(config)
    _setup_logging("DEBUG" if verbose else cfg.log_level)
    console.print(
        f"[bold cyan]FDA Recall Monitor[/bold cyan] — watching on schedule: "
        f"[yellow]{cfg.schedule_cron}[/yellow] UTC"
    )
    start_scheduler(cfg)


# ─────────────────────────────────────────────────────────────────────────────
# report
# ─────────────────────────────────────────────────────────────────────────────

@app.command()
def report(
    config: Path = typer.Option(_DEFAULT_CONFIG, "--config", "-c", help="Path to config.yaml"),
    last: int = typer.Option(20, "--last", "-n", help="Number of recent recalls to display"),
    category: Optional[str] = typer.Option(None, "--category", help="Filter by category (drug/device/food)"),
    classification: Optional[str] = typer.Option(None, "--class", help="Filter by class (I/II/III)"),
) -> None:
    """Print recent recalls from the local database."""
    cfg = _load_config(config)
    _setup_logging(cfg.log_level)

    async def _query() -> list[dict]:
        async with Database(cfg.db_path) as db:
            if category:
                return await db.get_by_category(category.lower(), last)
            if classification:
                return await db.get_by_classification(classification, last)
            return await db.get_recent(last)

    rows = asyncio.run(_query())
    if not rows:
        console.print("[dim]No records in database. Run [bold]fda-monitor run[/bold] first.[/dim]")
        raise typer.Exit(0)

    from agent.models import RecallRecord
    records = [RecallRecord.from_db_row(row) for row in rows]
    TerminalReporter().print_recalls(records, title=f"Last {len(records)} Recalls")


# ─────────────────────────────────────────────────────────────────────────────
# export
# ─────────────────────────────────────────────────────────────────────────────

class ExportFormat(str, Enum):
    json = "json"
    csv = "csv"
    ndjson = "ndjson"


@app.command()
def export(
    config: Path = typer.Option(_DEFAULT_CONFIG, "--config", "-c", help="Path to config.yaml"),
    output: Path = typer.Option(Path("data/export.json"), "--output", "-o", help="Output file path"),
    fmt: ExportFormat = typer.Option(ExportFormat.json, "--format", "-f", help="Output format"),
) -> None:
    """Export the full recall database to JSON, CSV, or NDJSON."""
    cfg = _load_config(config)
    _setup_logging(cfg.log_level)

    async def _export() -> list[dict]:
        async with Database(cfg.db_path) as db:
            return await db.get_all_for_export()

    rows = asyncio.run(_export())
    if not rows:
        console.print("[yellow]Database is empty.[/yellow]")
        raise typer.Exit(0)

    output.parent.mkdir(parents=True, exist_ok=True)

    if fmt == ExportFormat.json:
        output.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    elif fmt == ExportFormat.ndjson:
        with open(output, "w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
    elif fmt == ExportFormat.csv:
        if rows:
            with open(output, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=rows[0].keys())
                writer.writeheader()
                writer.writerows(rows)

    console.print(f"[green]✓[/green] Exported {len(rows)} records to [cyan]{output}[/cyan] ({fmt.value})")


# ─────────────────────────────────────────────────────────────────────────────
# stats
# ─────────────────────────────────────────────────────────────────────────────

@app.command()
def stats(
    config: Path = typer.Option(_DEFAULT_CONFIG, "--config", "-c", help="Path to config.yaml"),
) -> None:
    """Show database statistics (totals by category, classification, status)."""
    cfg = _load_config(config)
    _setup_logging(cfg.log_level)

    async def _stats() -> dict:
        async with Database(cfg.db_path) as db:
            return await db.count_stats()

    s = asyncio.run(_stats())
    TerminalReporter().print_stats(s)


# ─────────────────────────────────────────────────────────────────────────────
# Entrypoint
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app()
