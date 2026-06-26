"""Vapor CLI configuration module."""

from dataclasses import dataclass


@dataclass
class AuditConfig:
    """Configuration for a Vapor AWS cost audit run.

    Holds all CLI parameters and threshold values used by collectors
    and the aggregate node to determine resource verdicts.
    """

    region: str = "us-east-1"
    window_days: int = 30
    ec2_cpu_avg_threshold: float = 10.0
    ec2_cpu_max_threshold: float = 40.0
    rds_cpu_avg_threshold: float = 10.0
    rds_connections_threshold: int = 5
    rds_memory_free_pct_threshold: float = 75.0
    save_raw: str | None = None
    output: str | None = None
