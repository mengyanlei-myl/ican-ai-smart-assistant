import decision_service
import rules_engine
import semantic_recommendation_service as service_module
from config import DB_PATH

from semantic_recommendation_service import DISABLED_RULES, recommend_from_text


def forbid_stage7(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Stage 7 or database service must not be called")

    monkeypatch.setattr(decision_service, "recommend", forbidden)
    monkeypatch.setattr(decision_service, "connect", forbidden)
    monkeypatch.setattr(rules_engine, "evaluate_rules", forbidden)


def assert_safely_gated(result, reason):
    assert result["rule_execution"] == {
        "invoked": False,
        "enabled_rules": [],
        "evaluated_rules": [],
        "disabled_rules": DISABLED_RULES,
        "results": [],
    }
    assert result["recommendation"] == {
        "database_queried": False,
        "items": [],
        "disposition": "none",
        "is_final_recommendation": False,
        "combination_verified": False,
        "reason": reason,
    }
    assert result["options_applied"] is False


def test_ready_invokes_stage7_adapter_after_d2_candidate_filtering():
    result = recommend_from_text("预算10万元，至少续航30分钟", db_path=str(DB_PATH))
    assert result["request_status"] == "ready"
    assert result["parsed_requirements"]["hard_constraints"] == {
        "min_endurance_min": 30,
        "max_budget_cny": 100000,
        "budget_scope": "complete_solution",
    }
    assert result["database_queried"] is True
    assert result["recommendation_disposition"] == "provisional"
    assert result["recommendation"]["items"]
    assert result["options_applied"] is True
    assert result["applied_control_options"] == ["top_n", "allow_manual_review", "weights"]
    assert result["unapplied_control_options"] == []
    assert result["rule_execution"]["invoked"] is True
    assert result["rule_execution"]["enabled_rules"]


def test_needs_clarification_returns_questions_without_execution(monkeypatch):
    forbid_stage7(monkeypatch)
    result = recommend_from_text("载荷2kg")
    assert result["request_status"] == "needs_clarification"
    assert result["clarification_questions"]
    assert_safely_gated(result, "clarification_required")


def test_not_evaluated_preserves_unsupported_constraints(monkeypatch):
    forbid_stage7(monkeypatch)
    result = recommend_from_text("需要夜间自主避障能力")
    assert result["request_status"] == "not_evaluated"
    assert result["unsupported_constraints"]
    assert_safely_gated(result, "unsupported_or_no_executable_hard_constraints")


def test_soft_preferences_only_do_not_produce_candidates(monkeypatch):
    forbid_stage7(monkeypatch)
    result = recommend_from_text("优先续航长")
    assert result["request_status"] == "not_evaluated"
    assert result["parsed_requirements"]["soft_preferences"]
    assert result["options_applied"] is False
    assert result["applied_control_options"] == []
    assert result["unapplied_control_options"] == ["top_n", "allow_manual_review", "weights"]
    assert_safely_gated(result, "unsupported_or_no_executable_hard_constraints")


def test_unsupported_hard_constraint_never_produces_candidates(monkeypatch):
    forbid_stage7(monkeypatch)
    result = recommend_from_text("预算10万元，需要夜间自主避障能力")
    assert result["parsed_requirements"]["hard_constraints"]["max_budget_cny"] == 100000
    assert result["unsupported_constraints"]
    assert_safely_gated(result, "unsupported_or_no_executable_hard_constraints")


def test_incomplete_payload_requires_clarification_without_database(monkeypatch):
    forbid_stage7(monkeypatch)
    result = recommend_from_text("任务净载荷2kg")
    assert result["request_status"] == "needs_clarification"
    assert any("安装余量" in question for question in result["clarification_questions"])
    assert result["database_queried"] is False


def test_supported_and_unsupported_constraints_do_not_query(monkeypatch):
    forbid_stage7(monkeypatch)
    result = recommend_from_text("至少续航30分钟，操作系统要求 Ubuntu")
    assert result["request_status"] == "not_evaluated"
    assert result["unsupported_constraints"]
    assert result["database_queried"] is False


def test_reversed_temperature_range_requires_clarification_without_candidate_query(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("candidate service must not be called")

    monkeypatch.setattr(service_module, "evaluate_trusted_candidates", forbidden)
    result = recommend_from_text("工作温度 40℃ 到 -10℃", db_path=str(DB_PATH))
    assert result["request_status"] == "needs_clarification"
    assert result["clarification_questions"] == [
        "最低工作温度不能高于最高工作温度，请重新确认温度范围。"
    ]
    assert result["database_queried"] is False
    assert result["recommendation_disposition"] == "none"
    assert result["recommendation"]["items"] == []
    assert result["recommendation"]["is_final_recommendation"] is False


def test_ordered_temperature_range_enters_candidate_evaluation():
    result = recommend_from_text("工作温度 -10℃ 到 40℃", db_path=str(DB_PATH))
    assert result["request_status"] == "ready"
    assert result["database_queried"] is True
    assert result["constraint_results"] == [
        {"constraint_id": "stage8_temperature", "status": "evaluated_per_candidate"}
    ]


def test_all_request_states_are_never_final():
    for text in ("预算10万元", "载荷2kg", "优先续航长"):
        result = recommend_from_text(text, db_path=str(DB_PATH))
        assert result["recommendation"]["is_final_recommendation"] is False
        assert result["combination_verified"] is False


def test_stage7_rules_remain_disabled_for_gated_statuses():
    for text in ("载荷2kg", "优先续航长"):
        execution = recommend_from_text(text, db_path=str(DB_PATH))["rule_execution"]
        assert execution["disabled_rules"] == ["R01", "R02", "R03", "R04", "R05", "R06", "R07"]
        assert execution["results"] == []


def test_same_input_and_options_are_deterministic():
    args = ("预算10万元，至少续航30分钟", 7, True, {"task_constraint_fit": 30})
    assert recommend_from_text(*args, db_path=str(DB_PATH)) == recommend_from_text(*args, db_path=str(DB_PATH))
