"""Stage 8 semantic parsing, candidate gating, and Stage 7 rule orchestration."""

from __future__ import annotations

from typing import Any

from decision_service import evaluate_semantic_candidates
from semantic_parser import parse_task_requirements
from semantic_candidate_service import evaluate_trusted_candidates


DISABLED_RULES = [f"R{number:02d}" for number in range(1, 8)]

_REASONS = {
    "ready": "semantic_ready_rule_bridge_pending",
    "needs_clarification": "clarification_required",
    "not_evaluated": "unsupported_or_no_executable_hard_constraints",
}

_SUPPORTED_HARD_FIELDS = {
    "task_payload_requirement_kg", "installation_margin_kg", "max_total_mounted_weight_kg",
    "min_endurance_min", "max_budget_cny", "budget_scope",
    "temperature_min_c", "temperature_max_c", "protection_rating",
    "protection_scope", "specified_protected_device_types",
}


def recommend_from_text(
    text: str,
    top_n: int = 10,
    allow_manual_review: bool = True,
    weights: dict[str, Any] | None = None,
    *,
    confirmed_requirements: dict[str, Any] | None = None,
    db_path: str | None = None,
) -> dict[str, Any]:
    """Parse text once and return a safely gated, deterministic response."""

    parsed = parse_task_requirements(text)
    request_status = parsed["request_status"]
    if request_status not in _REASONS:
        raise ValueError(f"unsupported parser request_status: {request_status}")

    clarification_questions = list(parsed["clarification_questions"])
    unsupported_constraints = list(parsed["unsupported_constraints"])
    hard = parsed["hard_constraints"]
    unknown_hard_fields = sorted(set(hard) - _SUPPORTED_HARD_FIELDS)
    for field in unknown_hard_fields:
        unsupported_constraints.append({
            "field": field,
            "original_text": parsed["field_evidence"].get(field, [{}])[0].get("text", ""),
            "reason": "D2 尚未支持该硬约束。",
            "participated_in_validation": False,
            "is_hard_constraint": True,
        })

    payload_fields = {"task_payload_requirement_kg", "installation_margin_kg", "max_total_mounted_weight_kg"}
    if set(hard) & payload_fields:
        if "task_payload_requirement_kg" not in hard:
            clarification_questions.append("请明确任务净载荷；如无额外任务净载荷，请明确填写 0 kg。")
        if "installation_margin_kg" not in hard:
            clarification_questions.append("请补充安装余量，不能默认按 0 kg 计算。")

    temperature_min = hard.get("temperature_min_c")
    temperature_max = hard.get("temperature_max_c")
    if temperature_min is not None and temperature_max is not None and temperature_min > temperature_max:
        clarification_questions.append("最低工作温度不能高于最高工作温度，请重新确认温度范围。")

    if clarification_questions:
        request_status = "needs_clarification"
    elif unsupported_constraints:
        request_status = "not_evaluated"

    executable_fields = set(hard) & {
        "task_payload_requirement_kg", "installation_margin_kg", "max_total_mounted_weight_kg",
        "min_endurance_min", "max_budget_cny", "temperature_min_c", "temperature_max_c", "protection_rating",
    }
    candidate_result = None
    if request_status == "ready" and executable_fields:
        if db_path is None:
            raise ValueError("db_path is required for executable D2 constraints")
        candidate_result = evaluate_trusted_candidates(
            db_path, hard, top_n=None, allow_manual_review=allow_manual_review
        )
    elif request_status == "ready":
        request_status = "not_evaluated"

    parsed_requirements = dict(parsed)
    parsed_requirements["request_status"] = request_status
    parsed_requirements["needs_clarification"] = request_status == "needs_clarification"
    parsed_requirements["clarification_questions"] = clarification_questions
    parsed_requirements["unsupported_constraints"] = unsupported_constraints

    database_queried = candidate_result is not None
    stage7_result = None
    if candidate_result is not None:
        stage7_result = evaluate_semantic_candidates(
            db_path,
            candidate_result["items"],
            hard,
            top_n=top_n,
            allow_manual_review=allow_manual_review,
            custom_weights=weights,
        )
    items = stage7_result["items"] if stage7_result else []
    reason = _REASONS[request_status]
    if database_queried:
        reason = "trusted_candidates_provisional" if items else "no_candidates_after_d2_constraints"

    return {
        "confirmed_requirements": dict(confirmed_requirements or {}),
        "request_status": request_status,
        "parsed_requirements": parsed_requirements,
        "clarification_questions": clarification_questions,
        "unsupported_constraints": unsupported_constraints,
        "rule_execution": {
            "invoked": stage7_result is not None,
            "enabled_rules": stage7_result["enabled_rules"] if stage7_result else [],
            "evaluated_rules": stage7_result["enabled_rules"] if stage7_result else [],
            "disabled_rules": [
                rule_id for rule_id in DISABLED_RULES
                if not stage7_result or rule_id not in stage7_result["enabled_rules"]
            ],
            "results": [
                {"rule_id": rule_id, "status": "evaluated_per_candidate"}
                for rule_id in (stage7_result["enabled_rules"] if stage7_result else [])
            ],
        },
        "recommendation": {
            "database_queried": database_queried,
            "items": items,
            "disposition": "provisional" if items else "none",
            "is_final_recommendation": False,
            "combination_verified": False,
            "reason": reason,
        },
        "constraint_results": [
            {"constraint_id": constraint_id, "status": "evaluated_per_candidate"}
            for constraint_id in (candidate_result["executed_constraints"] if candidate_result else [])
        ],
        "missing_device_fields": candidate_result["missing_device_fields"] if candidate_result else [],
        "insufficient_evidence": candidate_result["insufficient_evidence"] if candidate_result else [],
        "exposure_assessment": candidate_result["exposure_assessment"] if candidate_result else {
            "drone": "unknown", "sensors": ["unknown"], "computer": "unknown"
        },
        "database_queried": database_queried,
        "candidate_pool_scope": candidate_result["candidate_pool_scope"] if candidate_result else None,
        "recommendation_disposition": "provisional" if items else "none",
        "is_final": False,
        "combination_verified": False,
        "options_applied": database_queried,
        "applied_control_options": ["top_n", "allow_manual_review", "weights"] if database_queried else [],
        "unapplied_control_options": [] if database_queried else ["top_n", "allow_manual_review", "weights"],
    }


__all__ = ["DISABLED_RULES", "recommend_from_text"]
