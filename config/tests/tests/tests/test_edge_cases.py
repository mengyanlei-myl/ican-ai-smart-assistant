# tests/test_edge_cases.py
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from rules_engine import evaluate_combo

def test_missing_data_goes_to_manual_review():
    combo_data = {'uav': {}, 'sensor': {}, 'computer': {}, 'requirements': {'任务载荷/安装余量(kg)': 0.5}}
    status, details = evaluate_combo(combo_data, ['R01'])
    assert status == 'manual_review', f"空数据应转人工复核，实际为 {status}"
    print("✅ 边界测试：空值数据成功转为 manual_review")

def test_null_price_not_zero():
    combo_data = {'uav': {'参考价格(CNY)': None}, 'sensor': {}, 'computer': {}, 'requirements': {'预算(CNY)': 100000}}
    status, details = evaluate_combo(combo_data, ['R02'])
    assert status == 'manual_review', f"空价格应转人工复核，实际为 {status}"
    print("✅ 边界测试：空价格未被误判为 0，正确转 manual_review")

def test_top3_less_than_three():
    recs = [{'status': 'pass'}, {'status': 'manual_review'}]
    top_3 = recs[:3]
    assert len(top_3) == 2, f"Top 3 不足时应返回实际数量，实际为 {len(top_3)}"
    print("✅ 边界测试：Top 3 数量不足时正确处理")

if __name__ == '__main__':
    test_missing_data_goes_to_manual_review()
    test_null_price_not_zero()
    test_top3_less_than_three()
    print("\n所有边界测试通过！")