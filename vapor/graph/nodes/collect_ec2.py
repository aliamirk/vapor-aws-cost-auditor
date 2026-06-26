"""EC2 collector node for the Vapor pipeline.

Paginates all EC2 instances, batches CloudWatch CPU metrics (avg, max, p95)
in a single get_metric_data call with 3600s period, and returns normalized
instance data with CPU utilization metrics.

Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

import boto3

if TYPE_CHECKING:
    from vapor.config import AuditConfig
    from vapor.graph.state import VaporState


def _safe_metric_id(instance_id: str, stat: str) -> str:
    """Convert instance_id to a valid CloudWatch metric query ID.

    CloudWatch metric IDs must match ^[a-z][a-zA-Z0-9_]*$.
    Transforms e.g. "i-0abc123def" + "avg" → "cpu_avg_0abc123def".

    Strips the 'i-' prefix, replaces any remaining dashes with underscores,
    and prepends the stat label with 'cpu_' prefix.
    """
    stripped = instance_id.removeprefix("i-")
    sanitized = stripped.replace("-", "_")
    return f"cpu_{stat}_{sanitized}"


def _build_metric_queries(instance_ids: list[str], config: "AuditConfig") -> list[dict]:
    """Build MetricDataQueries for CPUUtilization (avg, max, p95) for all instances.

    Each instance gets three queries — one per statistic. The period is fixed
    at 3600 seconds (1 hour). CloudWatch get_metric_data supports a maximum of
    500 queries per call, so callers should batch if needed.

    Args:
        instance_ids: List of EC2 instance IDs (e.g. ["i-0abc123def"]).
        config: AuditConfig with window_days for time range calculation.

    Returns:
        List of MetricDataQuery dicts ready for get_metric_data.
    """
    stat_map = {
        "avg": "Average",
        "max": "Maximum",
        "p95": "p95",
    }

    queries: list[dict] = []

    for instance_id in instance_ids:
        for stat_label, cw_stat in stat_map.items():
            metric_id = _safe_metric_id(instance_id, stat_label)

            if stat_label == "p95":
                # p95 requires ExtendedStatistics-style via MetricStat
                query = {
                    "Id": metric_id,
                    "MetricStat": {
                        "Metric": {
                            "Namespace": "AWS/EC2",
                            "MetricName": "CPUUtilization",
                            "Dimensions": [
                                {"Name": "InstanceId", "Value": instance_id}
                            ],
                        },
                        "Period": 3600,
                        "Stat": "p95",
                    },
                    "ReturnData": True,
                }
            else:
                query = {
                    "Id": metric_id,
                    "MetricStat": {
                        "Metric": {
                            "Namespace": "AWS/EC2",
                            "MetricName": "CPUUtilization",
                            "Dimensions": [
                                {"Name": "InstanceId", "Value": instance_id}
                            ],
                        },
                        "Period": 3600,
                        "Stat": cw_stat,
                    },
                    "ReturnData": True,
                }

            queries.append(query)

    return queries


def collect_ec2(state: "VaporState") -> dict:
    """Collect EC2 instance data and CPU utilization metrics.

    Paginates describe_instances, batches CloudWatch get_metric_data calls
    (respecting the 500-query limit), and matches metric results back to
    instances using safe metric IDs.

    Args:
        state: VaporState containing config with region and window_days.

    Returns:
        Dict with "raw" containing ec2 data and "errors" list.
        On failure: error dict with error message and empty data list.
    """
    try:
        config: "AuditConfig" = state["config"]
        region = config.region
        window_days = config.window_days

        ec2_client = boto3.client("ec2", region_name=region)
        cw_client = boto3.client("cloudwatch", region_name=region)

        # Paginate all EC2 instances
        paginator = ec2_client.get_paginator("describe_instances")
        instances: list[dict] = []

        for page in paginator.paginate():
            for reservation in page.get("Reservations", []):
                for instance in reservation.get("Instances", []):
                    # Extract tags safely
                    raw_tags = instance.get("Tags", [])
                    tags = {
                        tag["Key"]: tag["Value"]
                        for tag in raw_tags
                        if "Key" in tag and "Value" in tag
                    }

                    # Extract attached EBS volume details
                    block_devices = instance.get("BlockDeviceMappings", [])
                    ebs_volumes = []
                    for bd in block_devices:
                        ebs_info = bd.get("Ebs", {})
                        if ebs_info:
                            ebs_volumes.append(
                                {
                                    "device_name": bd.get("DeviceName"),
                                    "volume_id": ebs_info.get("VolumeId"),
                                    "status": ebs_info.get("Status"),
                                    "attach_time": ebs_info.get("AttachTime"),
                                }
                            )

                    instances.append(
                        {
                            "instance_id": instance["InstanceId"],
                            "instance_type": instance.get("InstanceType", "unknown"),
                            "state": instance.get("State", {}).get("Name", "unknown"),
                            "launch_time": instance.get("LaunchTime"),
                            "availability_zone": instance.get("Placement", {}).get(
                                "AvailabilityZone", ""
                            ),
                            "tags": tags,
                            "ebs_volumes": ebs_volumes,
                        }
                    )

        # Build CloudWatch metric queries for all instances
        instance_ids = [inst["instance_id"] for inst in instances]
        all_queries = _build_metric_queries(instance_ids, config)

        # Batch CloudWatch calls (max 500 queries per call)
        end_time = datetime.now(timezone.utc)
        start_time = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        from datetime import timedelta

        start_time = end_time - timedelta(days=window_days)

        metric_results: dict[str, list[float]] = {}
        batch_size = 500

        for i in range(0, len(all_queries), batch_size):
            batch = all_queries[i : i + batch_size]
            if not batch:
                continue

            response = cw_client.get_metric_data(
                MetricDataQueries=batch,
                StartTime=start_time,
                EndTime=end_time,
            )

            # Process paginated metric data results
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

        # Match metric results back to instances
        for inst in instances:
            instance_id = inst["instance_id"]
            avg_id = _safe_metric_id(instance_id, "avg")
            max_id = _safe_metric_id(instance_id, "max")
            p95_id = _safe_metric_id(instance_id, "p95")

            avg_values = metric_results.get(avg_id, [])
            max_values = metric_results.get(max_id, [])
            p95_values = metric_results.get(p95_id, [])

            # Handle missing data: set no_data=true when zero datapoints
            if not avg_values and not max_values and not p95_values:
                inst["cpu"] = {
                    "avg": None,
                    "max": None,
                    "p95": None,
                    "no_data": True,
                }
            else:
                inst["cpu"] = {
                    "avg": sum(avg_values) / len(avg_values) if avg_values else None,
                    "max": max(max_values) if max_values else None,
                    "p95": sum(p95_values) / len(p95_values) if p95_values else None,
                    "no_data": False,
                }

        return {
            "raw": {
                "ec2": {
                    "data": instances,
                    "instance_count": len(instances),
                }
            },
            "errors": [],
        }

    except Exception as e:
        return {
            "raw": {"ec2": {"error": str(e), "data": []}},
            "errors": [f"collect_ec2 failed: {str(e)}"],
        }
