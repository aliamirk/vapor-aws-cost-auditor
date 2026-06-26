"""Analyze node — sends normalized findings to GPT-5-mini for severity-tagged analysis.

Handles OpenAI API errors and JSON parsing failures gracefully by producing
a fallback AnalysisResult so the pipeline always completes.
"""

from __future__ import annotations

import json

import openai

from vapor.graph.state import AnalysisResult, VaporState
from vapor.prompts.system import SYSTEM_PROMPT
from vapor.prompts.user import build_user_message


def analyze(state: VaporState) -> dict:
    """Send normalized findings to GPT-5-mini with json_object response format.

    Parse response into AnalysisResult. On failure, produce fallback result.

    Returns:
        {"analysis": AnalysisResult}
    """
    try:
        findings = state["findings"]
        config = state["config"]

        # Filter out healthy findings to reduce payload size for LLM
        actionable_findings = [
            f for f in findings
            if f.get("verdict") not in ("healthy", "informational")
        ]
        # If no actionable findings, still send a subset for context
        findings_to_send = actionable_findings if actionable_findings else findings[:10]

        user_message = build_user_message(findings_to_send, config)

        client = openai.OpenAI()

        response = client.chat.completions.create(
            model="gpt-5-mini",
            max_completion_tokens=16000,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
        )

        content = response.choices[0].message.content

        # Handle None/empty content (model output truncated or refused)
        if not content:
            finish_reason = response.choices[0].finish_reason
            error_msg = f"LLM returned empty response (finish_reason={finish_reason})"
            usage = response.usage
            return {
                "analysis": _build_fallback_analysis(error_msg),
                "llm_usage": {
                    "model": "gpt-5-mini",
                    "input_tokens": usage.prompt_tokens if usage else 0,
                    "output_tokens": usage.completion_tokens if usage else 0,
                    "total_tokens": usage.total_tokens if usage else 0,
                },
            }

        result = json.loads(content)

        # Capture token usage statistics
        usage = response.usage
        llm_usage = {
            "model": "gpt-5-mini",
            "input_tokens": usage.prompt_tokens if usage else 0,
            "output_tokens": usage.completion_tokens if usage else 0,
            "total_tokens": usage.total_tokens if usage else 0,
        }

        # Validate expected keys exist
        analysis: AnalysisResult = {
            "summary": result["summary"],
            "findings": result["findings"],
        }

        return {"analysis": analysis, "llm_usage": llm_usage}

    except (openai.APIError, json.JSONDecodeError, KeyError, TypeError) as e:
        return {
            "analysis": _build_fallback_analysis(str(e)),
            "llm_usage": {
                "model": "gpt-5-mini",
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
            },
        }


def _build_fallback_analysis(error_msg: str) -> AnalysisResult:
    """Construct a minimal AnalysisResult describing the LLM failure.

    Returns an AnalysisResult with zeroed summary counts and a single
    finding explaining that analysis failed.
    """
    return {
        "summary": {
            "totalFindings": 0,
            "criticalCount": 0,
            "highCount": 0,
            "mediumCount": 0,
            "lowCount": 0,
            "estimatedMonthlySavings": "$0",
        },
        "findings": [
            {
                "title": "Analysis Failed",
                "severity": "low",
                "category": "system",
                "resource_id": "N/A",
                "detail": error_msg,
                "estimated_savings": "$0",
                "fix": "Retry the audit or check OpenAI API key",
            }
        ],
    }
