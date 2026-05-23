#!/usr/bin/env python3
"""CLI entry point: python main.py --prd path/to/prd.md"""
from __future__ import annotations

import json
from enum import Enum
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from src.analyzer import PRDAnalyzer
from src.task_generator import TaskFormatter

app = typer.Typer(add_completion=False)
console = Console()


class OutputFormat(str, Enum):
    json = "json"
    markdown = "markdown"
    both = "both"


@app.command()
def analyze(
    prd: Path = typer.Option(..., "--prd", help="Path to PRD file (Markdown or plain text)"),
    output: Path = typer.Option(None, "--output", "-o", help="Output file stem (default: output). .json/.md suffix added automatically."),
    fmt: OutputFormat = typer.Option(OutputFormat.both, "--format", help="Output format: json | markdown | both"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show full task details in terminal"),
    jira: bool = typer.Option(False, "--jira", help="Include Jira-compatible issue format in JSON output"),
) -> None:
    """Analyze a PRD and generate structured development tasks using AI."""
    if not prd.exists():
        console.print(f"[red]Error: file not found: {prd}[/red]")
        raise typer.Exit(1)

    prd_text = prd.read_text(encoding="utf-8")
    console.print(
        Panel(
            f"[bold blue]AI PRD Analyzer[/bold blue]\nFile: [cyan]{prd.name}[/cyan]  "
            f"({len(prd_text):,} chars)",
            expand=False,
        )
    )

    with console.status("[bold green]Calling AI (this may take 15-30 seconds)..."):
        try:
            analyzer = PRDAnalyzer()
            result = analyzer.analyze(prd_text)
        except Exception as exc:
            console.print(f"[red]Analysis failed: {exc}[/red]")
            raise typer.Exit(1)

    # ── Summary banner ────────────────────────────────────────────────────────
    console.print(f"\n[bold green]✓ Analysis complete:[/bold green] {result.prd_title}")
    console.print(
        f"  Requirements : {result.summary.total_requirements} "
        f"(functional: {result.summary.functional_count}, "
        f"non-functional: {result.summary.non_functional_count})"
    )
    ambiguity_color = "yellow" if result.summary.ambiguity_count > 0 else "green"
    console.print(
        f"  Ambiguities  : [{ambiguity_color}]{result.summary.ambiguity_count}[/{ambiguity_color}]"
    )
    console.print(f"  Tasks        : [green]{result.summary.total_tasks}[/green]")
    console.print(f"  Total effort : [cyan]{result.summary.estimated_total_effort}[/cyan]")

    # ── Ambiguity report ──────────────────────────────────────────────────────
    if result.ambiguities:
        console.print("\n[bold yellow]⚠ Ambiguities — clarify with PM before sprint start:[/bold yellow]")
        for amb in result.ambiguities:
            console.print(f"\n  [{amb.id}] [bold]{amb.location}[/bold]")
            console.print(f"    Issue    : {amb.issue}")
            console.print(f"    Question : [italic]{amb.clarifying_question}[/italic]")

    # ── Tasks table ───────────────────────────────────────────────────────────
    table = Table(title="\nGenerated Development Tasks", show_lines=True, expand=False)
    table.add_column("ID", style="dim", width=10)
    table.add_column("Title", min_width=35)
    table.add_column("Effort", width=13)
    table.add_column("Risk", width=8)
    table.add_column("Deps", width=14)

    for task in result.tasks:
        risk_color = {"high": "red", "medium": "yellow", "low": "green"}.get(
            task.risk_level.value, "white"
        )
        deps = ", ".join(task.dependencies) if task.dependencies else "—"
        table.add_row(
            task.id,
            task.title,
            task.effort_estimate,
            f"[{risk_color}]{task.risk_level.value}[/{risk_color}]",
            deps,
        )
    console.print(table)

    # ── Verbose detail ────────────────────────────────────────────────────────
    if verbose:
        console.print("\n[bold]Task Details:[/bold]")
        for task in result.tasks:
            console.print(f"\n[bold]{task.id}: {task.title}[/bold]")
            console.print(f"  {task.description}")
            console.print("  Acceptance criteria:")
            for criterion in task.acceptance_criteria:
                console.print(f"    - {criterion}")

    # ── Resolve output paths from stem ───────────────────────────────────────
    stem = Path(output.stem if output else "output")
    json_path = stem.with_suffix(".json")
    md_path = stem.with_suffix(".md")

    formatter = TaskFormatter()

    # ── Write JSON ────────────────────────────────────────────────────────────
    if fmt in (OutputFormat.json, OutputFormat.both):
        output_dict = formatter.to_dict(result)
        if jira:
            output_dict["jira_issues"] = formatter.to_jira_format(result)
        json_path.write_text(
            json.dumps(output_dict, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        console.print(f"\n[green]JSON  saved → {json_path}[/green]")

    # ── Write Markdown ────────────────────────────────────────────────────────
    if fmt in (OutputFormat.markdown, OutputFormat.both):
        md_path.write_text(formatter.to_markdown(result), encoding="utf-8")
        console.print(f"[green]MD    saved → {md_path}[/green]")


if __name__ == "__main__":
    app()
