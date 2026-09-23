"""Explainable R01-R07 compatibility rules.

Only fields defined by the project data dictionary are evaluated. Missing or
unparseable values are never treated as zero; they produce ``manual_review``.
"""

from __future__ import annotations

import math
import re
from typing import Any, Iterable


RULE_IDS = tuple(f"R{i:02d}" for i in range(1, 8))


def is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    return isinstance(value, str) and value.strip().lower() in {"", "nan", "none", "null"}


def _first(data: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = data.get(key)
        if not is_empty(value):
            return value
    return None


def _number(data: dict[str, Any], *keys: str) -> float | None:
    value = _first(data, *keys)
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = re.fullmatch(r"\s*([-+]?\d+(?:\.\d+)?)\s*", str(value).replace(",", ""))
    return float(match.group(1)) if match else None


def _text(data: dict[str, Any], *keys: str) -> str | None:
    value = _first(data, *keys)
    return str(value).strip() if value is not None else None


def _result(rule_id: str, status: str, reason: str, compared: dict[str, Any], missing: Iterable[str] = (), sources: Iterable[str] = ()) -> dict[str, Any]:
    return {
        "rule_id": rule_id,
        "status": status,
        "reason": reason,
        "compared_values": compared,
        "missing_fields": sorted(set(missing)),
        "evidence_sources": sorted({source for source in sources if source}),
    }


def _sources(*devices: dict[str, Any]) -> list[str]:
    result: set[str] = set()
    for device in devices:
        value = _first(device, "来源链接", "官方链接", "source_url")
        if value:
            result.update(part.strip() for part in str(value).split(";") if part.strip())
        result.update(source for source in device.get("_evidence_sources", []) if source)
    return sorted(result)


def _values(devices: list[dict[str, Any]], keys: tuple[str, ...], label: str):
    values: list[float] = []
    missing: list[str] = []
    for index, device in enumerate(devices):
        value = _number(device, *keys)
        if value is None:
            missing.append(f"sensors[{index}].{label}")
        else:
            values.append(value)
    return values, missing


def _interface_tokens(value: str | None) -> set[str]:
    if not value:
        return set()
    aliases = {
        "ETHERNET": "ETHERNET", "GIGE": "ETHERNET", "RJ45": "ETHERNET",
        "USB3": "USB3", "USB 3": "USB3", "USB-C": "USBC", "TYPE-C": "USBC",
        "CAN": "CAN", "UART": "UART", "GPIO": "GPIO", "MIPI": "MIPI",
        "CSI": "CSI", "GMSL2": "GMSL2", "GMSL": "GMSL", "PCIE": "PCIE",
        "I2C": "I2C", "SPI": "SPI", "RS232": "RS232", "RS-232": "RS232",
        "RS485": "RS485", "RS-485": "RS485",
    }
    upper = value.upper()
    return {canonical for needle, canonical in aliases.items() if needle in upper}


def _ip_level(value: str | None) -> tuple[int, int] | None:
    if not value:
        return None
    match = re.search(r"IP\s*(\d)(\d)", value.upper())
    return (int(match.group(1)), int(match.group(2))) if match else None


def evaluate_rules(
    drone: dict[str, Any],
    sensors: list[dict[str, Any]],
    computer: dict[str, Any],
    requirements: dict[str, Any] | None = None,
    enabled_rules: Iterable[str] | None = None,
) -> dict[str, Any]:
    requirements = requirements or {}
    enabled = set(enabled_rules or RULE_IDS)
    results: list[dict[str, Any]] = []
    all_sources = _sources(drone, computer, *sensors)

    # R01: sensor weights and computer weight are explicitly additive.
    if "R01" in enabled:
        uav_max = _number(drone, "最大有效载荷(kg)", "最大有效载荷kg", "标准化最大有效载荷kg", "max_payload")
        sensor_weights, missing = _values(sensors, ("重量(kg)", "标准化重量(kg)", "weight"), "重量(kg)")
        computer_weight = _number(computer, "重量(kg)", "weight")
        margin = _number(requirements, "installation_margin_kg", "任务载荷/安装余量(kg)")
        if uav_max is None: missing.append("drone.最大有效载荷(kg)")
        if computer_weight is None: missing.append("computer.重量(kg)")
        if margin is None: missing.append("task_requirements.installation_margin_kg")
        compared = {"drone_max_payload_kg": uav_max, "sensor_weights_kg": sensor_weights, "computer_weight_kg": computer_weight, "installation_margin_kg": margin, "total_payload_kg": None, "payload_margin_kg": None}
        if missing:
            results.append(_result("R01", "manual_review", "载荷字段不完整，无法可靠计算。", compared, missing, all_sources))
        else:
            total = sum(sensor_weights) + computer_weight + margin
            compared.update(total_payload_kg=total, payload_margin_kg=uav_max - total)
            status = "pass" if total <= uav_max else "fail"
            results.append(_result("R01", status, f"总载荷 {total:g} kg {'不超过' if status == 'pass' else '超过'}无人机上限 {uav_max:g} kg。", compared, sources=all_sources))

    # R02: prices are additive; no currency conversion or guessed value.
    if "R02" in enabled:
        missing: list[str] = []
        drone_price = _number(drone, "参考价格(CNY)", "price")
        sensor_prices, sensor_missing = _values(sensors, ("参考价格(CNY)", "price"), "参考价格(CNY)")
        computer_price = _number(computer, "参考价格(CNY)", "price")
        budget = _number(requirements, "budget", "预算(CNY)")
        missing.extend(sensor_missing)
        if drone_price is None: missing.append("drone.参考价格(CNY)")
        if computer_price is None: missing.append("computer.参考价格(CNY)")
        if budget is None: missing.append("task_requirements.budget")
        compared = {"drone_price_cny": drone_price, "sensor_prices_cny": sensor_prices, "computer_price_cny": computer_price, "budget_cny": budget, "total_price_cny": None}
        if missing:
            results.append(_result("R02", "manual_review", "人民币价格或预算缺失；空价格未按 0 处理。", compared, missing, all_sources))
        else:
            total = drone_price + sum(sensor_prices) + computer_price
            compared["total_price_cny"] = total
            status = "pass" if total <= budget else "fail"
            results.append(_result("R02", status, f"总价 {total:g} CNY {'不超过' if status == 'pass' else '超过'}预算 {budget:g} CNY。", compared, sources=all_sources))

    # R03: sensor power is explicitly additive.
    if "R03" in enabled:
        missing: list[str] = []
        output = _number(drone, "载荷最大输出功率(W)", "最大外设供电W", "power")
        sensor_power, sensor_missing = _values(sensors, ("功耗(W)", "power"), "功耗(W)")
        computer_power = _number(computer, "最大功耗(W)", "power")
        missing.extend(sensor_missing)
        if output is None: missing.append("drone.载荷最大输出功率(W)")
        if computer_power is None: missing.append("computer.最大功耗(W)")
        compared = {"drone_payload_power_w": output, "sensor_powers_w": sensor_power, "computer_max_power_w": computer_power, "total_power_w": None, "power_margin_w": None}
        if missing:
            results.append(_result("R03", "manual_review", "功耗或载荷供电上限缺失。", compared, missing, all_sources))
        else:
            total = sum(sensor_power) + computer_power
            compared.update(total_power_w=total, power_margin_w=output - total)
            status = "pass" if total <= output else "fail"
            results.append(_result("R03", status, f"总功耗 {total:g} W {'不超过' if status == 'pass' else '超过'}载荷供电上限 {output:g} W。", compared, sources=all_sources))

    # R04: one common voltage intersection across every device.
    if "R04" in enabled:
        ranges: list[tuple[str, float | None, float | None]] = [
            ("drone", _number(drone, "载荷输出电压最小值(V)"), _number(drone, "载荷输出电压最大值(V)")),
            ("computer", _number(computer, "输入电压最小值(V)"), _number(computer, "输入电压最大值(V)")),
        ]
        ranges += [(f"sensors[{i}]", _number(sensor, "输入电压最小值(V)"), _number(sensor, "输入电压最大值(V)")) for i, sensor in enumerate(sensors)]
        missing = [f"{name}.voltage_range" for name, low, high in ranges if low is None or high is None or (low is not None and high is not None and low > high)]
        compared = {name: [low, high] for name, low, high in ranges}
        compared["common_voltage_range_v"] = None
        if missing:
            results.append(_result("R04", "manual_review", "至少一个电压范围缺失、不可解析或上下限颠倒。", compared, missing, all_sources))
        else:
            common = [max(low for _, low, _ in ranges), min(high for _, _, high in ranges)]
            compared["common_voltage_range_v"] = common
            status = "pass" if common[0] <= common[1] else "fail"
            results.append(_result("R04", status, "存在共同供电电压区间。" if status == "pass" else "设备供电电压范围无交集。", compared, sources=all_sources))

    # R05: every sensor must share a documented data interface with computer.
    if "R05" in enabled:
        computer_interfaces = _text(computer, "数据接口", "interfaces")
        comp_tokens = _interface_tokens(computer_interfaces)
        matches: list[list[str]] = []
        missing: list[str] = []
        explicit_failure = False
        for index, sensor in enumerate(sensors):
            sensor_interfaces = _text(sensor, "数据接口", "接口", "interfaces")
            tokens = _interface_tokens(sensor_interfaces)
            common = sorted(tokens & comp_tokens)
            matches.append(common)
            if not sensor_interfaces:
                missing.append(f"sensors[{index}].数据接口")
            elif comp_tokens and tokens and not common:
                explicit_failure = True
            elif not tokens:
                missing.append(f"sensors[{index}].数据接口(无法标准化)")
        if not computer_interfaces or not comp_tokens:
            missing.append("computer.数据接口")
        mount_values = [_text(drone, "安装/挂载接口")] + [_text(sensor, "安装/挂载接口") for sensor in sensors] + [_text(computer, "安装/挂载接口")]
        if any(value is None for value in mount_values):
            missing.append("安装/挂载接口")
        compared = {"computer_interfaces": computer_interfaces, "sensor_interface_matches": matches, "mount_interfaces": mount_values}
        if explicit_failure:
            results.append(_result("R05", "fail", "已公开的数据接口之间没有共同接口。", compared, missing, all_sources))
        elif missing:
            results.append(_result("R05", "manual_review", "数据接口或安装/挂载信息不足，或可能需要转接。", compared, missing, all_sources))
        else:
            results.append(_result("R05", "pass", "每个传感器与计算平台均有明确共同数据接口，且未发现挂载冲突。", compared, sources=all_sources))

    # R06: all devices must cover mission temperature and protection request.
    if "R06" in enabled:
        req_min = _number(requirements, "mission_temp_min_c", "工作温度最低值(℃)")
        req_max = _number(requirements, "mission_temp_max_c", "工作温度最高值(℃)")
        req_ip_text = _text(requirements, "required_protection_level", "防护等级要求")
        req_ip = _ip_level(req_ip_text)
        devices = [("drone", drone), ("computer", computer)] + [(f"sensors[{i}]", sensor) for i, sensor in enumerate(sensors)]
        compared_devices = []
        missing: list[str] = []
        explicit_failure = False
        if req_min is None: missing.append("task_requirements.mission_temp_min_c")
        if req_max is None: missing.append("task_requirements.mission_temp_max_c")
        if req_ip_text and req_ip is None: missing.append("task_requirements.required_protection_level")
        for name, device in devices:
            low = _number(device, "工作温度最低值(℃)")
            high = _number(device, "工作温度最高值(℃)")
            level_text = _text(device, "防护等级", "protection_level")
            level = _ip_level(level_text)
            compared_devices.append({"device": name, "temperature_c": [low, high], "protection_level": level_text})
            if low is None or high is None:
                missing.append(f"{name}.工作温度范围")
            elif req_min is not None and req_max is not None and (low > req_min or high < req_max):
                explicit_failure = True
            if req_ip:
                if level is None:
                    missing.append(f"{name}.防护等级")
                elif level < req_ip:
                    explicit_failure = True
        compared = {"mission_temperature_c": [req_min, req_max], "required_protection_level": req_ip_text, "devices": compared_devices}
        if explicit_failure:
            results.append(_result("R06", "fail", "至少一个设备明确不满足任务温度或防护要求。", compared, missing, all_sources))
        elif missing:
            results.append(_result("R06", "manual_review", "任务环境条件或设备环境字段不完整。", compared, missing, all_sources))
        else:
            results.append(_result("R06", "pass", "所有设备覆盖任务温度与防护要求。", compared, sources=all_sources))

    # R07: conservative documented software overlap check.
    if "R07" in enabled:
        comp_os = _text(computer, "支持操作系统", "操作系统/ROS")
        comp_ros = _text(computer, "ROS支持", "操作系统/ROS")
        comp_cpu = _text(computer, "CPU型号", "CPU", "cpu")
        compared_sensors = []
        missing: list[str] = []
        explicit_failure = False
        for index, sensor in enumerate(sensors):
            driver = _text(sensor, "驱动或SDK", "驱动链接")
            sensor_os = _text(sensor, "支持操作系统")
            sensor_ros = _text(sensor, "ROS支持")
            compared_sensors.append({"driver_sdk": driver, "os": sensor_os, "ros": sensor_ros})
            if not driver: missing.append(f"sensors[{index}].驱动或SDK")
            if not sensor_os: missing.append(f"sensors[{index}].支持操作系统")
            if not sensor_ros: missing.append(f"sensors[{index}].ROS支持")
            if sensor_os and comp_os:
                linux_sensor = "LINUX" in sensor_os.upper() or "UBUNTU" in sensor_os.upper()
                linux_comp = "LINUX" in comp_os.upper() or "UBUNTU" in comp_os.upper()
                windows_sensor = "WINDOWS" in sensor_os.upper()
                windows_comp = "WINDOWS" in comp_os.upper()
                if not ((linux_sensor and linux_comp) or (windows_sensor and windows_comp)):
                    explicit_failure = True
        if not comp_os: missing.append("computer.支持操作系统")
        if not comp_ros: missing.append("computer.ROS支持")
        if not comp_cpu: missing.append("computer.CPU型号")
        compared = {"computer": {"os": comp_os, "ros": comp_ros, "cpu": comp_cpu}, "sensors": compared_sensors}
        if explicit_failure:
            results.append(_result("R07", "fail", "公开的软件支持信息显示没有共同操作系统。", compared, missing, all_sources))
        elif missing:
            results.append(_result("R07", "manual_review", "驱动、操作系统、CPU 架构或 ROS 信息不完整。", compared, missing, all_sources))
        else:
            results.append(_result("R07", "pass", "存在明确的软件与操作系统共同支持组合。", compared, sources=all_sources))

    statuses = {item["status"] for item in results}
    overall = "fail" if "fail" in statuses else "manual_review" if "manual_review" in statuses else "pass"
    return {
        "overall_status": overall,
        "rule_results": results,
        "missing_fields": sorted({field for item in results for field in item["missing_fields"]}),
        "evidence_sources": sorted({source for item in results for source in item["evidence_sources"]}),
    }


def evaluate_rule(rule_id: str, combo_data: dict[str, Any], enabled_rules: Iterable[str]):
    """Backward-compatible status-only adapter."""
    sensors = combo_data.get("sensors") or [combo_data.get("sensor", {})]
    result = evaluate_rules(combo_data.get("uav", {}), sensors, combo_data.get("computer", {}), combo_data.get("requirements", {}), enabled_rules)
    match = next((item for item in result["rule_results"] if item["rule_id"] == rule_id), None)
    return match["status"] if match else "not_applicable"


def evaluate_combo(combo_data: dict[str, Any], enabled_rules: Iterable[str]):
    """Backward-compatible tuple adapter used by the existing golden cases."""
    sensors = combo_data.get("sensors") or [combo_data.get("sensor", {})]
    result = evaluate_rules(combo_data.get("uav", {}), sensors, combo_data.get("computer", {}), combo_data.get("requirements", {}), enabled_rules)
    details = [{"rule_id": item["rule_id"], "status": item["status"]} for item in result["rule_results"]]
    return result["overall_status"], details
