# rules_engine.py
import re
import math

def is_empty(val):
    """严格判断空值，包括 None, '' 和 NaN"""
    if val is None:
        return True
    if isinstance(val, float) and math.isnan(val):
        return True
    if str(val).strip() in ('', 'nan', 'None', 'NaN'):
        return True
    return False

def get_num(data, key):
    """安全读取数值，空值或异常返回 None"""
    val = data.get(key)
    if is_empty(val):
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None

def evaluate_rule(rule_id, combo_data, enabled_rules):
    """评估单条规则，返回 'pass' / 'fail' / 'manual_review' / 'not_applicable'"""
    if rule_id not in enabled_rules:
        return 'not_applicable'

    uav = combo_data.get('uav', {})
    sensor = combo_data.get('sensor', {})
    computer = combo_data.get('computer', {})
    requirements = combo_data.get('requirements', {})

    if rule_id == 'R01': # 载荷要求
        uav_max = get_num(uav, '最大有效载荷(kg)')
        sensor_weight = get_num(sensor, '重量(kg)')
        comp_weight = get_num(computer, '重量(kg)')
        task_payload = get_num(requirements, '任务载荷/安装余量(kg)')
        
        # 缺失任何重量参数，转人工
        if None in (uav_max, sensor_weight, comp_weight, task_payload):
            return 'manual_review'
        
        total_weight = sensor_weight + comp_weight + task_payload
        if total_weight > uav_max:
            return 'fail'
        return 'pass'

    if rule_id == 'R02': # 预算要求
        # 成员一强调：R02支持率为0，无人民币官方价格必须转人工，绝不能自己按汇率换算
        return 'manual_review'

    if rule_id == 'R05': # 接口匹配
        required_interface = str(requirements.get('必需接口', '')).strip()
        # 如果任务未指定接口，规则不适用
        if not required_interface or required_interface == 'nan':
            return 'not_applicable'
        
        # 提取核心关键词（例如：从 'GMSL2直连' 提取 'GMSL2'）
        keyword = re.sub(r'[^A-Za-z0-9]', '', required_interface).upper()
        if not keyword:
            keyword = required_interface.upper()
            
        comp_has_keyword = False
        comp_has_any_interface = False
        for k, v in computer.items():
            if not is_empty(v) and ('接口' in str(k) or 'USB' in str(k) or 'UART' in str(k) or 'GPIO' in str(k) or '网' in str(k)):
                comp_has_any_interface = True
                if keyword in str(v).upper():
                    comp_has_keyword = True
                    
        sensor_has_keyword = False
        sensor_has_any_interface = False
        for k, v in sensor.items():
            if not is_empty(v) and '接口' in str(k):
                sensor_has_any_interface = True
                if keyword in str(v).upper():
                    sensor_has_keyword = True
                    
        # 【核心修复】传感器明确有接口，但计算平台缺少该接口，判定失败（针对 GC09）
        if sensor_has_keyword and not comp_has_keyword:
            return 'fail'
            
        if not comp_has_any_interface or not sensor_has_any_interface:
            return 'manual_review'
            
        if comp_has_keyword and sensor_has_keyword:
            return 'pass'
            
        return 'manual_review'

    if rule_id == 'R06': # 温度/防护要求
        uav_tmin = get_num(uav, '工作温度最低值(℃)')
        uav_tmax = get_num(uav, '工作温度最高值(℃)')
        req_tmin = get_num(requirements, '工作温度最低值(℃)')
        req_tmax = get_num(requirements, '工作温度最高值(℃)')
        
        if req_tmin is None and req_tmax is None:
            return 'pass'
            
        if uav_tmin is None or uav_tmax is None:
            return 'manual_review'
            
        if req_tmin is not None and uav_tmin > req_tmin:
            return 'fail'
        if req_tmax is not None and uav_tmax < req_tmax:
            return 'fail'
        return 'pass'

    if rule_id == 'R07': # ROS/软件支持
        ros_support = sensor.get('ROS支持')
        os_support = sensor.get('支持操作系统')
        if is_empty(ros_support) and is_empty(os_support):
            return 'manual_review'
        return 'pass'

    # 其他未实现规则（如 R03, R04），保守转人工
    return 'manual_review'

def evaluate_combo(combo_data, enabled_rules):
    """评估一套设备组合，执行所有启用规则并汇总总体状态。"""
    overall_status = 'pass'
    details = []
    
    for rule_id in ['R01', 'R02', 'R03', 'R04', 'R05', 'R06', 'R07']:
        status = evaluate_rule(rule_id, combo_data, enabled_rules)
        
        if status != 'not_applicable':
            details.append({'rule_id': rule_id, 'status': status})
            
        if status == 'fail':
            overall_status = 'fail'
        elif status == 'manual_review' and overall_status != 'fail':
            overall_status = 'manual_review'
            
    return overall_status, details