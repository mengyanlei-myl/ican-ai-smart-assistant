from pathlib import Path

from app import create_app


ROOT = Path(__file__).resolve().parents[1]


def page(name):
    return (ROOT / name).read_text(encoding="utf-8")


def test_task_page_calls_semantic_endpoint_with_top_three():
    html = page("task_input.html")
    assert "/api/v2/recommendations/semantic" in html
    assert "top_n: 3" in html
    assert "semanticResponse" in html
    assert "confirmed_requirements: requirements" in html


def test_confirmation_and_candidate_pages_use_semantic_response():
    confirmation = page("requirement_confirmation.html")
    candidates = page("candidate_devices.html")
    assert "request_status" in confirmation
    assert "clarification_questions" in confirmation
    assert "missing_device_fields" in confirmation
    assert "semanticResponse" in candidates
    assert "暂定推荐/待人工复核" in candidates
    assert confirmation.count("function goToCandidates()") == 1
    assert "localStorage.getItem('requirements')" in candidates
    for field in ("budget", "minFlightTime", "maxPayload", "requiredFunctions", "environment", "priority"):
        assert field in candidates
    assert "deviceLabel(combo.drone_name, combo.drone_id)" in candidates
    assert "combo.rule_results" in candidates


def test_initial_solution_displays_required_d3_fields_and_all_rules():
    html = page("initial_solution.html")
    for field in (
        "drone_id", "sensor_ids", "computer_id", "score", "rule_results",
        "missing_fields", "combination_verified", "recommendation_disposition",
    ):
        assert field in html
    assert "slice(0, 3)" in html
    assert "暂定推荐/待人工复核" in html
    assert "最终推荐" in html
    assert "deviceLabel(combo.drone_name, combo.drone_id)" in html


def test_semantic_request_preserves_confirmed_requirements_and_device_names():
    client = create_app({"TESTING": True}).test_client()
    confirmed = {
        "taskDesc": "至少续航30分钟",
        "budget": "50000",
        "minFlightTime": "30",
        "maxPayload": "0",
        "requiredFunctions": [],
        "environment": "通用",
        "priority": "均衡",
    }
    response = client.post("/api/v2/recommendations/semantic", json={
        "text": confirmed["taskDesc"],
        "top_n": 3,
        "allow_manual_review": True,
        "weights": {},
        "confirmed_requirements": confirmed,
    })
    assert response.status_code == 200
    body = response.get_json()
    assert body["confirmed_requirements"] == confirmed
    for item in body["recommendation"]["items"]:
        assert {"drone_name", "sensor_names", "computer_name"} <= item.keys()


def test_semantic_api_frontend_smoke_returns_at_most_three_combinations():
    client = create_app({"TESTING": True}).test_client()
    response = client.post("/api/v2/recommendations/semantic", json={
        "text": "至少续航30分钟",
        "top_n": 3,
        "allow_manual_review": True,
        "weights": {},
    })
    assert response.status_code == 200
    body = response.get_json()
    assert body["request_status"] == "ready"
    assert len(body["recommendation"]["items"]) <= 3
    assert all(
        item["recommendation_disposition"] == "provisional"
        for item in body["recommendation"]["items"]
    )
