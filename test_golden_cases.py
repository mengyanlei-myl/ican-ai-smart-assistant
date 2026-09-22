# test_golden_cases.py
import pandas as pd
import os
import json
import sqlite3
import sys
sys.path.append(os.path.abspath(os.path.dirname(__file__)))
from rules_engine import evaluate_combo

V2_DIR = 'data/compatibility/v2'
GOLDEN_FILE = os.path.join(V2_DIR, 'golden_cases_v1.xlsx')
DB_PATH = 'data/low_altitude_selection.db'

def get_device_data(device_id):
    """从数据库 v2_compatibility 表中提取原始 JSON 数据"""
    if not device_id or pd.isna(device_id):
        return None
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT raw_data FROM v2_compatibility WHERE device_id = ?", (str(device_id).strip(),))
    row = cursor.fetchone()
    conn.close()
    if row:
        return json.loads(row[0])
    return None

def run_tests():
    if not os.path.exists(GOLDEN_FILE):
        print(f"找不到测试文件: {GOLDEN_FILE}")
        return
        
    df = pd.read_excel(GOLDEN_FILE)
    print(f"共加载 {len(df)} 个测试案例。\n")
    
    pass_count = 0
    fail_count = 0
    
    for idx, row in df.iterrows():
        case_id = row.get('案例ID', f'Case_{idx+1}')
        expected_status = str(row.get('预期总状态', '')).strip().lower()
        
        # 解析启用规则
        enabled_str = str(row.get('启用规则', ''))
        enabled_rules = [r.strip() for r in enabled_str.split(',') if r.strip()]
        
        # 获取三台设备的数据
        uav_id = row.get('预期无人机ID')
        sensor_id = row.get('预期传感器ID')
        comp_id = row.get('预期计算平台ID')
        
        uav_data = get_device_data(uav_id)
        sensor_data = get_device_data(sensor_id)
        comp_data = get_device_data(comp_id)
        
        # 组装 combo_data
        combo_data = {
            'uav': uav_data or {},
            'sensor': sensor_data or {},
            'computer': comp_data or {},
            'requirements': row.to_dict() # 把案例行本身作为需求字典传进去
        }
        
        # 调用规则引擎
        actual_status, details = evaluate_combo(combo_data, enabled_rules)
        
        if actual_status == expected_status:
            pass_count += 1
            print(f"✅ {case_id} ({row.get('场景名称')}): 预期 [{expected_status}], 实际 [{actual_status}] (通过)")
        else:
            fail_count += 1
            print(f"❌ {case_id} ({row.get('场景名称')}): 预期 [{expected_status}], 实际 [{actual_status}] (失败)")
            print(f"   启用规则: {enabled_rules}")
            print(f"   详细结果: {details}")
            print(f"   预期失败规则: {row.get('预期失败规则')}")
            print(f"   预期人工复核规则: {row.get('预期人工复核规则')}")
            print()

    print(f"\n{'='*20} 测试结果 {'='*20}")
    print(f"总计: 通过 {pass_count}，失败 {fail_count}")
    print(f"{'='*48}")

if __name__ == '__main__':
    run_tests()