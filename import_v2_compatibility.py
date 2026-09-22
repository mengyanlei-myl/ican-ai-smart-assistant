# import_v2_compatibility.py
import pandas as pd
import sqlite3
import os
import json

DB_PATH = 'data/low_altitude_selection.db'
V2_DIR = 'data/compatibility/v2'

def import_v2():
    print("开始导入v2兼容性数据（追加模式，不删除v1数据）...")
    if not os.path.exists(DB_PATH):
        print("❌ 数据库不存在，请先运行原项目初始化。")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 1. 清理之前导入失败的空数据 (v2专属表，不影响v1的249条数据)
    cursor.execute("CREATE TABLE IF NOT EXISTS v2_compatibility (id INTEGER PRIMARY KEY AUTOINCREMENT, device_id TEXT UNIQUE, raw_data TEXT)")
    cursor.execute("DELETE FROM v2_compatibility")
    conn.commit()
    print("🧹 已清空旧的 v2 错误数据，准备重新导入...")

    # 2. 读取 ID 映射表
    mapping_file = os.path.join(V2_DIR, 'device_id_mapping_v2.xlsx')
    id_mapping = {}
    if os.path.exists(mapping_file):
        df_map = pd.read_excel(mapping_file)
        if '旧ID' in df_map.columns and '最终采用ID' in df_map.columns:
            for _, row in df_map.iterrows():
                if pd.notna(row['旧ID']) and pd.notna(row['最终采用ID']):
                    id_mapping[str(row['旧ID']).strip()] = str(row['最终采用ID']).strip()
        if '新ID' in df_map.columns and '最终采用ID' in df_map.columns:
            for _, row in df_map.iterrows():
                if pd.notna(row['新ID']) and pd.notna(row['最终采用ID']):
                    id_mapping[str(row['新ID']).strip()] = str(row['最终采用ID']).strip()
        print(f"✅ 已读取 ID 映射表，共 {len(id_mapping)} 条映射规则。")

    # 3. 定义待导入的 v2 文件列表
    v2_files = [
        'compatibility_specs_v2_completed.xlsx',
        'sensor_compatibility_specs_v2_completed.xlsx',
        'computer_compatibility_specs_v2_completed.xlsx'
    ]

    for file_name in v2_files:
        file_path = os.path.join(V2_DIR, file_name)
        if not os.path.exists(file_path):
            print(f"⚠️ 文件不存在: {file_name}，跳过。")
            continue
        
        df = pd.read_excel(file_path)
        df.columns = [str(c).strip() for c in df.columns]
        print(f"正在处理 {file_name}，共 {len(df)} 行数据...")
        
        # 【核心修复】根据文件名，动态决定使用哪一列作为设备的唯一 ID
        id_col = 'device_id'
        if 'sensor' in file_name:
            id_col = '传感器ID'
        elif 'computer' in file_name:
            id_col = '计算平台ID'
        else:
            id_col = '无人机ID'
            
        print(f"  -> 识别到 ID 列为: {id_col}")
        
        success = 0
        fail = 0
        for idx, row in df.iterrows():
            try:
                # 提取真实的原始 ID，并应用映射
                original_id = str(row.get(id_col, '')).strip()
                if not original_id:
                    raise ValueError(f"第 {idx+1} 行缺少 ID")
                    
                final_id = id_mapping.get(original_id, original_id)
                
                # 空值必须保持为 NULL
                raw_json = json.dumps({
                    k: (None if pd.isna(v) or str(v).strip() == '' else v) 
                    for k, v in row.items()
                }, ensure_ascii=False)
                
                cursor.execute('''
                    INSERT OR REPLACE INTO v2_compatibility (device_id, raw_data)
                    VALUES (?, ?)
                ''', (final_id, raw_json))
                
                success += 1
            except Exception as e:
                fail += 1
                print(f"  第 {idx+1} 行处理失败: {e}")
                
        print(f"  ✅ {file_name} 处理完成: 成功 {success}, 失败 {fail}")

    conn.commit()
    conn.close()
    print("🎉 v2 数据重新导入全部结束！")

if __name__ == '__main__':
    import_v2()