import decision_service

from config import DB_PATH
from semantic_recommendation_service import recommend_from_text


def test_d3_returns_ranked_three_device_combinations_with_all_rule_states():
    result = recommend_from_text(
        "至少续航30分钟", top_n=3, allow_manual_review=True, db_path=str(DB_PATH)
    )

    assert result["request_status"] == "ready"
    assert result["rule_execution"]["invoked"] is True
    assert 0 < len(result["recommendation"]["items"]) <= 3
    for item in result["recommendation"]["items"]:
        assert item["drone_id"]
        assert item["sensor_ids"]
        assert item["computer_id"]
        assert isinstance(item["score"], float)
        assert [rule["rule_id"] for rule in item["rule_results"]] == [
            "R01", "R02", "R03", "R04", "R05", "R06", "R07"
        ]
        assert item["missing_fields"] == sorted(item["missing_fields"])
        assert item["reasons"]
        assert item["combination_verified"] is False
        assert item["recommendation_disposition"] == "provisional"
        assert item["is_final"] is False


def test_d3_calls_existing_rule_engine_through_decision_service(monkeypatch):
    original = decision_service.evaluate_rules
    calls = []

    def tracked(*args, **kwargs):
        calls.append(kwargs.get("enabled_rules", args[4] if len(args) > 4 else None))
        return original(*args, **kwargs)

    monkeypatch.setattr(decision_service, "evaluate_rules", tracked)
    result = recommend_from_text(
        "至少续航30分钟", top_n=2, allow_manual_review=True, db_path=str(DB_PATH)
    )

    assert result["recommendation"]["items"]
    assert calls
    assert all(call == ["R03", "R04"] for call in calls)


def test_d3_applies_top_n_manual_review_and_weights():
    weighted = recommend_from_text(
        "至少续航30分钟",
        top_n=2,
        allow_manual_review=True,
        weights={"evidence_trust": 50, "task_constraint_fit": 5},
        db_path=str(DB_PATH),
    )
    strict = recommend_from_text(
        "至少续航30分钟", top_n=2, allow_manual_review=False, db_path=str(DB_PATH)
    )

    assert len(weighted["recommendation"]["items"]) <= 2
    assert weighted["applied_control_options"] == ["top_n", "allow_manual_review", "weights"]
    assert weighted["unapplied_control_options"] == []
    assert all(
        item["score_breakdown"]["evidence_trust"]["weight"] == 50.0
        for item in weighted["recommendation"]["items"]
    )
    assert len(strict["recommendation"]["items"]) <= len(weighted["recommendation"]["items"])


def test_d3_bridges_d2_constraints_without_claiming_final_verification():
    result = recommend_from_text(
        "任务净载荷0kg，安装余量0.1kg，至少续航30分钟",
        top_n=5,
        allow_manual_review=True,
        db_path=str(DB_PATH),
    )

    assert result["recommendation_disposition"] in {"provisional", "none"}
    assert result["is_final"] is False
    assert result["combination_verified"] is False
    for item in result["recommendation"]["items"]:
        by_rule = {rule["rule_id"]: rule for rule in item["rule_results"]}
        assert by_rule["R01"]["status"] in {"pass", "manual_review"}
        assert by_rule["R05"]["status"] == "not_evaluated"
        assert by_rule["R07"]["status"] == "not_evaluated"


def test_d3_gated_requests_do_not_invoke_decision_adapter(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("decision adapter must not be called")

    monkeypatch.setattr("semantic_recommendation_service.evaluate_semantic_candidates", forbidden)
    ambiguous = recommend_from_text("载荷2kg", db_path=str(DB_PATH))
    unsupported = recommend_from_text("需要夜间自主避障能力", db_path=str(DB_PATH))

    assert ambiguous["request_status"] == "needs_clarification"
    assert unsupported["request_status"] == "not_evaluated"
    assert ambiguous["recommendation"]["items"] == []
    assert unsupported["recommendation"]["items"] == []
