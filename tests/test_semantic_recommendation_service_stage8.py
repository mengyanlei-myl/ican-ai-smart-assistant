import decision_service
import rules_engine

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


def test_ready_is_gated_without_stage7_or_database(monkeypatch):
    forbid_stage7(monkeypatch)
    result = recommend_from_text("预算10万元，至少续航30分钟")
    assert result["request_status"] == "ready"
    assert result["parsed_requirements"]["hard_constraints"] == {
        "min_endurance_min": 30,
        "max_budget_cny": 100000,
        "budget_scope": "complete_solution",
    }
    assert_safely_gated(result, "semantic_ready_rule_bridge_pending")


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
    assert_safely_gated(result, "unsupported_or_no_executable_hard_constraints")


def test_unsupported_hard_constraint_never_produces_candidates(monkeypatch):
    forbid_stage7(monkeypatch)
    result = recommend_from_text("预算10万元，需要夜间自主避障能力")
    assert result["parsed_requirements"]["hard_constraints"]["max_budget_cny"] == 100000
    assert result["unsupported_constraints"]
    assert_safely_gated(result, "unsupported_or_no_executable_hard_constraints")


def test_all_request_states_have_no_final_or_provisional_result():
    for text in ("预算10万元", "载荷2kg", "优先续航长"):
        result = recommend_from_text(text)
        assert result["recommendation"]["disposition"] == "none"
        assert result["recommendation"]["is_final_recommendation"] is False


def test_all_stage7_rules_are_disabled_for_every_status():
    for text in ("预算10万元", "载荷2kg", "优先续航长"):
        execution = recommend_from_text(text)["rule_execution"]
        assert execution["disabled_rules"] == ["R01", "R02", "R03", "R04", "R05", "R06", "R07"]
        assert execution["results"] == []


def test_same_input_and_options_are_deterministic():
    args = ("预算10万元，至少续航30分钟", 7, False, {"ignored": 1})
    assert recommend_from_text(*args) == recommend_from_text(*args)
