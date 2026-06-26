"""Aggregate node for the Vapor pipeline.

Normalizes all raw collector data into a list of Finding TypedDicts with
pre-computed verdicts and estimated costs. Converts datetime objects to
ISO strings. Creates gap findings for collector errors.

Requirements: 10.1 through 10.16
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from vapor.config import AuditConfig
    from vapor.graph.state import VaporState

# On-demand EC2 pricing (USD/hour) for common instance types
EC2_HOURLY_USD: dict[str, float] = {
    "t3.micro": 0.0104,
    "t3.small": 0.0208,
    "t3.medium": 0.0416,
    "t3.large": 0.0832,
    "t3.xlarge": 0.1664,
    "t3.2xlarge": 0.3328,
    "m5.large": 0.096,
    "m5.xlarge": 0.192,
    "m5.2xlarge": 0.384,
    "m5.4xlarge": 0.768,
    "m5.8xlarge": 1.536,
    "c5.large": 0.085,
    "c5.xlarge": 0.17,
    "c5.2xlarge": 0.34,
    "r5.large": 0.126,
    "r5.xlarge": 0.252,
    "r5.2xlarge": 0.504,
}

# EBS monthly cost per GB by volume type
EBS_MONTHLY_PER_GB: dict[str, float] = {
    "gp3": 0.08,
    "gp2": 0.10,
    "io1": 0.125,
}

# Monthly cost for an unassociated Elastic IP ($0.005/hour × 730)
EIP_MONTHLY_USD: float = 3.65


def _serialize_datetimes(obj: object) -> object:
    """Recursively convert datetime objects to ISO 8601 strings.

    Handles dicts, lists, and bare datetime values. Returns the
    transformed structure with all datetimes replaced by their
    `.isoformat()` string representation.
    """
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _serialize_datetimes(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_serialize_datetimes(item) for item in obj]
    return obj


def _compute_ec2_verdict(instance: dict, config: "AuditConfig") -> tuple[str, str]:
    """Return (verdict, issue) for an EC2 instance based on CPU thresholds.

    Decision logic:
    - If cpu.no_data is true → ("no_data", "instance_no_metrics")
    - If cpu.avg < avg_threshold AND cpu.max < max_threshold → ("underutilized", "underutilized_instance")
    - Otherwise → ("healthy", "healthy_instance")
    """
    cpu = instance.get("cpu", {})

    if cpu.get("no_data", False):
        return ("no_data", "instance_no_metrics")

    avg = cpu.get("avg")
    max_val = cpu.get("max")

    if (
        avg is not None
        and max_val is not None
        and avg < config.ec2_cpu_avg_threshold
        and max_val < config.ec2_cpu_max_threshold
    ):
        return ("underutilized", "underutilized_instance")

    return ("healthy", "healthy_instance")


def _compute_rds_verdict(db: dict, config: "AuditConfig") -> list[tuple[str, str]]:
    """Return list of (verdict, issue) tuples for an RDS instance.

    RDS can have multiple issues simultaneously:
    - If cpu.avg < threshold AND connections_max < threshold → underutilized
    - If memory_free_pct > threshold → overprovisioned_memory
    - If neither condition is met → healthy
    """
    verdicts: list[tuple[str, str]] = []

    cpu = db.get("cpu", {})
    cpu_avg = cpu.get("avg")
    connections_max = db.get("connections_max")
    memory_free_pct = db.get("memory_free_pct")

    # Check underutilization
    if (
        cpu_avg is not None
        and connections_max is not None
        and cpu_avg < config.rds_cpu_avg_threshold
        and connections_max < config.rds_connections_threshold
    ):
        verdicts.append(("underutilized", "underutilized_database"))

    # Check overprovisioned memory
    if (
        memory_free_pct is not None
        and memory_free_pct > config.rds_memory_free_pct_threshold
    ):
        verdicts.append(("overprovisioned_memory", "overprovisioned_memory"))

    # Default to healthy if no issues found
    if not verdicts:
        verdicts.append(("healthy", "healthy_database"))

    return verdicts


def _estimate_ec2_cost(instance_type: str) -> float | None:
    """Lookup hourly rate × 730 hours. Returns None if type is unknown."""
    hourly = EC2_HOURLY_USD.get(instance_type)
    if hourly is None:
        return None
    return hourly * 730


def _estimate_ebs_cost(size_gb: int, volume_type: str) -> float | None:
    """Compute monthly cost based on volume type and size.

    Returns per-GB monthly rate × size_gb, or None if volume_type is unknown.
    """
    rate = EBS_MONTHLY_PER_GB.get(volume_type)
    if rate is None:
        return None
    return rate * size_gb


def aggregate(state: "VaporState") -> dict:
    """Normalize all raw collector data into Finding list with pre-computed verdicts.

    Reads state["config"] for thresholds and region, processes raw data from
    state["raw"] for each collector, builds Finding objects, handles datetime
    serialization, and creates gap findings for errors.

    Returns:
        {"findings": [Finding, ...]}
    """
    config: "AuditConfig" = state["config"]
    raw = state.get("raw", {})
    errors = state.get("errors", [])
    region = config.region
    findings: list[dict] = []

    # --- EC2 Findings ---
    ec2_data = raw.get("ec2", {}).get("data", [])
    for instance in ec2_data:
        verdict, issue = _compute_ec2_verdict(instance, config)
        instance_type = instance.get("instance_type", "unknown")
        cost = _estimate_ec2_cost(instance_type)

        data = _serialize_datetimes({
            "instance_type": instance_type,
            "state": instance.get("state"),
            "launch_time": instance.get("launch_time"),
            "availability_zone": instance.get("availability_zone"),
            "cpu": instance.get("cpu", {}),
            "ebs_volumes": instance.get("ebs_volumes", []),
            "memory": {
                "available": False,
                "reason": "CloudWatch agent required \u2014 not collected",
            },
        })

        findings.append({
            "resource_id": instance.get("instance_id", "unknown"),
            "resource_type": "EC2",
            "region": region,
            "issue": issue,
            "verdict": verdict,
            "estimated_monthly_cost_usd": cost,
            "data": data,
            "tags": instance.get("tags", {}),
        })

    # --- RDS Findings ---
    rds_data = raw.get("rds", {}).get("data", [])
    for db in rds_data:
        verdict_list = _compute_rds_verdict(db, config)

        data = _serialize_datetimes({
            "db_instance_class": db.get("db_instance_class"),
            "engine": db.get("engine"),
            "engine_version": db.get("engine_version"),
            "status": db.get("status"),
            "multi_az": db.get("multi_az"),
            "publicly_accessible": db.get("publicly_accessible"),
            "allocated_storage_gb": db.get("allocated_storage_gb"),
            "storage_type": db.get("storage_type"),
            "cpu": db.get("cpu", {}),
            "connections_max": db.get("connections_max"),
            "memory_free_pct": db.get("memory_free_pct"),
            "memory_freeable_gb": db.get("memory_freeable_gb"),
        })

        for verdict, issue in verdict_list:
            findings.append({
                "resource_id": db.get("db_instance_id", "unknown"),
                "resource_type": "RDS",
                "region": region,
                "issue": issue,
                "verdict": verdict,
                "estimated_monthly_cost_usd": None,
                "data": data,
                "tags": db.get("tags", {}),
            })

    # --- S3 Findings ---
    s3_data = raw.get("s3", {}).get("data", [])
    for bucket in s3_data:
        has_lifecycle = bucket.get("has_lifecycle_policy", True)
        if not has_lifecycle:
            verdict = "no_lifecycle_policy"
            issue = "missing_lifecycle_policy"
        else:
            verdict = "healthy"
            issue = "healthy_bucket"

        data = _serialize_datetimes({
            "has_lifecycle_policy": has_lifecycle,
            "creation_date": bucket.get("creation_date"),
        })

        findings.append({
            "resource_id": bucket.get("bucket_name", "unknown"),
            "resource_type": "S3",
            "region": region,
            "issue": issue,
            "verdict": verdict,
            "estimated_monthly_cost_usd": None,
            "data": data,
            "tags": bucket.get("tags", {}),
        })

    # --- Lambda Findings ---
    lambda_data = raw.get("lambda_funcs", {}).get("data", [])
    for func in lambda_data:
        memory_size = func.get("memory_size", 0)
        timeout = func.get("timeout", 0)

        if memory_size >= 1024:
            verdict = "high_memory"
            issue = "high_memory_function"
        elif timeout >= 900:
            verdict = "high_timeout"
            issue = "high_timeout_function"
        else:
            verdict = "healthy"
            issue = "healthy_function"

        data = _serialize_datetimes({
            "runtime": func.get("runtime"),
            "memory_size": memory_size,
            "timeout": timeout,
            "last_modified": func.get("last_modified"),
            "code_size_bytes": func.get("code_size_bytes"),
        })

        findings.append({
            "resource_id": func.get("function_name", "unknown"),
            "resource_type": "Lambda",
            "region": region,
            "issue": issue,
            "verdict": verdict,
            "estimated_monthly_cost_usd": None,
            "data": data,
            "tags": func.get("tags", {}),
        })

    # --- EBS Findings ---
    ebs_data = raw.get("ebs", {}).get("data", [])
    for volume in ebs_data:
        size_gb = volume.get("size_gb", 0)
        volume_type = volume.get("volume_type", "")
        cost = _estimate_ebs_cost(size_gb, volume_type)

        data = _serialize_datetimes({
            "size_gb": size_gb,
            "volume_type": volume_type,
            "create_time": volume.get("create_time"),
            "availability_zone": volume.get("availability_zone"),
        })

        findings.append({
            "resource_id": volume.get("volume_id", "unknown"),
            "resource_type": "EBS",
            "region": region,
            "issue": "unattached_volume",
            "verdict": "unattached",
            "estimated_monthly_cost_usd": cost,
            "data": data,
            "tags": volume.get("tags", {}),
        })

    # --- EIP Findings ---
    eip_data = raw.get("eip", {}).get("data", [])
    for eip in eip_data:
        data = {
            "public_ip": eip.get("public_ip"),
        }

        findings.append({
            "resource_id": eip.get("allocation_id", "unknown"),
            "resource_type": "EIP",
            "region": region,
            "issue": "unassociated_eip",
            "verdict": "unassociated",
            "estimated_monthly_cost_usd": EIP_MONTHLY_USD,
            "data": data,
            "tags": eip.get("tags", {}),
        })

    # --- Cost Explorer Findings ---
    cost_explorer_data = raw.get("cost_explorer", {})
    if cost_explorer_data.get("available", False):
        services = cost_explorer_data.get("services", [])
        total_cost = cost_explorer_data.get("total_cost_usd", 0.0)

        # Filter services with cost > $0.00 and sort by cost descending
        active_services = [
            s for s in services if s.get("cost_usd", 0) > 0.005
        ]
        active_services.sort(key=lambda s: s.get("cost_usd", 0), reverse=True)

        # Build a detailed cost breakdown string
        breakdown_lines = []
        for svc in active_services:
            svc_name = svc.get("service", "Unknown")
            svc_cost = svc.get("cost_usd", 0)
            pct = (svc_cost / total_cost * 100) if total_cost > 0 else 0
            breakdown_lines.append({
                "service": svc_name,
                "cost_usd": round(svc_cost, 2),
                "percentage": round(pct, 1),
            })

        data = _serialize_datetimes({
            "total_cost_usd": round(total_cost, 2),
            "period_days": config.window_days,
            "service_count": len(active_services),
            "cost_breakdown": breakdown_lines,
        })

        findings.append({
            "resource_id": "cost-explorer-summary",
            "resource_type": "CostExplorer",
            "region": region,
            "issue": "cost_summary",
            "verdict": "informational",
            "estimated_monthly_cost_usd": total_cost,
            "data": data,
            "tags": {},
        })

    # --- Gap Findings for Collector Errors ---
    for error_msg in errors:
        findings.append({
            "resource_id": "collector-error",
            "resource_type": "Gap",
            "region": region,
            "issue": "collector_error",
            "verdict": "gap",
            "estimated_monthly_cost_usd": None,
            "data": {"error": error_msg},
            "tags": {},
        })

    return {"findings": findings}
