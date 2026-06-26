"""User message builder for the LLM analysis prompt."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from vapor.config import AuditConfig
    from vapor.graph.state import Finding


def build_user_message(findings: list[Finding], config: AuditConfig) -> str:
    """Format findings and config context into a user message for the LLM.

    Includes region, window_days, resource count, and all threshold values
    so the LLM has full context for its analysis.
    """
    context = (
        f"Region: {config.region}\n"
        f"Window: {config.window_days} days\n"
        f"Total resources analyzed: {len(findings)}\n"
        f"Thresholds:\n"
        f"  EC2 CPU avg: {config.ec2_cpu_avg_threshold}%\n"
        f"  EC2 CPU max: {config.ec2_cpu_max_threshold}%\n"
        f"  RDS CPU avg: {config.rds_cpu_avg_threshold}%\n"
        f"  RDS connections: {config.rds_connections_threshold}\n"
        f"  RDS memory free pct: {config.rds_memory_free_pct_threshold}%\n"
    )

    findings_json = json.dumps(findings, indent=2, default=str)

    return f"{context}\nFindings:\n{findings_json}"
