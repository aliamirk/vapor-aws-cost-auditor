"""S3 collector node for the Vapor pipeline.

Lists all S3 buckets and checks each for lifecycle configuration.
Handles the NoSuchLifecycleConfiguration error code gracefully —
it is not a permissions error, it simply means no lifecycle policy exists.

Requirements: 5.1, 5.2, 5.3, 5.4, 5.5
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import boto3
from botocore.exceptions import ClientError

if TYPE_CHECKING:
    from vapor.graph.state import VaporState


def collect_s3(state: "VaporState") -> dict:
    """Collect S3 bucket data and lifecycle policy status.

    Lists all buckets in the account and checks each for a lifecycle
    configuration. NoSuchLifecycleConfiguration is NOT a permissions
    error — it is caught separately and sets has_lifecycle_policy=False.
    Other ClientErrors are recorded per-bucket but do not stop processing.

    Args:
        state: VaporState containing config with region.

    Returns:
        Dict with "raw" containing s3 data and "errors" list.
        On failure: error dict with error message and empty data list.
    """
    try:
        config = state["config"]
        s3_client = boto3.client("s3", region_name=config.region)

        response = s3_client.list_buckets()
        buckets_raw = response.get("Buckets", [])

        buckets: list[dict] = []
        per_bucket_errors: list[str] = []

        for bucket in buckets_raw:
            bucket_name = bucket["Name"]
            creation_date = bucket.get("CreationDate")
            has_lifecycle_policy = False

            try:
                s3_client.get_bucket_lifecycle_configuration(Bucket=bucket_name)
                has_lifecycle_policy = True
            except ClientError as e:
                error_code = e.response.get("Error", {}).get("Code", "")
                if error_code == "NoSuchLifecycleConfiguration":
                    # Not an error — bucket simply has no lifecycle policy
                    has_lifecycle_policy = False
                else:
                    # Genuine error for this bucket — record and continue
                    per_bucket_errors.append(
                        f"S3 bucket '{bucket_name}': {str(e)}"
                    )
                    # Still add bucket with unknown lifecycle status
                    buckets.append(
                        {
                            "bucket_name": bucket_name,
                            "creation_date": creation_date,
                            "has_lifecycle_policy": None,
                        }
                    )
                    continue

            buckets.append(
                {
                    "bucket_name": bucket_name,
                    "creation_date": creation_date,
                    "has_lifecycle_policy": has_lifecycle_policy,
                }
            )

        return {
            "raw": {
                "s3": {
                    "data": buckets,
                    "bucket_count": len(buckets),
                }
            },
            "errors": per_bucket_errors,
        }

    except Exception as e:
        return {
            "raw": {"s3": {"error": str(e), "data": []}},
            "errors": [f"collect_s3 failed: {str(e)}"],
        }
