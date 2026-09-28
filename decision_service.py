"""Database-backed catalog, compatibility, and deterministic recommendation services."""

from __future__ import annotations

import heapq
import itertools
import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from rules_engine import RULE_IDS, evaluate_rules, is_empty


TABLES = {"drone": "drones", "sensor": "sensors", "computer": "computers"}
V2_TYPES = {"drone": "uav", "sensor": "sensor", "computer": "computer"}
DEFAULT_WEIGHTS = {
    "task_constraint_fit": 25.0,
    "payload_margin": 15.0,
    "power_compatibility": 15.0,
    "environment_adaptation": 10.0,
    "interface_software": 15.0,
    "data_completeness": 10.0,
    "evidence_trust": 10.0,
}


def device_display_name(device: dict[str, Any]) -> str | None:
    """Return an existing human-readable name without changing the device ID."""
    for key in ("model_name", "name", "device_name", "型号", "model"):
        value = device.get(key)
        if not is_empty(value):
            return str(value).strip()
    return None


class ApiValidationError(ValueError):
    pass


class DeviceNotFoundError(LookupError):
    pass


def connect(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def normalized_status(row: sqlite3.Row) -> str:
    if row["verification_status"] in {"verified", "partial", "catalog_only"}:
        return row["verification_status"]
    if row["data_status"] in {"verified", "partial", "catalog_only"}:
        return row["data_status"]
    return "catalog_only"


def serialize_catalog_row(device_type: str, row: sqlite3.Row) -> dict[str, Any]:
    attributes = json.loads(row["raw_data"]) if row["raw_data"] else {}
    base = {key: row[key] for key in row.keys() if key not in {"raw_data", "update_date"}}
    base["device_type"] = device_type
    base["verification_status"] = normalized_status(row)
    base["attributes"] = attributes
    return base


def list_catalog(
    db_path: str | Path,
    device_type: str,
    *,
    q: str | None,
    page: int,
    page_size: int,
    verification_status: str | None,
    brand: str | None,
    category: str | None = None,
) -> dict[str, Any]:
    table = TABLES[device_type]
    clauses: list[str] = []
    params: list[Any] = []
    if q:
        clauses.append("(LOWER(device_id) LIKE ? OR LOWER(brand) LIKE ? OR LOWER(model) LIKE ? OR LOWER(raw_data) LIKE ?)")
        needle = f"%{q.lower()}%"
        params.extend([needle] * 4)
    if brand:
        clauses.append("LOWER(brand) = ?")
        params.append(brand.lower())
    if category:
        if device_type != "sensor":
            raise ApiValidationError("category 仅适用于传感器目录")
        clauses.append("LOWER(category) = ?")
        params.append(category.lower())
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    with connect(db_path) as conn:
        rows = conn.execute(f"SELECT * FROM {table}{where} ORDER BY device_id", params).fetchall()
    if verification_status:
        rows = [row for row in rows if normalized_status(row) == verification_status]
    total = len(rows)
    start = (page - 1) * page_size
    items = [serialize_catalog_row(device_type, row) for row in rows[start : start + page_size]]
    return {"items": items, "total": total, "page": page, "page_size": page_size, "pages": (total + page_size - 1) // page_size}


def _load_evidence(conn: sqlite3.Connection, device_type: str, device_id: str) -> list[str]:
    db_type = V2_TYPES[device_type]
    return sorted({row[0] for row in conn.execute(
        "SELECT source_url FROM verification_evidence WHERE device_type=? AND device_id=? AND source_url IS NOT NULL",
        (db_type, device_id),
    ) if row[0]})


def get_decision_device(conn: sqlite3.Connection, device_type: str, device_id: str) -> dict[str, Any]:
    v2_type = V2_TYPES[device_type]
    row = conn.execute("SELECT raw_data,verification_status,evidence_count FROM v2_compatibility WHERE device_type=? AND device_id=?", (v2_type, device_id)).fetchone()
    if row:
        data = json.loads(row["raw_data"])
        data.update(_device_metadata(device_id, device_type, row["verification_status"], row["evidence_count"], _load_evidence(conn, device_type, device_id), True))
        return data
    table = TABLES[device_type]
    row = conn.execute(f"SELECT * FROM {table} WHERE device_id=?", (device_id,)).fetchone()
    if not row:
        raise DeviceNotFoundError(f"不存在的{device_type} ID: {device_id}")
    data = json.loads(row["raw_data"]) if row["raw_data"] else {}
    data.update(_device_metadata(device_id, device_type, normalized_status(row), row["evidence_count"], _load_evidence(conn, device_type, device_id), False))
    return data


def _device_metadata(device_id: str, device_type: str, status: str, evidence_count: int, sources: list[str], in_verified_layer: bool) -> dict[str, Any]:
    return {
        "_device_id": device_id,
        "_device_type": device_type,
        "_verification_status": status,
        "_evidence_count": evidence_count,
        "_evidence_sources": sources,
        "_in_verified_layer": in_verified_layer,
    }


def check_compatibility(db_path: str | Path, drone_id: str, sensor_ids: list[str], computer_id: str, requirements: dict[str, Any], enabled_rules: list[str] | None = None) -> dict[str, Any]:
    with connect(db_path) as conn:
        drone = get_decision_device(conn, "drone", drone_id)
        sensors = [get_decision_device(conn, "sensor", sensor_id) for sensor_id in sensor_ids]
        computer = get_decision_device(conn, "computer", computer_id)
    result = evaluate_rules(drone, sensors, computer, requirements, enabled_rules)
    result.update({
        "drone_id": drone_id,
        "sensor_ids": sensor_ids,
        "computer_id": computer_id,
        "verification": {
            "combination_verified": False,
            "note": "设备证据状态不代表该计算组合已经验证。",
            "devices": {
                drone_id: drone["_verification_status"],
                **{sensor_id: sensor["_verification_status"] for sensor_id, sensor in zip(sensor_ids, sensors)},
                computer_id: computer["_verification_status"],
            },
        },
    })
    return result


def _load_v2_pool(conn: sqlite3.Connection, device_type: str) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT device_id,raw_data,verification_status,evidence_count FROM v2_compatibility WHERE device_type=? ORDER BY device_id", (V2_TYPES[device_type],)).fetchall()
    result = []
    for row in rows:
        data = json.loads(row["raw_data"])
        data.update(_device_metadata(row["device_id"], device_type, row["verification_status"], row["evidence_count"], _load_evidence(conn, device_type, row["device_id"]), True))
        result.append(data)
    return result


def _matches_structure(device: dict[str, Any], requirements: dict[str, Any], device_type: str) -> bool:
    id_filter = requirements.get(f"{device_type}_ids")
    if id_filter and device["_device_id"] not in id_filter:
        return False
    brand = requirements.get(f"{device_type}_brand")
    actual_brand = device.get("厂家")
    if brand and (not actual_brand or str(actual_brand).lower() != str(brand).lower()):
        return False
    if device_type == "sensor" and requirements.get("sensor_category"):
        category = device.get("类别") or device.get("标准化类别") or device.get("传感器子类")
        if not category or str(requirements["sensor_category"]).lower() not in str(category).lower():
            return False
    return True


def _score(rule_result: dict[str, Any], devices: list[dict[str, Any]], weights: dict[str, float]) -> tuple[float, dict[str, Any], float]:
    by_rule = {item["rule_id"]: item for item in rule_result["rule_results"]}
    components: dict[str, float | None] = {}
    determinate = [item for item in by_rule.values() if item["status"] != "manual_review"]
    components["task_constraint_fit"] = 100.0 * sum(item["status"] == "pass" for item in determinate) / len(determinate) if determinate else None
    r01 = by_rule.get("R01", {}).get("compared_values", {})
    if r01.get("payload_margin_kg") is not None and r01.get("drone_max_payload_kg"):
        components["payload_margin"] = max(0.0, min(100.0, 100.0 * r01["payload_margin_kg"] / r01["drone_max_payload_kg"]))
    else:
        components["payload_margin"] = None
    r03 = by_rule.get("R03", {}).get("compared_values", {})
    if r03.get("power_margin_w") is not None and r03.get("drone_payload_power_w"):
        components["power_compatibility"] = max(0.0, min(100.0, 100.0 * r03["power_margin_w"] / r03["drone_payload_power_w"]))
    else:
        components["power_compatibility"] = None
    components["environment_adaptation"] = 100.0 if by_rule.get("R06", {}).get("status") == "pass" else None
    interface_states = [by_rule.get(rule_id, {}).get("status") for rule_id in ("R05", "R07")]
    known_interface = [state for state in interface_states if state != "manual_review"]
    components["interface_software"] = 100.0 * sum(state == "pass" for state in known_interface) / len(known_interface) if known_interface else None
    required_keys = {
        "drone": ("最大有效载荷(kg)", "载荷最大输出功率(W)", "载荷输出电压最小值(V)", "载荷输出电压最大值(V)"),
        "sensor": ("重量(kg)", "功耗(W)", "输入电压最小值(V)", "输入电压最大值(V)", "数据接口"),
        "computer": ("重量(kg)", "最大功耗(W)", "输入电压最小值(V)", "输入电压最大值(V)", "数据接口"),
    }
    fields = [(device, key) for device in devices for key in required_keys[device["_device_type"]]]
    components["data_completeness"] = 100.0 * sum(not is_empty(device.get(key)) for device, key in fields) / len(fields)
    trust = {"verified": 100.0, "partial": 65.0, "catalog_only": 30.0}
    components["evidence_trust"] = sum(trust.get(device["_verification_status"], 30.0) for device in devices) / len(devices)
    available_weight = sum(weights[name] for name, value in components.items() if value is not None)
    total_weight = sum(weights.values())
    coverage = available_weight / total_weight if total_weight else 0.0
    raw_score = sum(weights[name] * value for name, value in components.items() if value is not None) / available_weight if available_weight else 0.0
    score = round(raw_score * (0.5 + 0.5 * coverage), 4)
    breakdown = {name: {"score": None if value is None else round(value, 4), "weight": weights[name], "included": value is not None} for name, value in components.items()}
    return score, breakdown, round(coverage, 4)


def _validated_weights(custom: dict[str, Any] | None) -> dict[str, float]:
    result = dict(DEFAULT_WEIGHTS)
    if not custom:
        return result
    unknown = set(custom) - set(result)
    if unknown:
        raise ApiValidationError(f"未知评分权重: {', '.join(sorted(unknown))}")
    for key, value in custom.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            raise ApiValidationError(f"权重 {key} 必须是非负数")
        result[key] = float(value)
    if sum(result.values()) <= 0:
        raise ApiValidationError("评分权重总和必须大于 0")
    return result


def recommend(db_path: str | Path, requirements: dict[str, Any], top_n: int, allow_manual_review: bool, custom_weights: dict[str, Any] | None) -> dict[str, Any]:
    started = time.perf_counter()
    weights = _validated_weights(custom_weights)
    enabled_rules = requirements.get("enabled_rules")
    if enabled_rules is not None:
        if not isinstance(enabled_rules, list) or not enabled_rules or any(rule not in RULE_IDS for rule in enabled_rules):
            raise ApiValidationError("requirements.enabled_rules 必须是 R01～R07 的非空数组")
        if len(set(enabled_rules)) != len(enabled_rules):
            raise ApiValidationError("requirements.enabled_rules 不得重复")
    with connect(db_path) as conn:
        pools = {device_type: [device for device in _load_v2_pool(conn, device_type) if _matches_structure(device, requirements, device_type)] for device_type in TABLES}
        dataset_summary = {
            "catalog": {key: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for key, table in TABLES.items()},
            "verified_compatibility_records": conn.execute("SELECT COUNT(*) FROM v2_compatibility").fetchone()[0],
            "field_evidence_records": conn.execute("SELECT COUNT(*) FROM verification_evidence").fetchone()[0],
            "candidate_pool": {key: len(value) for key, value in pools.items()},
        }
    heap: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    checked = rejected = pass_count = manual_count = 0
    for drone, sensor, computer in itertools.product(pools["drone"], pools["sensor"], pools["computer"]):
        checked += 1
        result = evaluate_rules(drone, [sensor], computer, requirements, enabled_rules)
        status = result["overall_status"]
        if status == "fail":
            rejected += 1
            continue
        if status == "manual_review":
            manual_count += 1
            if not allow_manual_review:
                rejected += 1
                continue
        else:
            pass_count += 1
        devices = [drone, sensor, computer]
        score, breakdown, coverage = _score(result, devices, weights)
        ids = (drone["_device_id"], sensor["_device_id"], computer["_device_id"])
        item = {
            "drone_id": ids[0], "sensor_ids": [ids[1]], "computer_id": ids[2],
            "drone_name": device_display_name(drone),
            "sensor_names": [device_display_name(sensor)],
            "computer_name": device_display_name(computer),
            "overall_status": status, "score": score, "score_breakdown": breakdown,
            "coverage": coverage, "confidence": coverage,
            "rule_results": result["rule_results"], "missing_fields": result["missing_fields"],
            "evidence_sources": result["evidence_sources"],
            "combination_verified": False,
        }
        rank = (1 if status == "pass" else 0, score, tuple(chr(0x10FFFF - ord(ch)) for ch in "|".join(ids)))
        if len(heap) < top_n:
            heapq.heappush(heap, (rank, item))
        elif rank > heap[0][0]:
            heapq.heapreplace(heap, (rank, item))
    recommendations = [item for _, item in heap]
    recommendations.sort(key=lambda item: (0 if item["overall_status"] == "pass" else 1, -item["score"], item["drone_id"], item["sensor_ids"], item["computer_id"]))
    return {
        "recommendations": recommendations,
        "dataset_summary": dataset_summary,
        "combinations_checked": checked,
        "rejected_count": rejected,
        "pass_count": pass_count,
        "manual_review_count": manual_count,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
    }


def _semantic_rule_result(rule_id: str, constraint_results: list[dict[str, Any]]) -> dict[str, Any] | None:
    constraint_ids = {
        "R01": ("stage8_payload",),
        "R02": ("stage8_budget",),
        "R06": ("stage8_temperature", "stage8_protection"),
    }.get(rule_id, ())
    matched = [item for item in constraint_results if item.get("constraint_id") in constraint_ids]
    if not matched:
        return None
    statuses = {item["status"] for item in matched}
    status = "fail" if "rejected" in statuses else "manual_review" if "insufficient_data" in statuses else "pass"
    return {
        "rule_id": rule_id,
        "status": status,
        "reason": "Stage 8 semantic constraint result bridged without changing the underlying evaluation.",
        "compared_values": {item["constraint_id"]: item["compared_values"] for item in matched},
        "missing_fields": sorted({field for item in matched for field in item["missing_device_fields"]}),
        "evidence_sources": [],
    }


def evaluate_semantic_candidates(
    db_path: str | Path,
    candidates: list[dict[str, Any]],
    requirements: dict[str, Any],
    *,
    top_n: int,
    allow_manual_review: bool,
    custom_weights: dict[str, Any] | None,
) -> dict[str, Any]:
    """Apply the existing Stage 7 rule and scoring chain to D2 candidate IDs."""

    weights = _validated_weights(custom_weights)
    stage7_rules = ["R03", "R04"]
    device_cache: dict[tuple[str, str], dict[str, Any]] = {}
    with connect(db_path) as conn:
        def load(device_type: str, device_id: str) -> dict[str, Any]:
            key = (device_type, device_id)
            if key not in device_cache:
                device_cache[key] = get_decision_device(conn, device_type, device_id)
            return device_cache[key]

        evaluated_items = []
        for candidate in candidates:
            drone = load("drone", candidate["drone_id"])
            sensors = [load("sensor", sensor_id) for sensor_id in candidate["sensor_ids"]]
            computer = load("computer", candidate["computer_id"])
            stage7 = evaluate_rules(drone, sensors, computer, requirements, stage7_rules)
            stage7_by_rule = {item["rule_id"]: item for item in stage7["rule_results"]}
            rule_results = []
            for rule_id in RULE_IDS:
                result = stage7_by_rule.get(rule_id) or _semantic_rule_result(
                    rule_id, candidate["constraint_results"]
                )
                if result is None:
                    result = {
                        "rule_id": rule_id,
                        "status": "not_evaluated",
                        "reason": "The rule is not applicable or is not safely enabled for this semantic request.",
                        "compared_values": {},
                        "missing_fields": [],
                        "evidence_sources": [],
                    }
                rule_results.append(result)

            determinate_results = [item for item in rule_results if item["status"] != "not_evaluated"]
            scoring_result = {"rule_results": determinate_results}
            devices = [drone, *sensors, computer]
            score, breakdown, coverage = _score(scoring_result, devices, weights)
            statuses = {item["status"] for item in determinate_results}
            if "fail" in statuses:
                continue
            if "manual_review" in statuses and not allow_manual_review:
                continue
            missing_fields = sorted({
                *candidate["missing_device_fields"],
                *(field for item in rule_results for field in item["missing_fields"]),
            })
            reasons = [
                {"source": item["constraint_id"], "status": item["status"], "reason": item["reason"]}
                for item in candidate["constraint_results"]
            ] + [
                {"source": item["rule_id"], "status": item["status"], "reason": item["reason"]}
                for item in rule_results
            ]
            evaluated_items.append({
                **candidate,
                "drone_name": device_display_name(drone),
                "sensor_names": [device_display_name(sensor) for sensor in sensors],
                "computer_name": device_display_name(computer),
                "score": score,
                "score_breakdown": breakdown,
                "coverage": coverage,
                "rule_results": rule_results,
                "missing_fields": missing_fields,
                "reasons": reasons,
                "combination_verified": False,
                "recommendation_disposition": "provisional",
                "is_final": False,
            })

    evaluated_items.sort(key=lambda item: (
        -item["score"], item["drone_id"], item["sensor_ids"], item["computer_id"]
    ))
    return {
        "items": evaluated_items[:top_n],
        "weights": weights,
        "enabled_rules": [
            rule_id for rule_id in RULE_IDS
            if any(result["rule_id"] == rule_id and result["status"] != "not_evaluated"
                   for item in evaluated_items for result in item["rule_results"])
        ],
    }


def stats(db_path: str | Path) -> dict[str, Any]:
    with connect(db_path) as conn:
        counts = {key: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for key, table in TABLES.items()}
        compatibility = conn.execute("SELECT COUNT(*) FROM v2_compatibility").fetchone()[0]
        evidence = conn.execute("SELECT COUNT(*) FROM verification_evidence").fetchone()[0]
        statuses = {row[0] or "unknown": row[1] for row in conn.execute("SELECT verification_status,COUNT(*) FROM v2_compatibility GROUP BY verification_status")}
    return {"catalog_counts": counts, "compatibility_records": compatibility, "field_evidence_records": evidence, "verification_status_counts": statuses}
