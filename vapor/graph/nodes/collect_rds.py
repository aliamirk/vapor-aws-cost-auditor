"""RDS collector node for the Vapor pipeline.

Paginates all RDS instances, batches CloudWatch metrics (CPUUtilization avg/max,
FreeableMemory avg, DatabaseConnections max) in a single get_metric_data call
with 3600s period, and returns normalized RDS instance data.

Critical: FreeableMemory is in bytes — divide by 1024^3 for GB.

Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import boto3

if TYPE_CHECKING:
    from vapor.config import AuditConfig
    from vapor.graph.state import VaporState


# Hardcoded RAM lookup for common RDS instance classes (in GB)
RDS_RAM_GB: dict[str, int] = {
    "db.t3.micro": 1,
    "db.t3.small": 2,
    "db.t3.medium": 4,
    "db.t3.large": 8,
    "db.m5.large": 8,
    "db.m5.xlarge": 16,
    "db.m5.2xlarge": 32,
    "db.m5.4xlarge": 64,
    "db.r5.large": 16,
    "db.r5.xlarge": 32,
    "db.r5.2xlarge": 64,
}


def _compute_memory_free_pct(freeable_memory_gb: float, instance_class: str) -> float | None:
    """Compute percentage of free memory using RDS_RAM_GB lookup.

    Args:
        freeable_memory_gb: Freeable memory in GB (already converted from bytes).
        instance_class: RDS instance class (e.g. "db.t3.micro").

    Returns:
        Percentage of total RAM that is free, or None if instance class is unknown.
    """
    if instance_class in RDS_RAM_GB:
        return (freeable_memory_gb / RDS_RAM_GB[instance_class]) * 100
    return None


def _safe_rds_metric_id(db_instance_id: str, metric: str, stat: str) -> str:
    """Convert RDS instance ID to a valid CloudWatch metric query ID.

    CloudWatch metric IDs must match ^[a-z][a-zA-Z0-9_]*$.
    Replaces dashes with underscores and prepends metric/stat label.

    Args:
        db_instance_id: RDS DB instance identifier.
        metric: Short metric name (e.g. "cpu", "mem", "conn").
        stat: Statistic label (e.g. "avg", "max").

    Returns:
        Safe metric query ID string.
    """
    sanitized = db_instance_id.replace("-", "_")
    return f"rds_{metric}_{stat}_{sanitized}"


def collect_rds(state: "VaporState") -> dict:
    """Collect RDS instance data and CloudWatch metrics.

    Paginates describe_db_instances, batches CloudWatch get_metric_data calls
    for CPUUtilization (avg, max), FreeableMemory (avg), and
    DatabaseConnections (max).

    Args:
        state: VaporState containing config with region and window_days.

    Returns:
        Dict with "raw" containing rds data and "errors" list.
        On failure: error dict with error message and empty data list.
    """
    try:
        config: "AuditConfig" = state["config"]
        region = config.region
        window_days = config.window_days

        rds_client = boto3.client("rds", region_name=region)
        cw_client = boto3.client("cloudwatch", region_name=region)

        # Paginate all RDS instances
        paginator = rds_client.get_paginator("describe_db_instances")
        db_instances: list[dict] = []

        for page in paginator.paginate():
            for db in page.get("DBInstances", []):
                # Extract tags safely
                raw_tags = db.get("TagList", [])
                tags = {
                    tag["Key"]: tag["Value"]
                    for tag in raw_tags
                    if "Key" in tag and "Value" in tag
                }

                db_instances.append(
                    {
                        "db_instance_id": db["DBInstanceIdentifier"],
                        "db_instance_class": db.get("DBInstanceClass", "unknown"),
                        "engine": db.get("Engine", "unknown"),
                        "engine_version": db.get("EngineVersion", "unknown"),
                        "status": db.get("DBInstanceStatus", "unknown"),
                        "multi_az": db.get("MultiAZ", False),
                        "publicly_accessible": db.get("PubliclyAccessible", False),
                        "allocated_storage_gb": db.get("AllocatedStorage", 0),
                        "storage_type": db.get("StorageType", "unknown"),
                        "tags": tags,
                    }
                )

        # Build CloudWatch metric queries for all RDS instances
        queries: list[dict] = []
        for db in db_instances:
            db_id = db["db_instance_id"]

            # CPUUtilization - Average
            queries.append(
                {
                    "Id": _safe_rds_metric_id(db_id, "cpu", "avg"),
                    "MetricStat": {
                        "Metric": {
                            "Namespace": "AWS/RDS",
                            "MetricName": "CPUUtilization",
                            "Dimensions": [
                                {"Name": "DBInstanceIdentifier", "Value": db_id}
                            ],
                        },
                        "Period": 3600,
                        "Stat": "Average",
                    },
                    "ReturnData": True,
                }
            )

            # CPUUtilization - Maximum
            queries.append(
                {
                    "Id": _safe_rds_metric_id(db_id, "cpu", "max"),
                    "MetricStat": {
                        "Metric": {
                            "Namespace": "AWS/RDS",
                            "MetricName": "CPUUtilization",
                            "Dimensions": [
                                {"Name": "DBInstanceIdentifier", "Value": db_id}
                            ],
                        },
                        "Period": 3600,
                        "Stat": "Maximum",
                    },
                    "ReturnData": True,
                }
            )

            # FreeableMemory - Average (in bytes from CloudWatch)
            queries.append(
                {
                    "Id": _safe_rds_metric_id(db_id, "mem", "avg"),
                    "MetricStat": {
                        "Metric": {
                            "Namespace": "AWS/RDS",
                            "MetricName": "FreeableMemory",
                            "Dimensions": [
                                {"Name": "DBInstanceIdentifier", "Value": db_id}
                            ],
                        },
                        "Period": 3600,
                        "Stat": "Average",
                    },
                    "ReturnData": True,
                }
            )

            # DatabaseConnections - Maximum
            queries.append(
                {
                    "Id": _safe_rds_metric_id(db_id, "conn", "max"),
                    "MetricStat": {
                        "Metric": {
                            "Namespace": "AWS/RDS",
                            "MetricName": "DatabaseConnections",
                            "Dimensions": [
                                {"Name": "DBInstanceIdentifier", "Value": db_id}
                            ],
                        },
                        "Period": 3600,
                        "Stat": "Maximum",
                    },
                    "ReturnData": True,
                }
            )

        # Batch CloudWatch calls (max 500 queries per call)
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(days=window_days)

        metric_results: dict[str, list[float]] = {}
        batch_size = 500

        for i in range(0, len(queries), batch_size):
            batch = queries[i : i + batch_size]
            if not batch:
                continue

            response = cw_client.get_metric_data(
                MetricDataQueries=batch,
                StartTime=start_time,
                EndTime=end_time,
            )

            for result in response.get("MetricDataResults", []):
                metric_id = result["Id"]
                values = result.get("Values", [])
                metric_results[metric_id] = values

            # Handle NextToken for large metric responses
            while response.get("NextToken"):
                response = cw_client.get_metric_data(
                    MetricDataQueries=batch,
                    StartTime=start_time,
                    EndTime=end_time,
                    NextToken=response["NextToken"],
                )
                for result in response.get("MetricDataResults", []):
                    metric_id = result["Id"]
                    values = result.get("Values", [])
                    metric_results[metric_id] = values

        # Match metric results back to RDS instances
        for db in db_instances:
            db_id = db["db_instance_id"]
            instance_class = db["db_instance_class"]

            cpu_avg_id = _safe_rds_metric_id(db_id, "cpu", "avg")
            cpu_max_id = _safe_rds_metric_id(db_id, "cpu", "max")
            mem_avg_id = _safe_rds_metric_id(db_id, "mem", "avg")
            conn_max_id = _safe_rds_metric_id(db_id, "conn", "max")

            cpu_avg_values = metric_results.get(cpu_avg_id, [])
            cpu_max_values = metric_results.get(cpu_max_id, [])
            mem_avg_values = metric_results.get(mem_avg_id, [])
            conn_max_values = metric_results.get(conn_max_id, [])

            # CPU metrics
            cpu_avg = (
                sum(cpu_avg_values) / len(cpu_avg_values) if cpu_avg_values else None
            )
            cpu_max = max(cpu_max_values) if cpu_max_values else None

            # FreeableMemory: convert from bytes to GB
            if mem_avg_values:
                freeable_memory_bytes = sum(mem_avg_values) / len(mem_avg_values)
                freeable_memory_gb = freeable_memory_bytes / (1024**3)
            else:
                freeable_memory_gb = None

            # DatabaseConnections
            connections_max = max(conn_max_values) if conn_max_values else None

            # Compute memory_free_pct
            if freeable_memory_gb is not None:
                memory_free_pct = _compute_memory_free_pct(
                    freeable_memory_gb, instance_class
                )
            else:
                memory_free_pct = None

            db["cpu"] = {
                "avg": cpu_avg,
                "max": cpu_max,
            }
            db["freeable_memory_gb"] = freeable_memory_gb
            db["memory_free_pct"] = memory_free_pct
            db["connections_max"] = connections_max

        return {
            "raw": {
                "rds": {
                    "data": db_instances,
                    "db_count": len(db_instances),
                }
            },
            "errors": [],
        }

    except Exception as e:
        return {
            "raw": {"rds": {"error": str(e), "data": []}},
            "errors": [f"collect_rds failed: {str(e)}"],
        }
