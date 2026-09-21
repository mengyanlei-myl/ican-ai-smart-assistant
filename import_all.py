import pandas as pd
import sqlite3
import re
import os

DB_PATH = 'data/low_altitude_selection.db'

UAV_FILE = 'data/uav_model_database.xlsx'
SENSOR_FILE = 'data/sensor_model_database.xlsx'
COMPUTER_FILE = 'data/compute_platform_database.xlsx'

def create_tables(conn):
    cursor = conn.cursor()
    cursor.executescript('''
        CREATE TABLE IF NOT EXISTS drones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            brand TEXT,
            model TEXT,
            max_payload REAL,
            endurance REAL,
            weight REAL,
            flight_range REAL,
            price REAL,
            power REAL,
            voltage TEXT,
            working_temperature TEXT,
            protection_level TEXT,
            source_url TEXT,
            update_date TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS sensors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT,
            brand TEXT,
            model TEXT,
            functions TEXT,
            detection_range REAL,
            accuracy TEXT,
            weight REAL,
            power REAL,
            voltage TEXT,
            interfaces TEXT,
            working_temperature TEXT,
            protection_level TEXT,
            price REAL,
            source_url TEXT,
            update_date TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS computers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            brand TEXT,
            model TEXT,
            cpu TEXT,
            ram REAL,
            storage REAL,
            weight REAL,
            power REAL,
            voltage TEXT,
            interfaces TEXT,
            working_temperature TEXT,
            protection_level TEXT,
            price REAL,
            source_url TEXT,
            update_date TIMESTAMP
        );
    ''')
    conn.commit()

def clean(col):
    if not isinstance(col, str):
        return col
    col = col.strip()
    col = col.replace('（', '(').replace('）', ')')
    col = re.sub(r'[\u200b\u200c\u200d\ufeff]', '', col)
    return col

def convert(value, target_unit):
    if pd.isna(value) or value == '':
        return None
    s = str(value).strip()
    m = re.match(r'([\d.]+)\s*([a-zA-Zμµ]+)?', s)
    if not m:
        try:
            return float(s)
        except:
            return None
    num = float(m.group(1))
    unit = (m.group(2) or '').lower()
    if target_unit == 'kg':
        if unit in ['g', 'gram']:
            return num / 1000
        elif unit in ['lb', 'lbs']:
            return num * 0.453592
        else:
            return num
    elif target_unit == 'rmb':
        if unit in ['usd', '$']:
            return num * 7
        else:
            return num
    elif target_unit == 'w':
        if unit in ['mw', 'milliwatt']:
            return num / 1000
        else:
            return num
    else:
        return num

def process_table(conn, table_name, file_path, mapping, conversions, required, merge_rules=None):
    """
    mapping: {目标列: 原始列名}
    conversions: {目标列: 目标单位}
    required: [必填目标列]
    merge_rules: {目标列: [原始列1, 原始列2]} 用于合并多个列的内容
    """
    if not os.path.exists(file_path):
        return 0, 0, f"文件不存在 {file_path}"

    df = pd.read_excel(file_path)
    if df.empty:
        return 0, 0, "文件为空"

    df.columns = [clean(c) for c in df.columns]

    if merge_rules:
        for target, src_cols in merge_rules.items():
            exist_cols = [c for c in src_cols if c in df.columns]
            if exist_cols:
                df[target] = df[exist_cols].apply(
                    lambda row: '; '.join([str(x) for x in row if pd.notna(x) and str(x).strip() != '']),
                    axis=1
                )

    rename = {}
    for target, src in mapping.items():
        if src in df.columns:
            rename[src] = target

    if not rename:
        return 0, 0, "无匹配列"

    df = df.rename(columns=rename)

    keep_cols = list(rename.values())
    if merge_rules:
        for target in merge_rules.keys():
            if target not in keep_cols and target in df.columns:
                keep_cols.append(target)
    keep_cols = list(dict.fromkeys(keep_cols))
    df = df[[c for c in keep_cols if c in df.columns]]

    missing = [f for f in required if f not in df.columns]
    if missing:
        return 0, 0, f"缺少必填列 {missing}"

    cursor = conn.cursor()
    cursor.execute(f"DELETE FROM {table_name}")
    conn.commit()

    success = 0
    fail = 0
    for idx, row in df.iterrows():
        try:
            for f in required:
                if pd.isna(row[f]) or str(row[f]).strip() == '':
                    raise ValueError(f"必填字段 {f} 为空")

            data = {}
            for col in df.columns:
                if col in conversions:
                    data[col] = convert(row[col], conversions[col])
                else:
                    data[col] = None if pd.isna(row[col]) else row[col]

            cols = ', '.join(data.keys())
            placeholders = ', '.join(['?'] * len(data))
            values = list(data.values())
            cursor.execute(f"INSERT INTO {table_name} ({cols}) VALUES ({placeholders})", values)
            success += 1
        except Exception as e:
            fail += 1
    conn.commit()
    return success, fail, ""

def import_all():
    for f in [UAV_FILE, SENSOR_FILE, COMPUTER_FILE]:
        if not os.path.exists(f):
            print(f"错误：文件 {f} 不存在")
            return

    conn = sqlite3.connect(DB_PATH)
    create_tables(conn)

    uav_mapping = {
        'brand': '厂家',
        'model': '型号',
        'max_payload': '最大起飞重量(kg)',
        'flight_range': '最大航程(km)',
        'working_temperature': '工作温度(°C)',
        'protection_level': '防护等级',
        'source_url': '官方链接',
    }
    uav_conversions = {
        'max_payload': 'kg',
        'price': 'rmb',
        'power': 'w'
    }
    uav_required = ['brand', 'model']

    sensor_mapping = {
        'category': '传感器子类',
        'brand': '厂家',
        'model': '型号',
        'functions': '完整名称',
        'detection_range': '探测距离/量程(m)',
        'accuracy': '精度',
        'weight': '单位(g)',
        'power': '功耗(W)',
        'interfaces': '接口',
        'working_temperature': '工作温度',
        'protection_level': '防护等级',
        'price': '价格参考',
        'source_url': '官方链接',
    }
    sensor_conversions = {
        'weight': 'kg',
        'price': 'rmb',
        'power': 'w',
        'detection_range': 'm'
    }
    sensor_required = ['category', 'brand', 'model']

    computer_mapping = {
        'brand': '厂家',
        'model': '型号',
        'ram': '内存',
        'storage': '核载存储',
        'power': '功耗/功耗模式(W)',
        'weight': '重量(g)',
        'voltage': '供电要求',
        'working_temperature': '工作温度(°C)',
        'price': '官方价格/采购状态',
        'source_url': '官方链接',
    }

    computer_merge = {
        'cpu': ['GPU/NPU/FPGA', 'CPU'], 
        'interfaces': ['USB/网络', 'UART/CAN/GPIO']
    }
    computer_conversions = {
        'weight': 'kg',
        'price': 'rmb',
        'power': 'w'
    }
    computer_required = ['brand', 'model']


    total_success = 0
    total_fail = 0
    errors = []

    s, f, err = process_table(conn, 'drones', UAV_FILE, uav_mapping, uav_conversions, uav_required)
    total_success += s
    total_fail += f
    if err:
        errors.append(f"无人机: {err}")

    s, f, err = process_table(conn, 'sensors', SENSOR_FILE, sensor_mapping, sensor_conversions, sensor_required)
    total_success += s
    total_fail += f
    if err:
        errors.append(f"传感器: {err}")

    s, f, err = process_table(conn, 'computers', COMPUTER_FILE, computer_mapping, computer_conversions, computer_required, computer_merge)
    total_success += s
    total_fail += f
    if err:
        errors.append(f"计算机: {err}")

    conn.close()

    if errors:
        print("导入完成！成功 {} 条，失败 {} 条。警告: {}".format(total_success, total_fail, '; '.join(errors)))
    else:
        print(f"导入完成！成功 {total_success} 条，失败 {total_fail} 条。")

if __name__ == '__main__':
    import_all()