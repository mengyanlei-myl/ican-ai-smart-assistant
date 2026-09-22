# test_api_v2.py
# 这里使用 Python 标准库 urllib，无需额外安装 requests 库
import urllib.request
import json

url = "http://127.0.0.1:5000/api/v2/recommend"

# 模拟前端传来的“普通白天巡检”任务需求（参考 GC01）
payload = {
    "enabled_rules": ["R01"],
    "requirements": {
        "任务载荷/安装余量(kg)": 0.5,
        "预算(CNY)": 100000
    }
}

# 构建请求
req = urllib.request.Request(
    url,
    data=json.dumps(payload).encode('utf-8'),
    headers={'Content-Type': 'application/json'}
)

try:
    print("正在请求 API...")
    with urllib.request.urlopen(req) as response:
        status_code = response.getcode()
        result = json.loads(response.read().decode('utf-8'))
        
        print("\n✅ HTTP 状态码:", status_code)
        print("✅ 返回的 JSON 数据:")
        print(json.dumps(result, indent=2, ensure_ascii=False))
except Exception as e:
    print(f"\n❌ 请求失败: {e}")
    print("请确保你已经启动了 app.py（在另一个终端窗口运行 python app.py）")