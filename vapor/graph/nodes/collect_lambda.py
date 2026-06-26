"""Lambda collector node for the Vapor pipeline.

Paginates all Lambda functions and collects configuration metadata
including function name, runtime, memory size, timeout, last modified,
and code size.

Requirements: 6.1, 6.2, 6.3
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import boto3

if TYPE_CHECKING:
    from vapor.graph.state import VaporState


def collect_lambda(state: "VaporState") -> dict:
    """Paginate all Lambda functions, collect configuration metadata.

    Uses the list_functions paginator to iterate over all Lambda functions
    in the configured region, extracting key configuration fields for
    downstream cost and configuration analysis.

    Args:
        state: VaporState containing config with region.

    Returns:
        Dict with "raw" containing lambda_funcs data and "errors" list.
        On failure: error dict with error message and empty data list.
    """
    try:
        config = state["config"]
        region = config.region

        client = boto3.client("lambda", region_name=region)
        paginator = client.get_paginator("list_functions")

        functions: list[dict] = []

        for page in paginator.paginate():
            for func in page.get("Functions", []):
                functions.append(
                    {
                        "function_name": func.get("FunctionName", ""),
                        "runtime": func.get("Runtime", ""),
                        "memory_size": func.get("MemorySize", 128),
                        "timeout": func.get("Timeout", 3),
                        "last_modified": func.get("LastModified", ""),
                        "code_size_bytes": func.get("CodeSize", 0),
                    }
                )

        return {
            "raw": {
                "lambda_funcs": {
                    "data": functions,
                    "function_count": len(functions),
                }
            },
            "errors": [],
        }

    except Exception as e:
        return {
            "raw": {"lambda_funcs": {"error": str(e), "data": []}},
            "errors": [f"collect_lambda failed: {str(e)}"],
        }
