import pytest

from semantic_parser import parse_task_requirements


def constraints(text):
    return parse_task_requirements(text)["normalized_constraints"]


@pytest.mark.parametrize("text,field,expected", [
    ("任务净载荷 2kg", "task_payload_requirement_kg", 2),
    ("携带净载荷 500克", "task_payload_requirement_kg", 0.5),
    ("整套不超过 3000g", "max_total_mounted_weight_kg", 3),
    ("安装余量 250克", "installation_margin_kg", 0.25),
])
def test_mass_fields_and_kg_conversion(text, field, expected):
    result = parse_task_requirements(text)
    assert result["request_status"] == "ready"
    assert result["hard_constraints"][field] == expected
    assert result["field_evidence"][field][0]["text"]


def test_bare_payload_is_ambiguous_and_not_mapped():
    result = parse_task_requirements("载荷 2kg")
    assert result["request_status"] == "needs_clarification"
    assert result["needs_clarification"] is True
    assert result["clarification_questions"]
    assert "task_payload_requirement_kg" not in result["normalized_constraints"]
    assert "max_total_mounted_weight_kg" not in result["normalized_constraints"]


@pytest.mark.parametrize("qualifier", ["不少于", "至少", "不超过", "至多"])
def test_qualified_bare_payload_is_still_ambiguous(qualifier):
    result = parse_task_requirements(f"载荷{qualifier}2kg")
    assert result["request_status"] == "needs_clarification"
    assert result["clarification_questions"]
    assert result["normalized_constraints"] == {}


@pytest.mark.parametrize("text,expected", [
    ("续航 30 分钟", 30),
    ("至少续航 2 小时", 120),
])
def test_hard_endurance_and_time_conversion(text, expected):
    result = parse_task_requirements(text)
    assert result["hard_constraints"]["min_endurance_min"] == expected


def test_endurance_preference_is_soft_only():
    result = parse_task_requirements("优先续航长")
    assert result["request_status"] == "not_evaluated"
    assert result["hard_constraints"] == {}
    assert result["soft_preferences"] == [{"field": "prefer_longer_endurance", "value": True}]


@pytest.mark.parametrize("text,amount,scope,unsupported", [
    ("预算 10000 元", 10000, "complete_solution", False),
    ("整套方案预算 10 万元", 100000, "complete_solution", False),
    ("传感器预算 2 万元", 20000, "sensors_only", True),
])
def test_budget_units_and_scope(text, amount, scope, unsupported):
    result = parse_task_requirements(text)
    assert result["hard_constraints"]["max_budget_cny"] == amount
    assert result["hard_constraints"]["budget_scope"] == scope
    assert bool(result["unsupported_constraints"]) is unsupported


def test_temperature_range_and_protection_are_separate():
    result = parse_task_requirements("工作温度 -20℃ 到 50℃，防护等级至少 IP54")
    assert result["hard_constraints"]["temperature_min_c"] == -20
    assert result["hard_constraints"]["temperature_max_c"] == 50
    assert result["hard_constraints"]["protection_rating"] == "IP54"
    assert "temperature_min_c" in result["field_evidence"]
    assert "protection_rating" in result["field_evidence"]


@pytest.mark.parametrize("text,scope,device_types", [
    ("需要 IP67", "exposed_devices", []),
    ("整套系统 IP67", "all_devices", []),
    ("无人机和传感器 IP67", "specified_devices", ["drone", "sensor"]),
])
def test_protection_scope_and_device_types(text, scope, device_types):
    result = parse_task_requirements(text)
    hard = result["hard_constraints"]
    assert hard["protection_rating"] == "IP67"
    assert hard["protection_scope"] == scope
    assert hard["specified_protected_device_types"] == device_types


def test_protection_device_types_have_fixed_order_and_no_duplicates():
    result = parse_task_requirements("传感器、无人机、相机和计算平台 IP54")
    assert result["hard_constraints"]["specified_protected_device_types"] == [
        "drone", "sensor", "computer"
    ]


def test_protection_scope_after_ip_rating_is_preserved():
    result = parse_task_requirements("IP67 防护要求适用于无人机和传感器")
    hard = result["hard_constraints"]
    assert hard["protection_scope"] == "specified_devices"
    assert hard["specified_protected_device_types"] == ["drone", "sensor"]


def test_protection_scope_does_not_capture_device_from_previous_requirement():
    result = parse_task_requirements("无人机续航至少30分钟，传感器 IP67")
    hard = result["hard_constraints"]
    assert hard["protection_scope"] == "specified_devices"
    assert hard["specified_protected_device_types"] == ["sensor"]


@pytest.mark.parametrize("connector", ["且", "并且", "同时"])
def test_protection_scope_stops_at_requirement_conjunction(connector):
    result = parse_task_requirements(f"无人机续航至少30分钟{connector}传感器需IP67")
    hard = result["hard_constraints"]
    assert hard["protection_scope"] == "specified_devices"
    assert hard["specified_protected_device_types"] == ["sensor"]


def test_protection_scope_keeps_device_enumeration_conjunction():
    result = parse_task_requirements("无人机和传感器均需IP67")
    hard = result["hard_constraints"]
    assert hard["protection_scope"] == "specified_devices"
    assert hard["specified_protected_device_types"] == ["drone", "sensor"]


def test_data_and_mechanical_interfaces_are_separate():
    result = parse_task_requirements("数据接口要求 USB3 和千兆网，机械接口使用通用安装板")
    assert result["hard_constraints"]["required_data_interfaces"] == ["USB3", "ETHERNET"]
    assert result["hard_constraints"]["required_mechanical_interfaces"] == ["机械接口使用通用安装板"]


@pytest.mark.parametrize("separator", ["，", ",", "、"])
def test_data_interface_lists_accept_common_separators(separator):
    result = parse_task_requirements(f"数据接口要求 USB3{separator}千兆网口{separator}USB3")
    assert result["hard_constraints"]["required_data_interfaces"] == ["USB3", "ETHERNET"]


@pytest.mark.parametrize("text,forbidden_field", [
    ("任务净载荷 -2kg", "task_payload_requirement_kg"),
    ("整套不超过 -3kg", "max_total_mounted_weight_kg"),
    ("安装余量 -500克", "installation_margin_kg"),
    ("续航 -30 分钟", "min_endurance_min"),
    ("预算 -1 万元", "max_budget_cny"),
])
def test_negative_nonnegative_quantities_need_clarification(text, forbidden_field):
    result = parse_task_requirements(text)
    assert result["request_status"] == "needs_clarification"
    assert result["needs_clarification"] is True
    assert "不能为负数" in result["clarification_questions"][0]
    assert forbidden_field not in result["normalized_constraints"]
    assert forbidden_field not in result["hard_constraints"]


def test_negative_temperatures_remain_valid():
    result = parse_task_requirements("工作温度 -30℃ 到 -5℃")
    assert result["request_status"] == "ready"
    assert result["hard_constraints"]["temperature_min_c"] == -30
    assert result["hard_constraints"]["temperature_max_c"] == -5


@pytest.mark.parametrize("text,expected", [
    ("允许使用转接器", True),
    ("禁止使用转接器", False),
    ("必须直连", False),
])
def test_adapter_policy(text, expected):
    assert constraints(text)["adapter_allowed"] is expected


def test_software_requirements_are_independent():
    result = parse_task_requirements(
        "操作系统要求 Ubuntu 22.04，支持 ROS2 Humble，CPU 架构 ARM64，需要官方 Linux SDK"
    )
    hard = result["hard_constraints"]
    assert hard["required_os"] == ["Ubuntu 22.04"]
    assert hard["required_ros"] == ["ROS2 Humble"]
    assert hard["required_cpu_arch"] == ["ARM64"]
    assert hard["required_driver_sdk"] == ["官方 Linux SDK"]


def test_unknown_explicit_capability_is_unsupported():
    result = parse_task_requirements("需要夜间自主避障能力")
    assert result["request_status"] == "not_evaluated"
    assert result["unsupported_constraints"][0]["original_text"] == "需要夜间自主避障能力"
    assert result["unsupported_constraints"][0]["is_hard_constraint"] is True
    assert result["unsupported_constraints"][0]["participated_in_validation"] is False


def test_supported_fields_do_not_hide_unsupported_hard_constraint():
    result = parse_task_requirements("预算 10 万元，需要夜间自主避障能力")
    assert result["hard_constraints"]["max_budget_cny"] == 100000
    assert result["unsupported_constraints"]
    assert result["request_status"] == "not_evaluated"


@pytest.mark.parametrize("text", ["", "   ", "优先续航长"])
def test_no_hard_constraint_is_not_evaluated(text):
    result = parse_task_requirements(text)
    assert result["request_status"] == "not_evaluated"
    assert result["needs_clarification"] is False


def test_installation_margin_is_never_defaulted():
    result = parse_task_requirements("携带净载荷 2kg")
    assert "installation_margin_kg" not in result["normalized_constraints"]


def test_equal_input_has_equal_output():
    text = "携带净载荷 500克，至少续航 2 小时，预算 10 万元，允许使用转接器"
    assert parse_task_requirements(text) == parse_task_requirements(text)


def test_output_contract_is_always_present():
    result = parse_task_requirements("")
    assert set(result) == {
        "raw_text", "normalized_constraints", "hard_constraints",
        "soft_preferences", "needs_clarification", "clarification_questions",
        "unsupported_constraints", "field_evidence", "request_status",
    }


def test_non_string_input_is_rejected():
    with pytest.raises(TypeError):
        parse_task_requirements(None)
