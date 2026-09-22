import pandas as pd
import requests
import sqlite3
import os

# ================= 配置区域 =================
DATA_DIR = "data"
EXCEL_FILES = {
    "无人机": os.path.join(DATA_DIR, "compatibility", "compatibility_specs_v1_completed.xlsx"),
    "传感器": os.path.join(DATA_DIR, "compatibility", "sensor_compatibility_specs_v1_corrected.xlsx"),
    "计算平台": os.path.join(DATA_DIR, "compatibility", "computer_compatibility_specs_v1_completed.xlsx")
}
DB_PATH = os.path.join(DATA_DIR, "low_altitude_selection.db")
API_BASE_URL = "http://127.0.0.1:5000/api"

TABLE_NAMES = {"无人机": "drones", "传感器": "sensors", "计算平台": "computers"}
EXCEL_ID_COLS = {"无人机": "无人机ID", "传感器": "传感器ID", "计算平台": "计算平台ID"}

# 【关键】ID别名映射，解决未匹配问题（后续开发正式接口也必须继续保留！）
ID_ALIASES = {
    "Parker_MicroStrain_3DM_GX5_25": "Parker_MicroStrain_3DM_GX5",
    "Ublox_ZED_F9P_04B": "Ublox_ZED_F9P"
}

# 【关键】严格按照要求修正的字段映射
FIELD_MAPPING = {
    "无人机": {
        "无人机ID": "device_id",
        "厂家": "brand",
        "型号": "model",
        "最大有效载荷(kg)": "max_payload",
        "工作温度最低值(℃)": "working_temperature",
        "防护等级": "protection_level",
        "参考价格(CNY)": "price"
        # 注：按要求，最大起飞重量(kg) 不映射为 max_payload
    },
    "传感器": {
        "传感器ID": "device_id",
        "厂家": "brand",
        "型号": "model",
        "类别": "category",
        "重量(kg)": "weight",
        "功耗(W)": "power",
        "数据接口": "interfaces",       # 要求3：数据接口映射
        "工作温度最低值(℃)": "working_temperature",
        "防护等级": "protection_level",
        "参考价格(CNY)": "price"
        # 要求5：彻底移除 驱动或SDK 映射
    },
    "计算平台": {
        "计算平台ID": "device_id",
        "厂家": "brand",
        "型号": "model",
        "CPU型号": "cpu",              # 要求4：增加 CPU型号
        "数据接口": "interfaces",      # <--- 新增：最新要求补上计算平台的接口映射
        "重量(kg)": "weight",
        "典型功耗(W)": "power",
        "内存": "ram",
        "存储": "storage",
        "参考价格(CNY)": "price"
        # 要求2：删除 类别->brand
        # 要求5：彻底移除 驱动或SDK 映射
    }
}

# 【要求6】兼容性专项字段检查列表
COMPATIBILITY_FIELDS = {
    "无人机": ["载荷输出电压最小值(V)", "载荷输出电压最大值(V)", "载荷最大输出功率(W)", "安装/挂载接口", "最大起飞重量(kg)"],
    "传感器": ["输入电压最小值(V)", "输入电压最大值(V)", "安装/挂载接口", "支持操作系统", "ROS支持", "驱动或SDK"],
    "计算平台": ["输入电压最小值(V)", "输入电压最大值(V)", "供电方式", "安装/挂载接口", "支持操作系统", "ROS支持", "驱动或SDK", "最大功耗(W)"]
}
# ===========================================

def get_db_columns(table_name):
    if not os.path.exists(DB_PATH):
        return set()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(f"PRAGMA table_info({table_name});")
    columns = [row[1] for row in cursor.fetchall()]
    conn.close()
    return set(columns)

def main():
    print("="*60)
    print("【兼容性最终文件只读检查报告】")
    print("="*60)

    api_data = {}
    for name, endpoint in [("无人机", "/drones"), ("传感器", "/sensors"), ("计算平台", "/computers")]:
        try:
            res = requests.get(API_BASE_URL + endpoint, timeout=5)
            if res.status_code == 200:
                data = res.json()
                api_data[name] = {str(item.get('device_id')) for item in data if isinstance(item, dict) and item.get('device_id') is not None}
        except Exception:
            api_data[name] = set()
            print(f"⚠️ 警告：无法连接API {endpoint}，请确认后端是否启动。")

    total_matched = 0

    for name, file_path in EXCEL_FILES.items():
        print(f"\n📁 正在检查 [{name}] 文件...")
        try:
            df = pd.read_excel(file_path, sheet_name=0)
            print(f"  - 读取主表成功，共 {len(df)} 条记录。")
            if len(df) != 5:
                print(f"  - ⚠️ 警告：记录数不是5条！")
        except Exception as e:
            print(f"  - ❌ 读取失败: {e}")
            continue

        id_col = EXCEL_ID_COLS.get(name)
        if id_col not in df.columns:
            print(f"  - ⚠️ 找不到ID列 '{id_col}'。")
            continue
            
        excel_ids = df[id_col].dropna().astype(str).tolist()
        print(f"  - 设备ID列表: {excel_ids}")

        # 应用别名映射比对
        print("  - 与API匹配结果:")
        api_ids = api_data.get(name, set())
        for eid in excel_ids:
            mapped_eid = ID_ALIASES.get(eid, eid)
            status = "✅ 匹配" if mapped_eid in api_ids else "❌ 未匹配"
            if mapped_eid in api_ids:
                total_matched += 1
            print(f"    * {eid} (映射为 {mapped_eid}): {status}")

        # 打印字段映射
        print("  - 完整字段映射 (Excel -> 数据库):")
        mapping = FIELD_MAPPING.get(name, {})
        for excel_col, db_col in mapping.items():
            if excel_col in df.columns:
                print(f"    * '{excel_col}' -> '{db_col}'")
            else:
                print(f"    * ⚠️ '{excel_col}' 在Excel中不存在")
        if name == "无人机":
            print("    * 注：已按修正要求，'最大起飞重量(kg)' 未映射为 max_payload。")

        # 空值与特殊值
        null_counts = df.isnull().sum()
        null_cols = null_counts[null_counts > 0]
        if len(null_cols) > 0:
            print("  - 空值检查: 发现空白单元格（读取为null，未转成0）：")
            for col, count in null_cols.items():
                print(f"    * '{col}': {count} 处空白")
        else:
            print("  - 空值检查: 未发现空白单元格。")

        supplement_found = False
        for col in df.columns:
            if df[col].dtype == 'object' or df[col].dtype == 'str':
                count = df[col].astype(str).str.contains('需要补充', na=False).sum()
                if count > 0:
                    print(f"  - '需要补充'检查: 列 '{col}' 保留 {count} 处。")
                    supplement_found = True
        if not supplement_found:
            print("  - '需要补充'检查: 未发现。")

        # 【要求6】兼容性专项字段读取方式检查
        print("  - 【要求6】兼容性专项字段读取方式检查:")
        table_name = TABLE_NAMES.get(name)
        db_cols = get_db_columns(table_name)
        target_fields = COMPATIBILITY_FIELDS.get(name, [])
        for field in target_fields:
            if field in df.columns:
                if field in mapping:
                    print(f"    * '{field}' -> 已映射到数据库字段 '{mapping[field]}'")
                else:
                    if field in db_cols:
                        print(f"    * '{field}' -> 数据库中有对应列，但未包含在主表映射中，需后续处理。")
                    else:
                        print(f"    * '{field}' -> ⚠️ 数据库无此字段，建议在后端/兼容性逻辑中直接从Excel数据读取或扩充模型。")

        # 数据库缺失字段
        print("  - 数据库缺失字段检查: 以下兼容性所需字段在数据库中不存在：")
        missing_fields = []
        for excel_col, db_col in mapping.items():
            if db_col not in db_cols and excel_col in df.columns:
                missing_fields.append(f"{excel_col} (映射为 {db_col})")
        if missing_fields:
            for f in missing_fields:
                print(f"    * {f}")
        else:
            print("    * 所有直接映射字段数据库均存在。")

    print("\n" + "="*60)
    print(f"✅ 检查完成。最终匹配记录数: {total_matched} / 15")
    if total_matched == 15:
        print("🎉 所有15条记录均能对应到API设备！")
    else:
        print("⚠️ 尚有记录未匹配，请检查ID别名配置或API数据。")
    print("注：本次为只读检查，未覆盖数据库，也未开发 POST /api/compatibility/check。")

if __name__ == "__main__":
    main()