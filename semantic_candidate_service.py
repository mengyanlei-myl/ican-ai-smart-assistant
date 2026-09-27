"""Read-only Stage 8 candidate evaluation over the trusted compatibility layer."""

from __future__ import annotations

import itertools
import json
import re
import sqlite3
from pathlib import Path
from typing import Any


DEVICE_ORDER = ("drone", "sensor", "computer")
DB_TYPES = {"drone": "uav", "sensor": "sensor", "computer": "computer"}


def _number(device: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = device.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str) and re.fullmatch(r"\s*[-+]?\d+(?:\.\d+)?\s*", value.replace(",", "")):
            return float(value.replace(",", "").strip())
    return None


def _ip_level(value: Any) -> tuple[int, int] | None:
    match = re.search(r"IP\s*(\d)(\d)", str(value or ""), re.IGNORECASE)
    return (int(match.group(1)), int(match.group(2))) if match else None


def _sources(device: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("来源链接", "官方链接", "source_url"):
        value = device.get(key)
        if value:
            values.extend(part.strip() for part in str(value).split(";") if part.strip())
    return sorted(set(values))


def _has_field_evidence(device: dict[str, Any], *keys: str) -> bool:
    return bool(set(keys) & device.get("_evidence_fields", set()))


def _open_read_only(db_path: str | Path) -> sqlite3.Connection:
    uri = Path(db_path).resolve().as_uri() + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _load_trusted_pool(db_path: str | Path) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    pools = {device_type: [] for device_type in DEVICE_ORDER}
    with _open_read_only(db_path) as connection:
        evidence_by_device: dict[tuple[str, str], dict[str, set[str]]] = {}
        for row in connection.execute(
            "SELECT device_type,device_id,field_name,source_url FROM verification_evidence "
            "WHERE device_type IN ('uav','sensor','computer')"
        ):
            bucket = evidence_by_device.setdefault(
                (row["device_type"], row["device_id"]), {"fields": set(), "sources": set()}
            )
            if row["field_name"]:
                bucket["fields"].add(row["field_name"])
            if row["source_url"]:
                bucket["sources"].add(row["source_url"])
        rows = connection.execute(
            "SELECT device_id,device_type,raw_data,verification_status,evidence_count "
            "FROM v2_compatibility WHERE device_type IN ('uav','sensor','computer') ORDER BY device_type,device_id"
        ).fetchall()
        for row in rows:
            public_type = next(key for key, value in DB_TYPES.items() if value == row["device_type"])
            device = json.loads(row["raw_data"])
            evidence = evidence_by_device.get((row["device_type"], row["device_id"]), {"fields": set(), "sources": set()})
            device.update({
                "_device_id": row["device_id"],
                "_device_type": public_type,
                "_verification_status": row["verification_status"],
                "_evidence_count": row["evidence_count"],
                "_evidence_fields": evidence["fields"],
                "_evidence_sources": sorted(set(_sources(device)) | evidence["sources"]),
            })
            pools[public_type].append(device)
    counts = {device_type: len(pools[device_type]) for device_type in DEVICE_ORDER}
    scope = {
        "source": "v2_compatibility",
        "trusted_device_records": sum(counts.values()),
        "counts": counts,
        "full_catalog_used": False,
    }
    return pools, scope


def _result(
    constraint_id: str,
    status: str,
    reason: str,
    compared_values: dict[str, Any],
    missing_fields: list[str] | None = None,
    insufficient_evidence: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "constraint_id": constraint_id,
        "status": status,
        "reason": reason,
        "compared_values": compared_values,
        "missing_device_fields": sorted(set(missing_fields or [])),
        "insufficient_evidence": sorted(set(insufficient_evidence or [])),
    }


def _payload_result(drone, sensor, computer, constraints):
    drone_keys = ("最大有效载荷(kg)", "最大有效载荷kg", "标准化最大有效载荷kg")
    sensor_keys = ("重量(kg)", "标准化重量(kg)")
    computer_keys = ("重量(kg)",)
    drone_max = _number(drone, *drone_keys)
    sensor_weight = _number(sensor, *sensor_keys)
    computer_weight = _number(computer, *computer_keys)
    task_payload = float(constraints["task_payload_requirement_kg"])
    installation = float(constraints["installation_margin_kg"])
    user_max = constraints.get("max_total_mounted_weight_kg")
    missing = []
    insufficient = []
    if drone_max is None:
        missing.append("drone.drone_max_payload_kg")
    if sensor_weight is None:
        missing.append("sensor.sensor_weight_kg")
    if computer_weight is None:
        missing.append("computer.computer_weight_kg")
    if drone_max is not None and not _has_field_evidence(drone, *drone_keys):
        insufficient.append("drone.drone_max_payload_kg")
    if sensor_weight is not None and not _has_field_evidence(sensor, *sensor_keys):
        insufficient.append("sensor.sensor_weight_kg")
    if computer_weight is not None and not _has_field_evidence(computer, *computer_keys):
        insufficient.append("computer.computer_weight_kg")
    compared = {
        "task_payload_requirement_kg": task_payload,
        "sensor_total_weight_kg": sensor_weight,
        "computer_weight_kg": computer_weight,
        "installation_margin_kg": installation,
        "total_mounted_weight_kg": None,
        "drone_max_payload_kg": drone_max,
        "max_total_mounted_weight_kg": user_max,
        "payload_margin_kg": None,
    }
    if missing or insufficient:
        return _result("stage8_payload", "insufficient_data", "载荷设备字段或字段证据不完整。", compared, missing, insufficient)
    total = task_payload + sensor_weight + computer_weight + installation
    compared["total_mounted_weight_kg"] = total
    compared["payload_margin_kg"] = drone_max - total
    rejected = total > drone_max or (user_max is not None and total > float(user_max))
    return _result(
        "stage8_payload", "rejected" if rejected else "satisfied",
        "总挂载重量超过允许上限。" if rejected else "总挂载重量满足已声明上限。", compared,
    )


def _endurance_result(drone, minimum):
    keys = ("最大飞行时间min", "典型飞行时间min")
    actual = _number(drone, *keys)
    compared = {"required_min_endurance_min": minimum, "published_endurance_min": actual}
    if actual is None:
        return _result("stage8_endurance", "insufficient_data", "无人机缺少可解析的公开续航字段。", compared, ["drone.endurance_min"])
    if not _has_field_evidence(drone, *keys):
        return _result("stage8_endurance", "insufficient_data", "无人机续航字段缺少字段级证据。", compared, insufficient_evidence=["drone.endurance_min"])
    status = "satisfied" if actual >= float(minimum) else "rejected"
    reason = "公开续航不低于任务下限；不代表实际工况续航保证。" if status == "satisfied" else "公开续航低于任务下限。"
    return _result("stage8_endurance", status, reason, compared)


def _budget_result(drone, sensor, computer, maximum):
    devices = (("drone", drone), ("sensor", sensor), ("computer", computer))
    prices: dict[str, float | None] = {}
    missing = []
    insufficient = []
    for name, device in devices:
        keys = ("参考价格(CNY)", "标准化参考价格(CNY)")
        price = _number(device, *keys)
        prices[name] = price
        if price is None:
            missing.append(f"{name}.price_cny")
        elif not _has_field_evidence(device, *keys):
            insufficient.append(f"{name}.price_cny")
    compared = {"max_budget_cny": maximum, "device_prices_cny": prices, "priced_total_cny": None}
    if missing or insufficient:
        return _result(
            "stage8_budget", "insufficient_data",
            "预算范围内存在未定价项目或价格缺少字段级证据，不能判定预算通过。",
            compared, missing, insufficient,
        )
    total = sum(prices.values())
    compared["priced_total_cny"] = total
    status = "satisfied" if total <= float(maximum) else "rejected"
    return _result("stage8_budget", status, "价格覆盖完整且在预算内。" if status == "satisfied" else "已定价总额超过预算。", compared)


def _temperature_result(drone, sensor, computer, constraints):
    required_min = constraints.get("temperature_min_c")
    required_max = constraints.get("temperature_max_c")
    devices = (("drone", drone), ("sensor", sensor), ("computer", computer))
    compared_devices = []
    missing = []
    insufficient = []
    rejected = False
    for name, device in devices:
        low_key = "工作温度最低值(℃)"
        high_key = "工作温度最高值(℃)"
        low = _number(device, low_key)
        high = _number(device, high_key)
        low_has_evidence = _has_field_evidence(device, low_key)
        high_has_evidence = _has_field_evidence(device, high_key)
        compared_devices.append({"device_type": name, "temperature_min_c": low, "temperature_max_c": high})
        if required_min is not None and low is None:
            missing.append(f"{name}.temperature_min_c")
        if required_max is not None and high is None:
            missing.append(f"{name}.temperature_max_c")
        if required_min is not None and low is not None and not low_has_evidence:
            insufficient.append(f"{name}.temperature_min_c")
        if required_max is not None and high is not None and not high_has_evidence:
            insufficient.append(f"{name}.temperature_max_c")
        if required_min is not None and low is not None and low_has_evidence and low > float(required_min):
            rejected = True
        if required_max is not None and high is not None and high_has_evidence and high < float(required_max):
            rejected = True
    compared = {"required_temperature_min_c": required_min, "required_temperature_max_c": required_max, "devices": compared_devices}
    if rejected:
        return _result("stage8_temperature", "rejected", "至少一个设备明确不覆盖任务温度。", compared, missing)
    if missing or insufficient:
        return _result("stage8_temperature", "insufficient_data", "至少一个设备缺少所需温度字段或证据。", compared, missing, insufficient)
    return _result("stage8_temperature", "satisfied", "三类设备均覆盖已声明温度边界。", compared)


def _protection_result(drone, sensor, computer, constraints):
    required_text = constraints["protection_rating"]
    required = _ip_level(required_text)
    scope = constraints["protection_scope"]
    specified = constraints["specified_protected_device_types"]
    devices = {"drone": drone, "sensor": sensor, "computer": computer}
    exposure = {"drone": "unknown", "sensors": ["unknown"], "computer": "unknown"}
    if scope == "exposed_devices":
        return _result(
            "stage8_protection", "insufficient_data", "设备暴露状态缺少结构化证据，无法确定防护评价对象。",
            {"required_protection_rating": required_text, "protection_scope": scope, "devices": []},
            ["exposure_assessment"], ["exposure_assessment"],
        ), exposure
    targets = list(DEVICE_ORDER) if scope == "all_devices" else list(specified)
    compared_devices = []
    missing = []
    insufficient = []
    rejected = False
    for name in targets:
        raw = devices[name].get("防护等级") or devices[name].get("protection_level")
        level = _ip_level(raw)
        compared_devices.append({"device_type": name, "protection_rating": raw})
        if level is None:
            missing.append(f"{name}.protection_rating")
        elif not _has_field_evidence(devices[name], "防护等级", "protection_level"):
            insufficient.append(f"{name}.protection_rating")
        elif required is not None and (level[0] < required[0] or level[1] < required[1]):
            rejected = True
    compared = {"required_protection_rating": required_text, "protection_scope": scope, "devices": compared_devices}
    if rejected:
        result = _result("stage8_protection", "rejected", "至少一个指定设备的防护等级低于要求。", compared, missing)
    elif missing or insufficient:
        result = _result("stage8_protection", "insufficient_data", "至少一个指定设备缺少 IP 防护字段或证据。", compared, missing, insufficient)
    else:
        result = _result("stage8_protection", "satisfied", "所有指定设备的 IP 防护等级满足要求。", compared)
    return result, exposure


def evaluate_trusted_candidates(
    db_path: str | Path,
    constraints: dict[str, Any],
    *,
    top_n: int,
    allow_manual_review: bool,
) -> dict[str, Any]:
    """Evaluate supported D2 constraints without invoking Stage 7 rules."""

    pools, pool_scope = _load_trusted_pool(db_path)
    items = []
    rejected_count = insufficient_count = 0
    aggregate_missing: set[str] = set()
    aggregate_evidence: set[str] = set()
    executed_ids: list[str] = []
    for constraint_id, fields in (
        ("stage8_payload", {"task_payload_requirement_kg", "installation_margin_kg", "max_total_mounted_weight_kg"}),
        ("stage8_endurance", {"min_endurance_min"}),
        ("stage8_budget", {"max_budget_cny"}),
        ("stage8_temperature", {"temperature_min_c", "temperature_max_c"}),
        ("stage8_protection", {"protection_rating"}),
    ):
        if set(constraints) & fields:
            executed_ids.append(constraint_id)

    for drone, sensor, computer in itertools.product(pools["drone"], pools["sensor"], pools["computer"]):
        results = []
        exposure = {"drone": "unknown", "sensors": ["unknown"], "computer": "unknown"}
        if "stage8_payload" in executed_ids:
            results.append(_payload_result(drone, sensor, computer, constraints))
        if "stage8_endurance" in executed_ids:
            results.append(_endurance_result(drone, constraints["min_endurance_min"]))
        if "stage8_budget" in executed_ids:
            results.append(_budget_result(drone, sensor, computer, constraints["max_budget_cny"]))
        if "stage8_temperature" in executed_ids:
            results.append(_temperature_result(drone, sensor, computer, constraints))
        if "stage8_protection" in executed_ids:
            protection, exposure = _protection_result(drone, sensor, computer, constraints)
            results.append(protection)
        missing = sorted({field for result in results for field in result["missing_device_fields"]})
        evidence = sorted({field for result in results for field in result["insufficient_evidence"]})
        aggregate_missing.update(missing)
        aggregate_evidence.update(evidence)
        statuses = {result["status"] for result in results}
        if "rejected" in statuses:
            rejected_count += 1
            continue
        if "insufficient_data" in statuses:
            insufficient_count += 1
            if not allow_manual_review:
                continue
        payload = next((result for result in results if result["constraint_id"] == "stage8_payload"), None)
        endurance = next((result for result in results if result["constraint_id"] == "stage8_endurance"), None)
        payload_margin = payload["compared_values"].get("payload_margin_kg") if payload else None
        endurance_values = endurance["compared_values"] if endurance else {}
        endurance_margin = None
        if endurance_values.get("published_endurance_min") is not None:
            endurance_margin = endurance_values["published_endurance_min"] - endurance_values["required_min_endurance_min"]
        items.append({
            "drone_id": drone["_device_id"], "sensor_ids": [sensor["_device_id"]], "computer_id": computer["_device_id"],
            "constraint_results": results, "missing_device_fields": missing,
            "insufficient_evidence": evidence, "exposure_assessment": exposure,
            "evidence_sources": sorted(set(drone["_evidence_sources"] + sensor["_evidence_sources"] + computer["_evidence_sources"])),
            "recommendation_disposition": "provisional", "is_final": False, "combination_verified": False,
            "_payload_margin": payload_margin, "_endurance_margin": endurance_margin,
        })
    items.sort(key=lambda item: (
        -(item["_payload_margin"] if item["_payload_margin"] is not None else float("-inf")),
        -(item["_endurance_margin"] if item["_endurance_margin"] is not None else float("-inf")),
        item["drone_id"], item["sensor_ids"], item["computer_id"],
    ))
    selected = items[:top_n]
    for item in selected:
        item.pop("_payload_margin")
        item.pop("_endurance_margin")
    return {
        "items": selected,
        "database_queried": True,
        "candidate_pool_scope": pool_scope,
        "executed_constraints": executed_ids,
        "missing_device_fields": sorted(aggregate_missing),
        "insufficient_evidence": sorted(aggregate_evidence),
        "exposure_assessment": {"drone": "unknown", "sensors": ["unknown"], "computer": "unknown"},
        "combinations_checked": len(pools["drone"]) * len(pools["sensor"]) * len(pools["computer"]),
        "rejected_count": rejected_count,
        "insufficient_data_count": insufficient_count,
    }


__all__ = ["evaluate_trusted_candidates"]
