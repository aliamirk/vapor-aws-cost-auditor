"""EIP collector node for the Vapor pipeline.

Retrieves all Elastic IP addresses, filters for unassociated EIPs
(those missing AssociationId or InstanceId), and collects allocation_id,
public_ip, and tags for each.

Requirements: 8.1, 8.2, 8.3, 8.4
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import boto3

if TYPE_CHECKING:
    from vapor.graph.state import VaporState


def collect_eip(state: "VaporState") -> dict:
    """Collect unassociated Elastic IP addresses.

    Calls describe_addresses() to retrieve all EIPs, then filters for
    addresses where AssociationId is absent or InstanceId is absent.

    Args:
        state: VaporState containing config with region.

    Returns:
        Dict with "raw" containing eip data and "errors" list.
        On failure: error dict with error message and empty data list.
    """
    try:
        config = state["config"]
        ec2_client = boto3.client("ec2", region_name=config.region)

        # Retrieve all Elastic IP addresses
        response = ec2_client.describe_addresses()
        all_addresses = response.get("Addresses", [])

        # Filter for unassociated: missing AssociationId or missing InstanceId
        unassociated: list[dict] = []
        for address in all_addresses:
            if "AssociationId" not in address or "InstanceId" not in address:
                raw_tags = address.get("Tags", [])
                tags = {
                    tag["Key"]: tag["Value"]
                    for tag in raw_tags
                    if "Key" in tag and "Value" in tag
                }

                unassociated.append(
                    {
                        "allocation_id": address.get("AllocationId"),
                        "public_ip": address.get("PublicIp"),
                        "tags": tags,
                    }
                )

        return {
            "raw": {
                "eip": {
                    "data": unassociated,
                    "eip_count": len(unassociated),
                }
            },
            "errors": [],
        }

    except Exception as e:
        return {
            "raw": {"eip": {"error": str(e), "data": []}},
            "errors": [f"collect_eip failed: {str(e)}"],
        }
