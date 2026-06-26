"""Cost Explorer collector node for the Vapor pipeline.

Queries AWS Cost Explorer for cost-by-service breakdown over the
configured window_days period, computes total spend, and returns
normalized cost data.

Requirements: 9.1, 9.2, 9.3, 9.4
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import boto3
from botocore.exceptions import ClientError

if TYPE_CHECKING:
    from vapor.graph.state import VaporState


def collect_cost_explorer(state: "VaporState") -> dict:
    """Query Cost Explorer for cost-by-service over window_days.

    Computes total_cost_usd as the sum of all individual service costs
    and returns a per-service breakdown.

    Args:
        state: VaporState containing config with region and window_days.

    Returns:
        Dict with "raw" containing cost_explorer data and "errors" list.
        If Cost Explorer is not enabled or permissions are insufficient,
        returns available=False with an error message.
    """
    try:
        config = state["config"]
        window_days = config.window_days

        # Cost Explorer API is only available in us-east-1, regardless of
        # the configured audit region. All AWS accounts must call this
        # endpoint in us-east-1.
        ce_client = boto3.client("ce", region_name="us-east-1")

        end_date = datetime.now(timezone.utc).date()
        start_date = end_date - timedelta(days=window_days)

        try:
            response = ce_client.get_cost_and_usage(
                TimePeriod={
                    "Start": start_date.strftime("%Y-%m-%d"),
                    "End": end_date.strftime("%Y-%m-%d"),
                },
                Granularity="MONTHLY",
                GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
                Metrics=["UnblendedCost"],
            )
        except ClientError as e:
            # Cost Explorer not enabled or insufficient permissions
            return {
                "raw": {
                    "cost_explorer": {
                        "available": False,
                        "error": "Cost Explorer not enabled or insufficient permissions",
                    }
                },
                "errors": [],
            }

        # Parse per-service costs from response
        services: list[dict] = []
        total_cost_usd = 0.0

        for time_period in response.get("ResultsByTime", []):
            for group in time_period.get("Groups", []):
                service_name = group["Keys"][0]
                cost_amount = float(
                    group["Metrics"]["UnblendedCost"]["Amount"]
                )
                services.append(
                    {"service": service_name, "cost_usd": cost_amount}
                )
                total_cost_usd += cost_amount

        return {
            "raw": {
                "cost_explorer": {
                    "available": True,
                    "services": services,
                    "total_cost_usd": total_cost_usd,
                }
            },
            "errors": [],
        }

    except Exception as e:
        return {
            "raw": {"cost_explorer": {"error": str(e), "data": []}},
            "errors": [f"collect_cost_explorer failed: {str(e)}"],
        }
