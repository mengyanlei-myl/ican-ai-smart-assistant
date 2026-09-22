# tests/test_golden_cases.py
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import pandas as pd
import json
import sqlite3
from rules_engine import evaluate_combo

V2_DIR = 'data/compatibility/v2'
GOLDEN_FILE = os.path.join(V2_DIR, 'golden_cases_v1.xlsx')
DB_PATH = 'data/low_altitude_selection.db'

def get_device_data(device_id):
    if not device_id or pd.isna(device_id):
        return None
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT raw_data FROM v2_compatibility WHERE device_id = ?", (str(device_id).strip(),))
    row = cursor.fetchone()
    conn.close()
    return json.loads(row[0]) if row else None

def run_tests():
    df = pd.read_excel(GOLDEN_FILE)
    pass_count = 0
    fail_count = 0
    for idx, row in df.iterrows():
        case_id = row.get('案例ID', f'Case_{idx+1}')
        expected_status = str(row.get('预期总状态', '')).strip().lower()
        enabled_str = str(row.get('启用规则', ''))
        enabled_rules = [r.strip() for r in enabled_str.split(',') if r.strip()]
        
        combo_data = {
            'uav': get_device_data(row.get('预期无人机ID')) or {},
            'sensor': get_device_data(row.get('预期传感器ID')) or {},
            'computer': get_device_data(row.get('预期计算平台ID')) or {},
            'requirements': row.to_dict()
        }
        
        actual_status, details = evaluate_combo(combo_data, enabled_rules)
        
        if actual_status == expected_status:
            pass_count += 1
            print(f"✅ {case_id}: 预期 [{expected_status}], 实际 [{actual_status}]")
        else:
            fail_count += 1
            print(f"❌ {case_id}: 预期 [{expected_status}], 实际 [{actual_status}]")
            
    print(f"\n测试结果: 通过 {pass_count}，失败 {fail_count}")

if __name__ == '__main__':
    run_tests()