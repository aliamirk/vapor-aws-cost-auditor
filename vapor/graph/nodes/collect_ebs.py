"""EBS collector node for the Vapor pipeline.

Paginates unattached EBS volumes (status=available) and collects
volume metadata including size, type, creation time, and tags.

Requirements: 7.1, 7.2, 7.3
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import boto3

if TYPE_CHECKING:
    from vapor.graph.state import VaporState


def collect_ebs(state: "VaporState") -> dict:
    """Collect unattached EBS volumes (status=available).

    Paginates describe_volumes with a filter for status="available",
    collecting volume metadata for cost analysis.

    Args:
        state: VaporState containing config with region.

    Returns:
        Dict with "raw" containing ebs data and "errors" list.
        On failure: error dict with error message and empty data list.
    """
    try:
        config = state["config"]
        region = config.region

        ec2_client = boto3.client("ec2", region_name=region)

        paginator = ec2_client.get_paginator("describe_volumes")
        volumes: list[dict] = []

        for page in paginator.paginate(
            Filters=[{"Name": "status", "Values": ["available"]}]
        ):
            for volume in page.get("Volumes", []):
                # Extract tags safely
                raw_tags = volume.get("Tags", [])
                tags = {
                    tag["Key"]: tag["Value"]
                    for tag in raw_tags
                    if "Key" in tag and "Value" in tag
                }

                volumes.append(
                    {
                        "volume_id": volume["VolumeId"],
                        "size_gb": volume["Size"],
                        "volume_type": volume.get("VolumeType", "unknown"),
                        "create_time": volume.get("CreateTime"),
                        "availability_zone": volume.get("AvailabilityZone", ""),
                        "tags": tags,
                    }
                )

        return {
            "raw": {
                "ebs": {
                    "data": volumes,
                    "volume_count": len(volumes),
                }
            },
            "errors": [],
        }

    except Exception as e:
        return {
            "raw": {"ebs": {"error": str(e), "data": []}},
            "errors": [f"collect_ebs failed: {str(e)}"],
        }
