"""
Reporter — rich terminal output + self-contained HTML report + NDJSON log.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Sequence

from jinja2 import Environment, FileSystemLoader, select_autoescape
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from agent.models import RecallRecord, RunSummary

logger = logging.getLogger(__name__)
console = Console()

# ── Classification colour map ─────────────────────────────────────────────────
_CLASS_STYLE = {
    "Class I": "bold red",
    "Class II": "bold yellow",
    "Class III": "bold green",
}


def _class_style(record: RecallRecord) -> str:
    return _CLASS_STYLE.get(record.class_label, "white")


# ─────────────────────────────────────────────────────────────────────────────
# Terminal reporter
# ─────────────────────────────────────────────────────────────────────────────

class TerminalReporter:
    """Renders recall records to the terminal using Rich."""

    def print_recalls(self, records: Sequence[RecallRecord], title: str = "FDA Recalls") -> None:
        if not records:
            console.print(Panel("[dim]No recalls to display.[/dim]", title=title))
            return

        table = Table(
            title=title,
            box=box.ROUNDED,
            show_header=True,
            header_style="bold cyan",
            expand=True,
        )
        table.add_column("Date", style="dim", width=10, no_wrap=True)
        table.add_column("Class", width=9, no_wrap=True)
        table.add_column("Category", width=8)
        table.add_column("Recall #", width=14, no_wrap=True)
        table.add_column("Firm", width=22)
        table.add_column("Product", ratio=2)
        table.add_column("Status", width=11)

        for r in records:
            style = _class_style(r)
            date_str = _fmt_date(r.report_date)
            table.add_row(
                date_str,
                Text(r.class_label, style=style),
                r.category.capitalize(),
                r.recall_number or "—",
                r.recalling_firm[:22] if r.recalling_firm else "—",
                r.product_description[:80] if r.product_description else "—",
                r.status or "—",
            )

        console.print(table)

    def print_summary(self, summary: RunSummary) -> None:
        lines = [
            f"[cyan]Run ID:[/cyan]        {summary.run_id}",
            f"[cyan]Started:[/cyan]       {summary.started_at}",
            f"[cyan]Finished:[/cyan]      {summary.finished_at}",
            f"[green]New records:[/green]   {summary.total_new}",
            f"[yellow]Duplicates:[/yellow]    {summary.total_duplicates}",
            f"[blue]Total fetched:[/blue] {summary.total_fetched}",
        ]
        if summary.total_errors:
            lines.append(f"[red]Errors:[/red]        {summary.total_errors}")
        console.print(Panel("\n".join(lines), title="[bold]Run Summary[/bold]", border_style="cyan"))

    def print_stats(self, stats: dict) -> None:
        console.print(Panel(
            f"[green]Total recalls in DB:[/green] {stats.get('total_recalls', 0)}\n"
            f"[dim]Last run:[/dim] {stats.get('last_run', 'never')}",
            title="[bold]Database Stats[/bold]",
        ))

        if by_cat := stats.get("by_category"):
            t = Table(title="By Category", box=box.SIMPLE)
            t.add_column("Category", style="cyan")
            t.add_column("Count", justify="right")
            for k, v in sorted(by_cat.items(), key=lambda x: -x[1]):
                t.add_row(k.capitalize(), str(v))
            console.print(t)

        if by_cls := stats.get("by_classification"):
            t = Table(title="By Classification", box=box.SIMPLE)
            t.add_column("Classification")
            t.add_column("Count", justify="right")
            for k, v in sorted(by_cls.items(), key=lambda x: -x[1]):
                style = _CLASS_STYLE.get(k, "white")
                t.add_row(Text(k or "Unknown", style=style), str(v))
            console.print(t)


# ─────────────────────────────────────────────────────────────────────────────
# HTML reporter
# ─────────────────────────────────────────────────────────────────────────────

class HtmlReporter:
    """Generates a self-contained Bootstrap HTML report via Jinja2."""

    def __init__(self, template_dir: Path) -> None:
        self._env = Environment(
            loader=FileSystemLoader(str(template_dir)),
            autoescape=select_autoescape(["html"]),
        )

    def render(
        self,
        records: Sequence[RecallRecord],
        summary: RunSummary,
        output_path: Path,
    ) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        template = self._env.get_template("report.html.j2")
        html = template.render(
            records=[r.to_dict() for r in records],
            summary=summary.to_dict(),
            generated_at=datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
            class_colours={"Class I": "danger", "Class II": "warning", "Class III": "success"},
        )
        output_path.write_text(html, encoding="utf-8")
        logger.info("HTML report written to %s", output_path)


# ─────────────────────────────────────────────────────────────────────────────
# NDJSON logger
# ─────────────────────────────────────────────────────────────────────────────

class NdjsonLogger:
    """Appends recall records as newline-delimited JSON for downstream pipelines."""

    def __init__(self, log_path: Path) -> None:
        self.log_path = log_path

    def append(self, records: Sequence[RecallRecord]) -> None:
        if not records:
            return
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.log_path, "a", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r.to_dict(), ensure_ascii=False) + "\n")
        logger.debug("Appended %d records to %s", len(records), self.log_path)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _fmt_date(date_str: str) -> str:
    """Convert YYYYMMDD to YYYY-MM-DD for display."""
    if date_str and len(date_str) == 8:
        return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
    return date_str or "—"
