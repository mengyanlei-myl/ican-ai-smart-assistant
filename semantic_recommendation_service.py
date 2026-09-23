"""Stage 8 semantic request orchestration without recommendation execution.

This first integration boundary intentionally performs no database access and
does not invoke the Stage 7 rule or recommendation services.
"""

from __future__ import annotations

from typing import Any

from semantic_parser import parse_task_requirements


DISABLED_RULES = [f"R{number:02d}" for number in range(1, 8)]

_REASONS = {
    "ready": "semantic_ready_rule_bridge_pending",
    "needs_clarification": "clarification_required",
    "not_evaluated": "unsupported_or_no_executable_hard_constraints",
}


def recommend_from_text(
    text: str,
    top_n: int = 10,
    allow_manual_review: bool = True,
    weights: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Parse text and return a safely gated, deterministic response.

    The control options are accepted for API compatibility but deliberately
    remain unapplied in D1 because no candidates are queried or ranked.
    Validation of HTTP input belongs to the route boundary.
    """

    del top_n, allow_manual_review, weights
    parsed = parse_task_requirements(text)
    request_status = parsed["request_status"]
    if request_status not in _REASONS:
        raise ValueError(f"unsupported parser request_status: {request_status}")

    return {
        "request_status": request_status,
        "parsed_requirements": parsed,
        "clarification_questions": list(parsed["clarification_questions"]),
        "unsupported_constraints": list(parsed["unsupported_constraints"]),
        "rule_execution": {
            "invoked": False,
            "enabled_rules": [],
            "evaluated_rules": [],
            "disabled_rules": list(DISABLED_RULES),
            "results": [],
        },
        "recommendation": {
            "database_queried": False,
            "items": [],
            "disposition": "none",
            "is_final_recommendation": False,
            "combination_verified": False,
            "reason": _REASONS[request_status],
        },
        "options_applied": False,
    }


__all__ = ["DISABLED_RULES", "recommend_from_text"]
