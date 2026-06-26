"""Vapor CLI entry point.

Parses command-line arguments, loads environment variables, builds the
audit configuration, and invokes the LangGraph pipeline.
"""

from __future__ import annotations

import argparse
import sys

from rich.console import Console

from vapor.config import AuditConfig

console = Console()


def parse_args() -> argparse.Namespace:
    """Define and parse all CLI arguments with defaults."""
    parser = argparse.ArgumentParser(
        prog="vapor",
        description="Audit an AWS account for cost waste.",
    )
    parser.add_argument(
        "--region",
        type=str,
        default="us-east-1",
        help="Target AWS region (default: us-east-1)",
    )
    parser.add_argument(
        "--window-days",
        type=int,
        default=30,
        help="CloudWatch lookback window in days (default: 30)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Path to write analysis JSON output",
    )
    parser.add_argument(
        "--save-raw",
        type=str,
        default=None,
        help="Path to write raw collector JSON",
    )
    parser.add_argument(
        "--ec2-cpu-avg-threshold",
        type=float,
        default=10.0,
        help="EC2 CPU average %% underutilization threshold (default: 10.0)",
    )
    parser.add_argument(
        "--ec2-cpu-max-threshold",
        type=float,
        default=40.0,
        help="EC2 CPU max %% underutilization threshold (default: 40.0)",
    )
    parser.add_argument(
        "--rds-cpu-avg-threshold",
        type=float,
        default=10.0,
        help="RDS CPU average %% underutilization threshold (default: 10.0)",
    )
    parser.add_argument(
        "--rds-connections-threshold",
        type=int,
        default=5,
        help="RDS idle connections threshold (default: 5)",
    )
    parser.add_argument(
        "--rds-memory-free-pct",
        type=float,
        default=75.0,
        help="RDS memory over-provisioned %% threshold (default: 75.0)",
    )
    return parser.parse_args()


def build_config(args: argparse.Namespace) -> AuditConfig:
    """Convert parsed args namespace to AuditConfig dataclass."""
    return AuditConfig(
        region=args.region,
        window_days=args.window_days,
        output=args.output,
        save_raw=args.save_raw,
        ec2_cpu_avg_threshold=args.ec2_cpu_avg_threshold,
        ec2_cpu_max_threshold=args.ec2_cpu_max_threshold,
        rds_cpu_avg_threshold=args.rds_cpu_avg_threshold,
        rds_connections_threshold=args.rds_connections_threshold,
        rds_memory_free_pct_threshold=args.rds_memory_free_pct,
    )


def main() -> None:
    """Parse CLI arguments, load environment, build config, invoke graph pipeline."""
    try:
        from dotenv import load_dotenv

        load_dotenv()

        args = parse_args()
        config = build_config(args)

        initial_state = {
            "config": config,
            "raw": {},
            "errors": [],
            "findings": [],
            "analysis": {"summary": {}, "findings": []},
            "llm_usage": {"model": "", "input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
            "report": "",
        }

        from vapor.graph.graph import build_graph

        graph = build_graph()
        graph.invoke(initial_state)

        sys.exit(0)
    except Exception as e:
        console.print(f"[bold red]Fatal error:[/] {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
