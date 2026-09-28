import copy

import pandas as pd
import pytest

from app import create_app
from import_all import import_all
from rules_engine import RULE_IDS, evaluate_rules


def golden_case(case_id):
    frame = pd.read_excel("data/compatibility/v2/golden_cases_v1.xlsx", sheet_name="标准案例")
    row = frame.loc[frame["案例ID"] == case_id].iloc[0]
    requirements = {
        str(key): value.item() if hasattr(value, "item") else value
        for key, value in row.items() if not pd.isna(value)
    }
    enabled_rules = [rule.strip() for rule in str(row["启用规则"]).split(",") if rule.strip()]
    return row, requirements, enabled_rules


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("stage7") / "api.db"
    import_all(db_path)
    app = create_app({
        "TESTING": True,
        "DATABASE_PATH": str(db_path),
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{db_path.as_posix()}",
    })
    return app.test_client()


def test_catalog_counts_and_pagination_boundaries(client):
    expected = {"drones": 281, "sensors": 460, "computers": 50}
    for endpoint, total in expected.items():
        body = client.get(f"/api/v2/{endpoint}?page=1&page_size=100").get_json()
        assert body["total"] == total
        assert len(body["items"]) == min(total, 100)
        assert body["pages"] == (total + 99) // 100
        empty = client.get(f"/api/v2/{endpoint}?page=999&page_size=100").get_json()
        assert empty["items"] == []
    assert client.get("/api/v2/drones?page=0").status_code == 400
    assert client.get("/api/v2/drones?page_size=101").status_code == 400


def test_search_chinese_english_model_and_standard_id(client):
    searches = [
        ("sensors", "工业相机"),
        ("sensors", "Basler"),
        ("sensors", "boa9344-70cc"),
        ("sensors", "Basler_boa9344_70cc"),
    ]
    for endpoint, query in searches:
        response = client.get(f"/api/v2/{endpoint}", query_string={"q": query, "page_size": 100})
        assert response.status_code == 200
        assert response.get_json()["total"] > 0, query


def test_partial_null_is_visible_and_not_coerced(client):
    response = client.get("/api/v2/sensors", query_string={"q": "Basler_boa9344_70cc"})
    assert response.status_code == 200
    item = response.get_json()["items"][0]
    assert item["device_id"] == "Basler_boa9344_70cc"
    assert item["verification_status"] == "partial"
    assert item["weight"] is None
    assert item["attributes"]["标准化重量(kg)"] is None


def base_combo():
    drone = {
        "最大有效载荷(kg)": 10, "参考价格(CNY)": 100, "载荷最大输出功率(W)": 100,
        "载荷输出电压最小值(V)": 12, "载荷输出电压最大值(V)": 24,
        "安装/挂载接口": "通用安装板", "工作温度最低值(℃)": -20,
        "工作温度最高值(℃)": 50, "防护等级": "IP54",
    }
    sensor = {
        "重量(kg)": 1, "参考价格(CNY)": 50, "功耗(W)": 10,
        "输入电压最小值(V)": 12, "输入电压最大值(V)": 20,
        "数据接口": "USB3", "安装/挂载接口": "通用安装板",
        "工作温度最低值(℃)": -10, "工作温度最高值(℃)": 40,
        "防护等级": "IP54", "驱动或SDK": "SDK", "支持操作系统": "Ubuntu Linux", "ROS支持": "ROS 2",
    }
    computer = {
        "重量(kg)": 1, "参考价格(CNY)": 100, "最大功耗(W)": 20,
        "输入电压最小值(V)": 12, "输入电压最大值(V)": 24,
        "数据接口": "USB3", "安装/挂载接口": "通用安装板",
        "工作温度最低值(℃)": -10, "工作温度最高值(℃)": 40,
        "防护等级": "IP54", "CPU型号": "Arm Cortex-A76",
        "支持操作系统": "Ubuntu Linux", "ROS支持": "ROS 2",
    }
    requirements = {"installation_margin_kg": 1, "budget": 1000, "mission_temp_min_c": 0, "mission_temp_max_c": 35, "required_protection_level": "IP54"}
    return drone, [sensor], computer, requirements


@pytest.mark.parametrize("rule_id", RULE_IDS)
def test_each_rule_pass(rule_id):
    drone, sensors, computer, requirements = base_combo()
    result = evaluate_rules(drone, sensors, computer, requirements, [rule_id])
    assert result["overall_status"] == "pass", result


@pytest.mark.parametrize("rule_id,mutation", [
    ("R01", lambda d, s, c, r: d.update({"最大有效载荷(kg)": 1})),
    ("R02", lambda d, s, c, r: r.update({"budget": 100})),
    ("R03", lambda d, s, c, r: d.update({"载荷最大输出功率(W)": 10})),
    ("R04", lambda d, s, c, r: s[0].update({"输入电压最小值(V)": 30, "输入电压最大值(V)": 40})),
    ("R05", lambda d, s, c, r: s[0].update({"数据接口": "GMSL2"})),
    ("R06", lambda d, s, c, r: r.update({"mission_temp_min_c": -30})),
    ("R07", lambda d, s, c, r: s[0].update({"支持操作系统": "Windows"})),
])
def test_each_rule_fail(rule_id, mutation):
    drone, sensors, computer, requirements = base_combo()
    mutation(drone, sensors, computer, requirements)
    result = evaluate_rules(drone, sensors, computer, requirements, [rule_id])
    assert result["overall_status"] == "fail", result


@pytest.mark.parametrize("rule_id,mutation", [
    ("R01", lambda d, s, c, r: s[0].pop("重量(kg)")),
    ("R02", lambda d, s, c, r: c.pop("参考价格(CNY)")),
    ("R03", lambda d, s, c, r: d.pop("载荷最大输出功率(W)")),
    ("R04", lambda d, s, c, r: c.pop("输入电压最大值(V)")),
    ("R05", lambda d, s, c, r: s[0].pop("数据接口")),
    ("R06", lambda d, s, c, r: s[0].pop("工作温度最低值(℃)")),
    ("R07", lambda d, s, c, r: s[0].pop("驱动或SDK")),
])
def test_each_rule_manual_review_has_missing_fields(rule_id, mutation):
    drone, sensors, computer, requirements = base_combo()
    mutation(drone, sensors, computer, requirements)
    result = evaluate_rules(drone, sensors, computer, requirements, [rule_id])
    assert result["overall_status"] == "manual_review", result
    assert result["missing_fields"]


def test_multi_sensor_weight_and_power_are_summed():
    drone, sensors, computer, requirements = base_combo()
    second = copy.deepcopy(sensors[0])
    second["重量(kg)"] = 2
    second["功耗(W)"] = 15
    result = evaluate_rules(drone, [sensors[0], second], computer, requirements, ["R01", "R03"])
    by_rule = {item["rule_id"]: item for item in result["rule_results"]}
    assert by_rule["R01"]["compared_values"]["total_payload_kg"] == 5
    assert by_rule["R03"]["compared_values"]["total_power_w"] == 45


def test_compatibility_invalid_and_missing_ids(client):
    assert client.post("/api/v2/compatibility/check", json={}).status_code == 400
    response = client.post("/api/v2/compatibility/check", json={
        "drone_id": "missing", "sensor_ids": ["Stereolabs_ZED_2i"],
        "computer_id": "CP-RPI-PI5", "task_requirements": {},
    })
    assert response.status_code == 404


def test_compatibility_api_returns_all_rules_and_multi_sensor_calculations(client):
    response = client.post("/api/v2/compatibility/check", json={
        "drone_id": "UAV-DJI-M400",
        "sensor_ids": ["Stereolabs_ZED_2i", "Livox_Mid360"],
        "computer_id": "CP-UP-UP2PRO7000",
        "task_requirements": {"installation_margin_kg": 0.5},
    })
    assert response.status_code == 200
    body = response.get_json()
    assert [item["rule_id"] for item in body["rule_results"]] == list(RULE_IDS)
    assert body["verification"]["combination_verified"] is False
    r01 = next(item for item in body["rule_results"] if item["rule_id"] == "R01")
    assert len(r01["compared_values"]["sensor_weights_kg"]) == 2
    assert all(key in r01 for key in ("reason", "compared_values", "missing_fields", "evidence_sources"))


@pytest.mark.parametrize("case_id,expected", [("GC01", "pass"), ("GC07", "fail"), ("GC02", "manual_review")])
def test_golden_case_tri_state_through_compatibility_api(client, case_id, expected):
    row, requirements, enabled_rules = golden_case(case_id)
    response = client.post("/api/v2/compatibility/check", json={
        "drone_id": row["预期无人机ID"],
        "sensor_ids": [row["预期传感器ID"]],
        "computer_id": row["预期计算平台ID"],
        "task_requirements": requirements,
        "enabled_rules": enabled_rules,
    })
    assert response.status_code == 200
    body = response.get_json()
    assert body["overall_status"] == expected
    assert [result["rule_id"] for result in body["rule_results"]] == enabled_rules


def test_known_pass_golden_case_is_retrievable_by_recommendations(client):
    row, requirements, enabled_rules = golden_case("GC01")
    requirements.update({
        "enabled_rules": enabled_rules,
        "drone_ids": [row["预期无人机ID"]],
        "sensor_ids": [row["预期传感器ID"]],
        "computer_ids": [row["预期计算平台ID"]],
    })
    response = client.post("/api/v2/recommendations", json={
        "requirements": requirements, "top_n": 10, "allow_manual_review": True,
    })
    assert response.status_code == 200
    body = response.get_json()
    assert body["combinations_checked"] == 1
    assert body["pass_count"] == 1
    assert body["recommendations"][0]["overall_status"] == "pass"
    assert body["recommendations"][0]["drone_id"] == row["预期无人机ID"]
    assert body["recommendations"][0]["sensor_ids"] == [row["预期传感器ID"]]
    assert body["recommendations"][0]["computer_id"] == row["预期计算平台ID"]


@pytest.mark.parametrize("top_n", [5, 10, 20, 50])
def test_dynamic_top_n_and_limit(client, top_n):
    response = client.post("/api/v2/recommendations", json={"requirements": {}, "top_n": top_n, "allow_manual_review": True})
    assert response.status_code == 200
    body = response.get_json()
    assert len(body["recommendations"]) == top_n
    assert body["combinations_checked"] > top_n
    assert body["rejected_count"] + body["pass_count"] + body["manual_review_count"] >= body["combinations_checked"]
    assert all(item["overall_status"] != "fail" for item in body["recommendations"])
    assert all(item["combination_verified"] is False for item in body["recommendations"])
    assert client.post("/api/v2/recommendations", json={"top_n": 51}).status_code == 400


def test_recommendations_are_deterministic_and_not_fixed_mock(client):
    payload = {"requirements": {}, "top_n": 10, "allow_manual_review": True}
    first = client.post("/api/v2/recommendations", json=payload).get_json()
    second = client.post("/api/v2/recommendations", json=payload).get_json()
    projection = lambda body: [(x["drone_id"], tuple(x["sensor_ids"]), x["computer_id"], x["score"]) for x in body["recommendations"]]
    assert projection(first) == projection(second)
    assert len(set(projection(first))) == 10
    assert first["combinations_checked"] == 500
    assert all(item["overall_status"] == "manual_review" for item in first["recommendations"])
    assert all(item["missing_fields"] for item in first["recommendations"])


def test_stats_are_database_backed(client):
    body = client.get("/api/v2/stats").get_json()
    assert body["catalog_counts"] == {"drone": 281, "sensor": 460, "computer": 50}
    assert body["compatibility_records"] == 25
    assert body["field_evidence_records"] == 214
    assert body["verification_status_counts"] == {"verified": 2, "partial": 23}
