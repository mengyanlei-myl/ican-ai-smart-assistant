# 推荐决策 API v2

## 本地启动

在项目根目录使用项目虚拟环境，不要使用系统环境或 `.tools`：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

默认地址为 `http://127.0.0.1:5000`。

## 数据边界

- 设备目录共 791 条：无人机 281、传感器 460、计算平台 50。目录用于完整搜索和查看，字段不全的设备不会被过滤。
- 可信兼容参数共 25 条，字段证据共 214 条。它们表示设备字段已有证据，不表示任意三类设备组合已经验证。
- 推荐接口从 25 条证据层记录产生候选，并对每个组合重新执行 R01～R07。返回的 `combination_verified` 恒为 `false`，除非未来存在独立的组合级验证数据。
- SQL `NULL` 原样序列化为 JSON `null`，不转换成 `0`、空字符串或推测值。

## 三态规则

- `pass`：所需字段完整且明确满足规则。
- `fail`：所需字段完整且明确违反规则。
- `manual_review`：必要字段缺失、不可解析、含义不清或需要转接/额外验证。具体字段位于 `missing_fields`。

总体状态优先级为 `fail` > `manual_review` > `pass`。

## 目录接口

### `GET /api/v2/drones`

### `GET /api/v2/sensors`

### `GET /api/v2/computers`

共同参数：

| 参数 | 说明 |
| --- | --- |
| `q` | 在标准 ID、厂家、型号及原始属性中进行关键词搜索 |
| `page` | 页码，从 1 开始，默认 1 |
| `page_size` | 每页条数，默认 20，范围 1～100 |
| `verification_status` | `verified`、`partial` 或 `catalog_only` |
| `brand` / `厂家` | 厂家精确筛选，不区分大小写 |
| `category` / `类别` | 传感器类别精确筛选 |

响应示例：

```json
{
  "items": [
    {
      "device_id": "Basler_boa9344_70cc",
      "device_type": "sensor",
      "brand": "Basler",
      "model": "boa9344-70cc",
      "weight": null,
      "verification_status": "partial",
      "attributes": {
        "标准化重量(kg)": null
      }
    }
  ],
  "total": 1,
  "page": 1,
  "page_size": 20,
  "pages": 1
}
```

PowerShell 示例：

```powershell
Invoke-RestMethod 'http://127.0.0.1:5000/api/v2/sensors?q=Basler&page=1&page_size=20'
```

## 兼容性判定

### `POST /api/v2/compatibility/check`

请求：

```json
{
  "drone_id": "UAV-DJI-M400",
  "sensor_ids": ["Stereolabs_ZED_2i", "Livox_Mid360"],
  "computer_id": "CP-UP-UP2PRO7000",
  "enabled_rules": ["R01", "R03", "R04"],
  "task_requirements": {
    "installation_margin_kg": 0.5,
    "budget": 100000,
    "mission_temp_min_c": -10,
    "mission_temp_max_c": 40,
    "required_protection_level": "IP54"
  }
}
```

响应包含 `overall_status`、七条 `rule_results`、汇总后的 `missing_fields`、`evidence_sources` 和每条规则的 `compared_values`。多个传感器的重量在 R01 中求和，功耗在 R03 中求和；其他字段不会擅自累加。

`enabled_rules` 可选。省略时执行全部 R01～R07；传入时仅执行任务明确启用的规则，未启用规则不参与总体状态。这与黄金案例的“启用规则”口径一致。

curl 示例：

```bash
curl -X POST http://127.0.0.1:5000/api/v2/compatibility/check \
  -H "Content-Type: application/json" \
  -d '{"drone_id":"UAV-DJI-M400","sensor_ids":["Stereolabs_ZED_2i"],"computer_id":"CP-UP-UP2PRO7000","task_requirements":{"installation_margin_kg":0.5}}'
```

不存在的设备 ID 返回 `404`；缺少字段、类型错误或重复传感器 ID 返回 `400`。

## 推荐排序

### `POST /api/v2/recommendations`

请求：

```json
{
  "requirements": {
    "enabled_rules": ["R01"],
    "installation_margin_kg": 0.5,
    "mission_temp_min_c": -10,
    "mission_temp_max_c": 40,
    "required_protection_level": "IP54"
  },
  "top_n": 10,
  "allow_manual_review": true,
  "weights": {
    "data_completeness": 15,
    "evidence_trust": 15
  }
}
```

`top_n` 默认 10，允许 1～50。可覆盖的权重名称：

- `task_constraint_fit`
- `payload_margin`
- `power_compatibility`
- `environment_adaptation`
- `interface_software`
- `data_completeness`
- `evidence_trust`

算法流程：

1. 根据明确的 ID、厂家和传感器类别条件缩小 25 条证据层候选池。
2. 流式枚举候选组合，对每个组合执行 R01～R07；不保存 `281×460×50` 全部组合。
3. `fail` 组合计入 `rejected_count`，不进入正常推荐。
4. 对 `pass` 或允许返回的 `manual_review` 组合计算 0～100 分。
5. 软评分字段缺失时，该分项标记为 `included=false`，不按 0 参与平均，同时降低 `coverage`/`confidence`，避免缺失数据获得优势。
6. 使用固定大小的 Top-K 堆。最终先按 `pass`、再按 `manual_review`，随后按分数降序及标准设备 ID 升序稳定排序。

响应摘要：

```json
{
  "recommendations": [],
  "dataset_summary": {},
  "combinations_checked": 500,
  "rejected_count": 0,
  "pass_count": 0,
  "manual_review_count": 500,
  "elapsed_ms": 25.4
}
```

每个推荐项均包含 `score_breakdown`、`rule_results`、`coverage`、`confidence`、`missing_fields` 和 `evidence_sources`。`manual_review` 不会显示为兼容通过。

PowerShell 示例：

```powershell
$body = @{
  requirements = @{ installation_margin_kg = 0.5 }
  top_n = 10
  allow_manual_review = $true
  weights = @{}
} | ConvertTo-Json -Depth 5
Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:5000/api/v2/recommendations' -ContentType 'application/json' -Body $body
```

## 统计与健康检查

### `GET /api/v2/stats`

从数据库实时统计目录数量、25 条兼容参数、214 条字段证据以及可信状态分布。

### `GET /api/health`

保留原健康检查地址，并复用相同的实时数据库统计，不写死数量。

## 兼容接口

原有 `/api/drones`、`/api/sensors`、`/api/computers`、`/api/filter`、`/api/v2/devices`、`/api/v2/compatibility` 和 `/api/v2/recommend` 均保留，避免破坏现有成员调用。
