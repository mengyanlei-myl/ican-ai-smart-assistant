import hashlib
import json
from pathlib import Path

import pytest

from config import DB_PATH
from semantic_candidate_service import (
    _budget_result,
    _protection_result,
    _temperature_result,
    evaluate_trusted_candidates,
)
from semantic_parser import parse_task_requirements


def hard(text):
    return parse_task_requirements(text)["hard_constraints"]


def test_trusted_pool_is_exactly_the_25_v2_records():
    result = evaluate_trusted_candidates(
        DB_PATH, hard("至少续航30分钟"), top_n=3, allow_manual_review=True
    )
    assert result["candidate_pool_scope"] == {
        "source": "v2_compatibility",
        "trusted_device_records": 25,
        "counts": {"drone": 10, "sensor": 10, "computer": 5},
        "full_catalog_used": False,
    }
    assert result["combinations_checked"] == 500


def test_payload_formula_keeps_all_weight_components_separate():
    result = evaluate_trusted_candidates(
        DB_PATH,
        hard("任务净载荷 1kg，安装余量 0.5kg，整套不超过 3kg"),
        top_n=50,
        allow_manual_review=True,
    )
    payload_results = [
        constraint
        for item in result["items"]
        for constraint in item["constraint_results"]
        if constraint["constraint_id"] == "stage8_payload"
        and constraint["status"] == "satisfied"
    ]
    assert payload_results
    values = payload_results[0]["compared_values"]
    assert values["total_mounted_weight_kg"] == (
        values["task_payload_requirement_kg"]
        + values["sensor_total_weight_kg"]
        + values["computer_weight_kg"]
        + values["installation_margin_kg"]
    )


def test_missing_candidate_fields_are_insufficient_not_satisfied():
    result = evaluate_trusted_candidates(
        DB_PATH, hard("任务净载荷 1kg，安装余量 0.5kg"),
        top_n=500, allow_manual_review=True,
    )
    insufficient = [
        constraint
        for item in result["items"]
        for constraint in item["constraint_results"]
        if constraint["status"] == "insufficient_data"
    ]
    assert insufficient
    assert any(constraint["missing_device_fields"] for constraint in insufficient)


def test_allow_manual_review_controls_insufficient_candidates():
    constraints = hard("预算10万元")
    allowed = evaluate_trusted_candidates(DB_PATH, constraints, top_n=10, allow_manual_review=True)
    excluded = evaluate_trusted_candidates(DB_PATH, constraints, top_n=10, allow_manual_review=False)
    assert allowed["items"]
    assert all(
        any(result["status"] == "insufficient_data" for result in item["constraint_results"])
        for item in allowed["items"]
    )
    assert excluded["items"] == []


def test_temperature_and_ip_are_independent():
    result = evaluate_trusted_candidates(
        DB_PATH, hard("工作温度 -10℃ 到 40℃，全部设备 IP54"),
        top_n=20, allow_manual_review=True,
    )
    assert result["executed_constraints"] == ["stage8_temperature", "stage8_protection"]
    for item in result["items"]:
        assert [entry["constraint_id"] for entry in item["constraint_results"]] == [
            "stage8_temperature", "stage8_protection"
        ]


def test_default_exposed_scope_is_unknown_and_insufficient():
    result = evaluate_trusted_candidates(
        DB_PATH, hard("需要 IP67"), top_n=2, allow_manual_review=True
    )
    assert result["items"]
    item = result["items"][0]
    assert item["exposure_assessment"] == {
        "drone": "unknown", "sensors": ["unknown"], "computer": "unknown"
    }
    assert item["constraint_results"][0]["status"] == "insufficient_data"


def test_no_candidate_is_final_or_combination_verified():
    result = evaluate_trusted_candidates(
        DB_PATH, hard("至少续航30分钟"), top_n=10, allow_manual_review=True
    )
    assert all(item["recommendation_disposition"] == "provisional" for item in result["items"])
    assert all(item["is_final"] is False for item in result["items"])
    assert all(item["combination_verified"] is False for item in result["items"])


def test_candidate_output_is_deterministic():
    constraints = hard("至少续航30分钟")
    first = evaluate_trusted_candidates(DB_PATH, constraints, top_n=10, allow_manual_review=True)
    second = evaluate_trusted_candidates(DB_PATH, constraints, top_n=10, allow_manual_review=True)
    assert first == second


def test_database_is_opened_read_only_and_unchanged():
    database_path = Path(DB_PATH)
    before = hashlib.sha256(database_path.read_bytes()).hexdigest()
    evaluate_trusted_candidates(DB_PATH, hard("至少续航30分钟"), top_n=3, allow_manual_review=True)
    after = hashlib.sha256(database_path.read_bytes()).hexdigest()
    assert after == before


def test_ip_digits_are_compared_independently():
    drone = {"防护等级": "IP65", "_evidence_fields": {"防护等级"}}
    sensor = {"_evidence_fields": set()}
    computer = {"_evidence_fields": set()}
    result, _ = _protection_result(drone, sensor, computer, {
        "protection_rating": "IP57",
        "protection_scope": "specified_devices",
        "specified_protected_device_types": ["drone"],
    })
    assert result["status"] == "rejected"


def test_parsed_price_without_field_evidence_is_not_reported_missing():
    drone = {"参考价格(CNY)": 100, "_evidence_fields": set()}
    sensor = {"参考价格(CNY)": 200, "_evidence_fields": {"参考价格(CNY)"}}
    computer = {"参考价格(CNY)": 300, "_evidence_fields": {"参考价格(CNY)"}}
    result = _budget_result(drone, sensor, computer, 1000)
    assert result["status"] == "insufficient_data"
    assert result["missing_device_fields"] == []
    assert result["insufficient_evidence"] == ["drone.price_cny"]


def test_protection_level_fallback_accepts_matching_field_evidence():
    drone = {"protection_level": "IP67", "_evidence_fields": {"protection_level"}}
    sensor = {"_evidence_fields": set()}
    computer = {"_evidence_fields": set()}
    result, _ = _protection_result(drone, sensor, computer, {
        "protection_rating": "IP57",
        "protection_scope": "specified_devices",
        "specified_protected_device_types": ["drone"],
    })
    assert result["status"] == "satisfied"
    assert result["missing_device_fields"] == []
    assert result["insufficient_evidence"] == []


def _temperature_device(low, high, evidence_fields):
    return {
        "工作温度最低值(℃)": low,
        "工作温度最高值(℃)": high,
        "_evidence_fields": set(evidence_fields),
    }


@pytest.mark.parametrize(
    ("unverified_device", "insufficient_field"),
    [
        (_temperature_device(0.0, 50.0, {"工作温度最高值(℃)"}), "drone.temperature_min_c"),
        (_temperature_device(-20.0, 30.0, {"工作温度最低值(℃)"}), "drone.temperature_max_c"),
    ],
)
def test_unverified_out_of_range_temperature_is_insufficient_not_rejected(
    unverified_device, insufficient_field
):
    verified_device = _temperature_device(
        -20.0, 50.0, {"工作温度最低值(℃)", "工作温度最高值(℃)"}
    )
    result = _temperature_result(
        unverified_device,
        verified_device,
        verified_device,
        {"temperature_min_c": -10.0, "temperature_max_c": 40.0},
    )

    assert result["status"] == "insufficient_data"
    assert insufficient_field in result["insufficient_evidence"]


def test_unverified_out_of_range_temperature_obeys_manual_review_policy(monkeypatch):
    verified_fields = {"工作温度最低值(℃)", "工作温度最高值(℃)"}
    drone = {
        "_device_id": "drone-1",
        "_evidence_sources": [],
        **_temperature_device(0.0, 50.0, {"工作温度最高值(℃)"}),
    }
    sensor = {
        "_device_id": "sensor-1",
        "_evidence_sources": [],
        **_temperature_device(-20.0, 50.0, verified_fields),
    }
    computer = {
        "_device_id": "computer-1",
        "_evidence_sources": [],
        **_temperature_device(-20.0, 50.0, verified_fields),
    }
    pools = {"drone": [drone], "sensor": [sensor], "computer": [computer]}
    scope = {"source": "test", "trusted_device_records": 3}
    monkeypatch.setattr(
        "semantic_candidate_service._load_trusted_pool",
        lambda _database_path: (pools, scope),
    )
    constraints = {"temperature_min_c": -10.0, "temperature_max_c": 40.0}

    retained = evaluate_trusted_candidates(
        "unused.db", constraints, top_n=10, allow_manual_review=True
    )
    excluded = evaluate_trusted_candidates(
        "unused.db", constraints, top_n=10, allow_manual_review=False
    )

    assert len(retained["items"]) == 1
    assert retained["items"][0]["recommendation_disposition"] == "provisional"
    assert retained["items"][0]["constraint_results"][0]["status"] == "insufficient_data"
    assert excluded["items"] == []


@pytest.mark.parametrize(
    "device",
    [
        _temperature_device(0.0, 50.0, {"工作温度最低值(℃)", "工作温度最高值(℃)"}),
        _temperature_device(-20.0, 30.0, {"工作温度最低值(℃)", "工作温度最高值(℃)"}),
    ],
)
def test_verified_out_of_range_temperature_is_rejected(device):
    verified_device = _temperature_device(
        -20.0, 50.0, {"工作温度最低值(℃)", "工作温度最高值(℃)"}
    )
    result = _temperature_result(
        device,
        verified_device,
        verified_device,
        {"temperature_min_c": -10.0, "temperature_max_c": 40.0},
    )

    assert result["status"] == "rejected"


def test_verified_temperature_range_remains_satisfied():
    verified_device = _temperature_device(
        -20.0, 50.0, {"工作温度最低值(℃)", "工作温度最高值(℃)"}
    )
    result = _temperature_result(
        verified_device,
        verified_device,
        verified_device,
        {"temperature_min_c": -10.0, "temperature_max_c": 40.0},
    )

    assert result["status"] == "satisfied"
