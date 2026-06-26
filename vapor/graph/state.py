"""Vapor pipeline state definitions.

Defines the shared state TypedDict used by all LangGraph nodes,
along with reducer functions for safe parallel state merging.
"""

from __future__ import annotations

from typing import Annotated, TypedDict

from vapor.config import AuditConfig


def merge_dicts(a: dict, b: dict) -> dict:
    """Reducer: shallow merge for parallel collector outputs."""
    return {**a, **b}


def merge_lists(a: list, b: list) -> list:
    """Reducer: concatenation for error lists."""
    return a + b


class Finding(TypedDict):
    """A normalized finding representing a single resource with its verdict."""

    resource_id: str
    resource_type: str  # EC2 | RDS | S3 | Lambda | EBS | EIP | CostExplorer
    region: str
    issue: str  # machine-readable descriptor
    verdict: str  # underutilized | healthy | overutilized | no_data | gap | ...
    estimated_monthly_cost_usd: float | None
    data: dict
    tags: dict


class AnalysisResult(TypedDict):
    """LLM analysis output with summary counts and severity-tagged findings."""

    summary: dict
    findings: list[dict]


class LLMUsage(TypedDict):
    """Token usage statistics from the LLM call."""

    model: str
    input_tokens: int
    output_tokens: int
    total_tokens: int


class VaporState(TypedDict):
    """Shared state for the Vapor LangGraph pipeline.

    Uses Annotated reducers so parallel collector nodes can safely
    merge their outputs into the raw and errors fields.
    """

    config: AuditConfig
    raw: Annotated[dict, merge_dicts]
    errors: Annotated[list, merge_lists]
    findings: list[Finding]
    analysis: AnalysisResult
    llm_usage: LLMUsage
    report: str
