# check_mapping.py
import pandas as pd
import os

file_path = 'data/compatibility/v2/device_id_mapping_v2.xlsx'

if os.path.exists(file_path):
    df = pd.read_excel(file_path)
    print("✅ 成功读取映射表")
    print("文件共有", len(df), "行数据")
    print("实际的列名是：", list(df.columns))
    print("\n前 5 行数据预览：")
    print(df.head().to_string())
else:
    print(f"❌ 找不到文件: {file_path}")