# inspect_excel.py
import pandas as pd
import os

def inspect_excel(file_path):
    print(f"\n{'='*20} 检查文件: {file_path} {'='*20}")
    if not os.path.exists(file_path):
        print("❌ 文件不存在")
        return
    try:
        df = pd.read_excel(file_path)
        print(f"✅ 读取成功，共 {len(df)} 行")
        print(f"列名: {df.columns.tolist()}")
        print("\n前 3 行数据预览:")
        # 为了避免列太多显示乱，只打印前3行，并只显示非空值
        for idx, row in df.head(3).iterrows():
            print(f"  行 {idx+1}:")
            for col, val in row.items():
                if pd.notna(val):
                    print(f"    {col}: {val}")
    except Exception as e:
        print(f"❌ 读取失败: {e}")

V2_DIR = 'data/compatibility/v2'
inspect_excel(os.path.join(V2_DIR, 'golden_cases_v1.xlsx'))
inspect_excel(os.path.join(V2_DIR, 'compatibility_specs_v2_completed.xlsx'))
inspect_excel(os.path.join(V2_DIR, 'sensor_compatibility_specs_v2_completed.xlsx'))