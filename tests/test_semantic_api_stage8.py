import pytest

import app as app_module
import decision_service
import rules_engine
from app import create_app


@pytest.fixture()
def client(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("legacy recommendation route must not be called")

    monkeypatch.setattr(decision_service, "recommend", forbidden)
    monkeypatch.setattr(app_module, "recommend", forbidden)
    application = create_app({"TESTING": True})
    return application.test_client()


def test_normal_chinese_request_returns_200_and_safe_response(client):
    response = client.post("/api/v2/recommendations/semantic", json={
        "text": "预算10万元，至少续航30分钟",
        "top_n": 5,
        "allow_manual_review": False,
        "weights": {"task_constraint_fit": 30},
    })
    assert response.status_code == 200
    body = response.get_json()
    assert body["request_status"] == "ready"
    assert body["rule_execution"]["invoked"] is True
    assert body["recommendation"]["database_queried"] is True
    assert body["recommendation"]["items"] == []  # allow_manual_review=false excludes incomplete budget candidates
    assert body["recommendation"]["reason"] == "no_candidates_after_d2_constraints"
    assert body["candidate_pool_scope"]["trusted_device_records"] == 25
    assert body["candidate_pool_scope"]["full_catalog_used"] is False
    assert body["options_applied"] is True
    assert body["applied_control_options"] == ["top_n", "allow_manual_review", "weights"]
    assert body["unapplied_control_options"] == []


@pytest.mark.parametrize("payload,error", [
    ({}, "text 为必填字段"),
    ({"text": 123}, "text 必须是字符串"),
])
def test_missing_or_non_string_text_returns_400(client, payload, error):
    response = client.post("/api/v2/recommendations/semantic", json=payload)
    assert response.status_code == 400
    assert response.get_json() == {"status": "error", "error": error}


@pytest.mark.parametrize("payload", [["not", "an", "object"], "text", 1, True])
def test_non_object_json_returns_400(client, payload):
    response = client.post("/api/v2/recommendations/semantic", json=payload)
    assert response.status_code == 400
    assert response.get_json()["error"] == "请求体必须是 JSON 对象"


@pytest.mark.parametrize("text", ["", "   "])
def test_blank_text_is_parsed_with_http_200(client, text):
    response = client.post("/api/v2/recommendations/semantic", json={"text": text})
    assert response.status_code == 200
    body = response.get_json()
    assert body["request_status"] == "not_evaluated"
    assert body["recommendation"]["reason"] == "unsupported_or_no_executable_hard_constraints"
    assert body["recommendation"]["items"] == []


@pytest.mark.parametrize("field,value", [
    ("top_n", 0),
    ("top_n", 51),
    ("top_n", True),
    ("top_n", "10"),
    ("allow_manual_review", 1),
    ("allow_manual_review", "true"),
    ("weights", []),
    ("weights", "default"),
])
def test_invalid_reserved_options_return_400(client, field, value):
    response = client.post("/api/v2/recommendations/semantic", json={"text": "预算10万元", field: value})
    assert response.status_code == 400
    assert response.get_json()["status"] == "error"


@pytest.mark.parametrize("extra", [
    {"requirements": {"budget": 100000}},
    {"task_requirements": {"budget": 100000}},
    {"budget": 100000},
    {"unknown_constraint": True},
])
def test_structured_override_or_unknown_field_returns_400(client, extra):
    response = client.post("/api/v2/recommendations/semantic", json={"text": "预算10万元", **extra})
    assert response.status_code == 400
    assert "不允许的请求字段" in response.get_json()["error"]


def test_clarification_and_unsupported_statuses_are_not_pass(client):
    ambiguous = client.post("/api/v2/recommendations/semantic", json={"text": "载荷2kg"}).get_json()
    unsupported = client.post("/api/v2/recommendations/semantic", json={"text": "需要夜间自主避障能力"}).get_json()
    assert ambiguous["request_status"] == "needs_clarification"
    assert ambiguous["clarification_questions"]
    assert ambiguous["recommendation"]["disposition"] == "none"
    assert unsupported["request_status"] == "not_evaluated"
    assert unsupported["unsupported_constraints"]
    assert unsupported["rule_execution"]["results"] == []


def test_supported_constraint_returns_only_provisional_candidates(client):
    body = client.post("/api/v2/recommendations/semantic", json={
        "text": "至少续航30分钟", "top_n": 5, "allow_manual_review": True,
    }).get_json()
    assert body["request_status"] == "ready"
    assert body["database_queried"] is True
    assert body["recommendation_disposition"] == "provisional"
    assert body["is_final"] is False
    assert body["combination_verified"] is False
    assert len(body["recommendation"]["items"]) <= 5


def test_supported_plus_r07_constraint_does_not_query(client):
    body = client.post("/api/v2/recommendations/semantic", json={
        "text": "至少续航30分钟，操作系统要求 Ubuntu"
    }).get_json()
    assert body["request_status"] == "not_evaluated"
    assert body["database_queried"] is False
    assert body["recommendation"]["items"] == []


def test_reversed_temperature_range_api_requires_clarification(client):
    response = client.post("/api/v2/recommendations/semantic", json={
        "text": "工作温度 40℃ 到 -10℃"
    })
    assert response.status_code == 200
    body = response.get_json()
    assert body["request_status"] == "needs_clarification"
    assert body["database_queried"] is False
    assert body["recommendation_disposition"] == "none"
    assert body["recommendation"]["items"] == []
    assert body["recommendation"]["is_final_recommendation"] is False
    assert body["clarification_questions"] == [
        "最低工作温度不能高于最高工作温度，请重新确认温度范围。"
    ]


def test_ordered_temperature_range_api_enters_candidate_evaluation(client):
    response = client.post("/api/v2/recommendations/semantic", json={
        "text": "工作温度 -10℃ 到 40℃"
    })
    assert response.status_code == 200
    body = response.get_json()
    assert body["request_status"] == "ready"
    assert body["database_queried"] is True


def test_existing_recommendations_route_is_unchanged():
    application = create_app({"TESTING": True})
    client = application.test_client()
    response = client.post("/api/v2/recommendations", json={"top_n": 51})
    assert response.status_code == 400
    assert response.get_json() == {"status": "error", "error": "top_n 必须是 1～50 的整数"}
