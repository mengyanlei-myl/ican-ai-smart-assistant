"""Deterministic Stage 8 parser for Chinese task requirement text.

This module deliberately has no dependency on Flask, the database, the rule
engine, or third-party packages.  It extracts only contract fields whose
meaning is explicit in the input; ambiguous payload wording is surfaced as a
clarification instead of being guessed.
"""

from __future__ import annotations

import re
from typing import Any


_NUMBER = r"[-+]?\d+(?:\.\d+)?"
_MASS = rf"(?P<value>{_NUMBER})\s*(?P<unit>kg|千克|公斤|g|克)"
_DURATION = rf"(?P<value>{_NUMBER})\s*(?P<unit>分钟|分|min|小时|时|h)"
_MONEY = rf"(?P<value>{_NUMBER})\s*(?P<unit>万元|万|元|CNY|人民币)"
_TEMP = rf"(?P<value>{_NUMBER})\s*(?:°\s*C|℃|摄氏度|度)"


def _mass_kg(value: str, unit: str) -> float:
    number = float(value)
    return number / 1000 if unit in {"g", "克"} else number


def _duration_min(value: str, unit: str) -> float:
    number = float(value)
    return number * 60 if unit in {"小时", "时", "h"} else number


def _money_cny(value: str, unit: str) -> float:
    number = float(value)
    return number * 10000 if unit in {"万元", "万"} else number


def _clean_number(value: float) -> int | float:
    return int(value) if value.is_integer() else value


def parse_task_requirements(text: str) -> dict[str, Any]:
    """Parse one natural-language request into the frozen Stage 8 contract.

    The returned value is composed only of JSON-compatible Python types.
    Matching order and output ordering are stable, so equal input always gives
    equal output.
    """

    if not isinstance(text, str):
        raise TypeError("text must be a string")

    normalized: dict[str, Any] = {}
    hard: dict[str, Any] = {}
    soft: list[dict[str, Any]] = []
    questions: list[str] = []
    unsupported: list[dict[str, Any]] = []
    evidence: dict[str, list[dict[str, Any]]] = {}
    claimed: list[tuple[int, int]] = []

    def overlaps(match: re.Match[str]) -> bool:
        return any(match.start() < end and start < match.end() for start, end in claimed)

    def record(field: str, value: Any, match: re.Match[str], *, is_hard: bool = True) -> None:
        normalized[field] = value
        if is_hard:
            hard[field] = value
        evidence.setdefault(field, []).append({
            "text": match.group(0), "start": match.start(), "end": match.end()
        })
        claimed.append((match.start(), match.end()))

    def record_nonnegative(field: str, value: float, match: re.Match[str], label: str) -> bool:
        """Record a nonnegative quantity or request correction of a negative one."""
        if value < 0:
            questions.append(f"“{match.group(0)}”中的{label}不能为负数，请提供大于或等于 0 的值。")
            claimed.append((match.start(), match.end()))
            return False
        record(field, _clean_number(value), match)
        return True

    def first(pattern: str, flags: int = re.IGNORECASE) -> re.Match[str] | None:
        return re.search(pattern, text, flags)

    # Weight semantics are intentionally separate and ordered from explicit to
    # ambiguous.  No missing installation margin is synthesized.
    match = first(rf"(?:携带|运输|搭载)\s*(?:的)?\s*(?:任务)?\s*净载荷\s*(?:为|是|约|不少于|至少)?\s*{_MASS}")
    if match:
        record_nonnegative("task_payload_requirement_kg", _mass_kg(match["value"], match["unit"]), match, "任务净载荷")
    else:
        match = first(rf"任务\s*净载荷\s*(?:为|是|约|不少于|至少)?\s*{_MASS}")
        if match:
            record_nonnegative("task_payload_requirement_kg", _mass_kg(match["value"], match["unit"]), match, "任务净载荷")

    match = first(rf"(?:整套|整机|总挂载(?:重量)?|整套挂载(?:重量)?)\s*(?:重量)?\s*(?:不超过|不得超过|至多|上限(?:为|是)?)\s*{_MASS}")
    if match:
        record_nonnegative("max_total_mounted_weight_kg", _mass_kg(match["value"], match["unit"]), match, "总挂载重量上限")

    match = first(rf"(?:安装|支架|线缆|挂载)\s*(?:重量)?\s*(?:余量|预留)\s*(?:为|是|约)?\s*{_MASS}")
    if not match:
        match = first(rf"(?:预留)\s*{_MASS}\s*(?:的)?\s*(?:安装|支架|线缆|挂载)(?:重量|余量)?")
    if match:
        record_nonnegative("installation_margin_kg", _mass_kg(match["value"], match["unit"]), match, "安装余量")

    # A bare payload quantity is unsafe only if it was not consumed by one of
    # the explicit payload meanings above.
    for match in re.finditer(rf"(?<!净)载荷\s*(?:为|是|约|不少于|至少|不超过|不得超过|至多)?\s*{_MASS}", text, re.IGNORECASE):
        if not overlaps(match):
            questions.append(
                f"请确认“{match.group(0)}”指任务净载荷、总挂载重量，还是无人机最大有效载荷。"
            )
            claimed.append((match.start(), match.end()))

    # Numeric endurance is hard; non-numeric comparative language is soft.
    match = first(rf"(?:至少|不得低于|不低于|最低)?\s*续航\s*(?:时间)?\s*(?:至少|不得低于|不低于|为|是|约)?\s*{_DURATION}")
    if match:
        record_nonnegative("min_endurance_min", _duration_min(match["value"], match["unit"]), match, "续航时长")
    match = first(r"(?:优先续航长|续航越长越好|优先选择续航(?:更)?长(?:的)?|长续航优先)")
    if match:
        item = {"field": "prefer_longer_endurance", "value": True}
        soft.append(item)
        evidence.setdefault("prefer_longer_endurance", []).append({"text": match.group(0), "start": match.start(), "end": match.end()})

    # Budget scope is retained even when the present Stage 7 R02 cannot apply
    # a local budget.
    match = first(rf"(?:(?P<scope>传感器|无人机|计算平台|整套(?:方案)?)\s*)?预算\s*(?:为|是|约|不超过|不得超过|至多)?\s*{_MONEY}")
    if match:
        scopes = {"传感器": "sensors_only", "无人机": "drone_only", "计算平台": "computer_only"}
        scope = scopes.get(match["scope"], "complete_solution")
        valid_budget = record_nonnegative("max_budget_cny", _money_cny(match["value"], match["unit"]), match, "预算")
        if valid_budget:
            normalized["budget_scope"] = scope
            hard["budget_scope"] = scope
            evidence["budget_scope"] = list(evidence["max_budget_cny"])
        if valid_budget and scope != "complete_solution":
            unsupported.append({
                "field": "max_budget_cny", "original_text": match.group(0),
                "reason": "当前阶段 7 R02 不支持局部预算范围。",
                "participated_in_validation": False, "is_hard_constraint": True,
            })

    # Temperature ranges and one-sided explicit bounds.
    range_match = first(rf"(?:工作|环境|任务)?\s*温度\s*(?:范围)?\s*(?:为|是|需在|介于)?\s*(?P<low>{_NUMBER})\s*(?:°\s*C|℃|摄氏度|度)?\s*(?:至|到|~|～|—|-)\s*(?P<high>{_NUMBER})\s*(?:°\s*C|℃|摄氏度|度)")
    if range_match:
        record("temperature_min_c", _clean_number(float(range_match["low"])), range_match)
        normalized["temperature_max_c"] = _clean_number(float(range_match["high"]))
        hard["temperature_max_c"] = normalized["temperature_max_c"]
        evidence["temperature_max_c"] = list(evidence["temperature_min_c"])
    else:
        low_match = first(rf"(?:最低|最小)\s*(?:工作|环境|任务)?\s*温度\s*(?:为|是|不得高于|不高于)?\s*{_TEMP}")
        high_match = first(rf"(?:最高|最大)\s*(?:工作|环境|任务)?\s*温度\s*(?:为|是|不得低于|不低于)?\s*{_TEMP}")
        if low_match:
            record("temperature_min_c", _clean_number(float(low_match["value"])), low_match)
        if high_match:
            record("temperature_max_c", _clean_number(float(high_match["value"])), high_match)

    match = first(r"(?:至少|不低于|防护等级(?:要求)?(?:为|是)?\s*)?(?P<rating>IP\s*\d{2})", re.IGNORECASE)
    if match:
        record("protection_rating", re.sub(r"\s+", "", match["rating"]).upper(), match)
        requirement_boundary = re.compile(r"并且|同时|且|[，,；;。\n]")
        preceding_boundaries = list(requirement_boundary.finditer(text, 0, match.start()))
        clause_start = preceding_boundaries[-1].end() if preceding_boundaries else 0
        following_boundary = requirement_boundary.search(text, match.end())
        clause_end = following_boundary.start() if following_boundary else len(text)
        clause = text[clause_start:clause_end]
        if re.search(r"(?:整套系统|整套设备|全部设备|所有设备)", clause):
            scope = "all_devices"
            specified_types: list[str] = []
        else:
            device_terms = (
                ("drone", r"无人机|飞行平台"),
                ("sensor", r"传感器|相机|雷达"),
                ("computer", r"计算平台|计算机|工控机|边缘计算"),
            )
            specified_types = [device_type for device_type, pattern in device_terms if re.search(pattern, clause)]
            scope = "specified_devices" if specified_types else "exposed_devices"
        normalized["protection_scope"] = scope
        hard["protection_scope"] = scope
        evidence["protection_scope"] = list(evidence["protection_rating"])
        normalized["specified_protected_device_types"] = specified_types
        hard["specified_protected_device_types"] = specified_types
        evidence["specified_protected_device_types"] = list(evidence["protection_rating"])

    # Interfaces use conservative, explicit vocabularies.
    interface_aliases = {
        "USB3": ("USB3", "USB 3", "USB3.0", "USB 3.0"),
        "USBC": ("USB-C", "TYPE-C", "Type-C"),
        "ETHERNET": ("千兆网", "以太网", "Ethernet", "GigE", "RJ45"),
        "GMSL2": ("GMSL2",), "CAN": ("CAN",), "UART": ("UART",),
        "MIPI": ("MIPI",), "CSI": ("CSI",), "PCIE": ("PCIe",),
        "RS232": ("RS232", "RS-232"), "RS485": ("RS485", "RS-485"),
    }
    data_context = first(r"(?:数据接口|通信接口|直连接口|接口要求)[^。；;\n]*")
    if data_context:
        upper = data_context.group(0).upper()
        interfaces = [canonical for canonical, aliases in interface_aliases.items() if any(alias.upper() in upper for alias in aliases)]
        if interfaces:
            record("required_data_interfaces", interfaces, data_context)

    mech_match = first(r"(?:机械接口|安装接口|挂载接口|云台接口|通用安装板)[^。；，,]*")
    if mech_match:
        record("required_mechanical_interfaces", [mech_match.group(0).strip()], mech_match)

    match = first(r"(?:允许|可以|可)\s*(?:使用)?\s*(?:接口)?转接(?:器|头|线)?")
    if match:
        record("adapter_allowed", True, match)
    else:
        match = first(r"(?:不允许|禁止|不得|不能|无需)\s*(?:使用)?\s*(?:接口)?转接(?:器|头|线)?|必须\s*直连")
        if match:
            record("adapter_allowed", False, match)

    # Software requirements are independently extracted.
    os_match = first(r"(?:操作系统|系统|OS)\s*(?:要求)?\s*(?:为|是|需(?:要)?|支持)?\s*(?P<os>Ubuntu(?:\s*\d+(?:\.\d+)?)?|Linux|Windows(?:\s*\d+)?|Android)", re.IGNORECASE)
    if os_match:
        record("required_os", [os_match["os"]], os_match)

    ros_match = first(r"(?:要求|需要|支持|兼容|必须)?\s*(?P<ros>ROS\s*2(?:\s+[A-Za-z]+)?|ROS2(?:\s+[A-Za-z]+)?|ROS\s*1|ROS1)(?:\s*(?:版本|环境))?", re.IGNORECASE)
    if ros_match:
        record("required_ros", [re.sub(r"ROS\s*2", "ROS2", ros_match["ros"], flags=re.IGNORECASE)], ros_match)

    cpu_match = first(r"(?:CPU\s*(?:架构)?|处理器架构|架构)\s*(?:要求)?\s*(?:为|是|需(?:要)?|支持)?\s*(?P<arch>ARM64|AARCH64|ARM|X86_64|X64|X86|AMD64)", re.IGNORECASE)
    if cpu_match:
        aliases = {"AARCH64": "ARM64", "X64": "X86_64", "AMD64": "X86_64"}
        arch = aliases.get(cpu_match["arch"].upper(), cpu_match["arch"].upper())
        record("required_cpu_arch", [arch], cpu_match)

    sdk_match = first(r"(?:要求|需要|必须|支持)\s*(?P<sdk>[^。；，,]{0,30}?(?:驱动|SDK))(?=$|[。；，,])", re.IGNORECASE)
    if sdk_match:
        record("required_driver_sdk", [sdk_match["sdk"].strip()], sdk_match)

    # Preserve explicit capability requests not covered by the first release.
    supported_terms = "续航|载荷|预算|温度|防护|接口|转接|操作系统|系统|ROS|CPU|架构|驱动|SDK"
    for match in re.finditer(r"(?:要求|需要|必须具备|应具备)\s*(?P<capability>[^。；，,]{1,40}?(?:能力|功能))(?=$|[。；，,])", text):
        if re.search(supported_terms, match["capability"], re.IGNORECASE):
            continue
        unsupported.append({
            "field": None, "original_text": match.group(0),
            "reason": "第一批标准字段和规则尚不支持该能力要求。",
            "participated_in_validation": False, "is_hard_constraint": True,
        })

    # De-duplicate clarification questions and unsupported entries while
    # retaining deterministic encounter order.
    questions = list(dict.fromkeys(questions))
    unique_unsupported: list[dict[str, Any]] = []
    seen_unsupported: set[tuple[Any, ...]] = set()
    for item in unsupported:
        key = (item["field"], item["original_text"], item["reason"])
        if key not in seen_unsupported:
            seen_unsupported.add(key)
            unique_unsupported.append(item)

    needs_clarification = bool(questions)
    if needs_clarification:
        status = "needs_clarification"
    elif unique_unsupported:
        # An explicit unsupported hard constraint prevents this request from
        # being considered ready even when other fields were parsed.
        status = "not_evaluated"
    elif hard:
        status = "ready"
    else:
        status = "not_evaluated"

    return {
        "raw_text": text,
        "normalized_constraints": normalized,
        "hard_constraints": hard,
        "soft_preferences": soft,
        "needs_clarification": needs_clarification,
        "clarification_questions": questions,
        "unsupported_constraints": unique_unsupported,
        "field_evidence": evidence,
        "request_status": status,
    }


__all__ = ["parse_task_requirements"]
