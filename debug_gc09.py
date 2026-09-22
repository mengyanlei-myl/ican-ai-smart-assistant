# debug_gc09.py
import pandas as pd
import json
import sqlite3
import os

V2_DIR = 'data/compatibility/v2'
GOLDEN_FILE = os.path.join(V2_DIR, 'golden_cases_v1.xlsx')
DB_PATH = 'data/low_altitude_selection.db'

def debug_gc09():
    df = pd.read_excel(GOLDEN_FILE)
    gc09 = df[df['案例ID'] == 'GC09'].iloc[0]
    
    print("=== GC09 测试用例原始信息 ===")
    print(f"场景: {gc09.get('场景名称')}")
    print(f"预期总状态: {gc09.get('预期总状态')}")
    print(f"预期失败规则: {gc09.get('预期失败规则')}")
    print(f"预期原因: {gc09.get('预期原因')}")
    print(f"备注: {gc09.get('备注')}")
    print(f"任务需求: {gc09.to_dict()}")
    
    uav_id = gc09.get('预期无人机ID')
    sensor_id = gc09.get('预期传感器ID')
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    print(f"\n=== 设备数据库信息 ===")
    for label, dev_id in [("无人机", uav_id), ("传感器", sensor_id)]:
        if pd.notna(dev_id):
            cursor.execute("SELECT raw_data FROM v2_compatibility WHERE device_id = ?", (dev_id,))
            row = cursor.fetchone()
            if row:
                data = json.loads(row[0])
                print(f"\n【{label} {dev_id}】")
                print(f"  安装/挂载接口: {data.get('安装/挂载接口')}")
                print(f"  数据接口: {data.get('数据接口')}")
                print(f"  飞控扩展接口: {data.get('飞控扩展接口')}")
                print(f"  是否允许第三方载荷: {data.get('是否允许第三方载荷')}")
            else:
                print(f"\n【{label} {dev_id}】未找到数据库记录")
    conn.close()

if __name__ == '__main__':
    debug_gc09()