"""Vapor render node — formats analysis results for terminal or JSON output.

Supports three output modes:
- Terminal: Rich color-coded panels with severity badges (default)
- JSON file: Pretty-printed AnalysisResult written to --output path
- Raw JSON: Pre-LLM collector state written to --save-raw path
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from vapor.graph.state import VaporState

SEVERITY_COLORS: dict[str, str] = {
    "critical": "bold red",
    "high": "bold yellow",
    "medium": "bold blue",
    "low": "bold green",
}

SEVERITY_ORDER: dict[str, int] = {
    "critical": 0,
    "high": 1,
    "medium": 2,
    "low": 3,
}


def _render_terminal(analysis: dict, config, llm_usage: dict, raw: dict) -> str:
    """Render color-coded Rich panels to terminal. Returns summary string."""
    console = Console()

    summary = analysis.get("summary", {})
    findings = analysis.get("findings", [])

    # Sort findings by severity descending (critical first, low last)
    findings = sorted(
        findings,
        key=lambda f: SEVERITY_ORDER.get(f.get("severity", "low"), 99),
    )

    # Header panel
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    header_text = f"[bold]Vapor — AWS Cost Audit Report[/bold]\nRegion: {config.region}  |  {timestamp}"
    console.print(Panel(header_text, style="bold cyan"))

    # Cost Explorer breakdown table (mini cost explorer)
    cost_explorer_data = raw.get("cost_explorer", {})
    if cost_explorer_data.get("available", False):
        services = cost_explorer_data.get("services", [])
        total_cost = cost_explorer_data.get("total_cost_usd", 0.0)

        # Filter and sort
        active_services = [s for s in services if s.get("cost_usd", 0) > 0.005]
        active_services.sort(key=lambda s: s.get("cost_usd", 0), reverse=True)

        if active_services:
            cost_table = Table(
                title=f"Cost Breakdown — {config.window_days}-Day Window (Total: ${total_cost:.2f})",
                show_header=True,
                header_style="bold magenta",
            )
            cost_table.add_column("Service", style="white", min_width=30)
            cost_table.add_column("Cost (USD)", justify="right", style="cyan")
            cost_table.add_column("%", justify="right", style="dim")

            for svc in active_services:
                svc_name = svc.get("service", "Unknown")
                svc_cost = svc.get("cost_usd", 0)
                pct = (svc_cost / total_cost * 100) if total_cost > 0 else 0
                cost_table.add_row(
                    svc_name,
                    f"${svc_cost:.2f}",
                    f"{pct:.1f}%",
                )

            console.print(cost_table)
            console.print()

    # Summary row table
    total = summary.get("totalFindings", 0)
    critical_count = summary.get("criticalCount", 0)
    high_count = summary.get("highCount", 0)
    savings = summary.get("estimatedMonthlySavings", 0)

    table = Table(show_header=True, header_style="bold")
    table.add_column("Total Findings")
    table.add_column("Critical", style="bold red")
    table.add_column("High", style="bold yellow")
    table.add_column("Est. Monthly Savings")
    table.add_row(
        str(total),
        str(critical_count),
        str(high_count),
        f"${savings:,.2f}" if isinstance(savings, (int, float)) else str(savings),
    )
    console.print(table)

    # Per-finding panels
    for finding in findings:
        severity = finding.get("severity", "low")
        color = SEVERITY_COLORS.get(severity, "white")
        badge = f"[{color}][{severity.upper()}][/{color}]"

        title = finding.get("title", "Unknown Finding")
        category = finding.get("category", "")
        resource_id = finding.get("resource_id", "")
        detail = finding.get("detail", "")
        estimated_savings = finding.get("estimated_savings", "")
        fix = finding.get("fix", "")

        body_lines = [
            f"{badge}  {title}",
            f"Category: {category}",
            f"Resource: {resource_id}",
            f"Detail: {detail}",
            f"Estimated Savings: {estimated_savings}",
            f"Fix: {fix}",
        ]
        body = "\n".join(body_lines)
        console.print(Panel(body, border_style=color))

    # LLM usage statistics
    if llm_usage and llm_usage.get("total_tokens", 0) > 0:
        usage_text = (
            f"[bold]LLM Usage[/bold] ({llm_usage.get('model', 'unknown')})\n"
            f"  Input tokens:  {llm_usage.get('input_tokens', 0):,}\n"
            f"  Output tokens: {llm_usage.get('output_tokens', 0):,}\n"
            f"  Total tokens:  {llm_usage.get('total_tokens', 0):,}"
        )
        console.print(Panel(usage_text, style="dim"))

    summary_str = (
        f"Findings: {total} | Critical: {critical_count} | "
        f"High: {high_count} | Est. Savings: ${savings:,.2f}/mo"
        if isinstance(savings, (int, float))
        else f"Findings: {total} | Critical: {critical_count} | High: {high_count}"
    )
    return summary_str


def _render_json_file(analysis: dict, path: str) -> None:
    """Write AnalysisResult as pretty-printed JSON with default=str."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(analysis, f, indent=2, default=str)


def _save_raw_json(raw: dict, path: str) -> None:
    """Write raw collector state as pretty-printed JSON with default=str."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(raw, f, indent=2, default=str)


def render(state: VaporState) -> dict:
    """Output analysis as Rich terminal panels or JSON file.

    If --save-raw is set, writes raw collector JSON first.
    If --output is set, writes analysis JSON to file.
    Otherwise, renders Rich panels to terminal.

    Returns:
        {"report": "<rendered_summary_string>"}
    """
    config = state["config"]
    analysis = state["analysis"]
    llm_usage = state.get("llm_usage", {})

    # Sort findings by severity before any output
    findings = analysis.get("findings", [])
    sorted_findings = sorted(
        findings,
        key=lambda f: SEVERITY_ORDER.get(f.get("severity", "low"), 99),
    )
    analysis = {**analysis, "findings": sorted_findings}

    # Save raw collector state if requested
    if config.save_raw:
        _save_raw_json(state["raw"], config.save_raw)

    # Determine output mode
    if config.output:
        # Include llm_usage in the JSON report
        output_data = {**analysis, "llm_usage": llm_usage}
        _render_json_file(output_data, config.output)
        console = Console()
        console.print(f"[green]Report written to:[/green] {config.output}")
        summary = analysis.get("summary", {})
        total = summary.get("totalFindings", 0)
        critical_count = summary.get("criticalCount", 0)
        high_count = summary.get("highCount", 0)
        savings = summary.get("estimatedMonthlySavings", 0)
        summary_str = (
            f"Findings: {total} | Critical: {critical_count} | "
            f"High: {high_count} | Est. Savings: ${savings:,.2f}/mo"
            if isinstance(savings, (int, float))
            else f"Findings: {total} | Critical: {critical_count} | High: {high_count}"
        )
    else:
        summary_str = _render_terminal(analysis, config, llm_usage, state["raw"])

    return {"report": summary_str}
