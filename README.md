# 🚁 低空设备智能选型系统

“低空智选”是一套面向低空作业场景的无人机设备组合决策系统。用户可以使用自然语言描述预算、续航、载荷、工作环境等任务要求，系统将需求转换为结构化约束，从无人机、传感器和机载计算平台目录中筛选候选设备，并通过确定性规则校验组合兼容性，输出 Top3 暂定推荐方案、规则状态、推荐理由和缺失证据。

> 当前版本用于竞赛演示和方案辅助。公开资料不足时，系统不会编造参数，而是返回 `manual_review`、`insufficient_data` 或 `provisional`，提示用户进行人工复核。

## 主要功能

- 自然语言任务输入与结构化需求解析
- 预算、续航、载荷、环境和偏好等约束提取
- 无人机、传感器和计算平台候选设备筛选
- R01～R07 组合兼容性与安全规则校验
- Top3 组合推荐及推荐理由展示
- 缺失字段、资料不足和人工复核状态提示
- API v2 健康检查、目录查询、兼容性检查和推荐接口

## 功能页面

| 文件 | 功能 |
| --- | --- |
| `task_input.html` | 输入自然语言任务及补充约束 |
| `requirement_confirmation.html` | 确认系统解析出的任务要求 |
| `candidate_devices.html` | 查看候选设备及约束检查状态 |
| `initial_solution.html` | 查看 Top3 暂定推荐方案、规则结果和风险提示 |

## 运行环境

- Python 3.11
- Windows 10/11（最终演示环境）
- 现代浏览器，例如 Microsoft Edge 或 Google Chrome

## 快速开始

### 1. 解压源代码

将项目压缩包完整解压到本地文件夹。请勿只复制 HTML 页面，`data`、`config` 和其他 Python 文件均为程序运行所需内容。

### 2. 打开终端

在项目根目录打开 PowerShell、命令提示符或其他终端。项目根目录中应能看到 `app.py` 和 `requirements.txt`。

### 3. 安装依赖

```bash
python -m pip install -r requirements.txt
```

如计算机同时安装了多个 Python 版本，请确认当前命令使用的是 Python 3.11。

### 4. 启动后端

```bash
python app.py
```

看到 Flask 服务启动信息后，请保持该终端窗口开启。

### 5. 检查健康接口

在浏览器中打开：

<http://127.0.0.1:5000/api/v2/health>

返回结果中包含以下内容时，说明后端和数据库已正常启动：

```json
{
  "api_version": "v2",
  "database": "ok",
  "status": "ok"
}
```

实际响应还可能包含设备目录数量、兼容性记录数量和验证状态统计。

### 6. 打开前端

使用浏览器打开项目根目录中的 `task_input.html`，然后按以下顺序操作：

1. 输入自然语言任务并填写必要参数。
2. 确认系统解析出的结构化要求。
3. 查看候选设备及筛选结果。
4. 查看 Top3 暂定推荐方案、规则状态和风险提示。

## 演示案例

推荐使用以下任务进行演示：

> 预算20万元，至少续航30分钟，需要搭载2kg设备，优先选择续航较长的方案。

系统将识别预算、最低续航、最大载荷和优先目标，并将这些要求继续传递到候选筛选和推荐阶段。

演示过程中可能看到以下状态：

- `ready`：任务语义明确，可以进入候选评估。
- `pass`：当前规则已有足够证据并通过校验。
- `fail`：当前组合违反硬约束，将被排除。
- `manual_review`：公开资料不足或需要人工确认。
- `insufficient_data`：候选设备缺少完成该项判断所需的字段级证据。
- `provisional`：暂定推荐，仍需人工复核。
- `final`：相关约束已经完成验证，可作为最终推荐。

`ready` 只表示任务描述已经解析清楚，不代表所有候选设备都已通过规则验证。

## R01～R07 规则说明

| 规则 | 校验内容 |
| --- | --- |
| R01 | 载荷及安全余量校验 |
| R02 | 组合成本与预算校验 |
| R03 | 设备功耗与供电能力校验 |
| R04 | 工作电压兼容性校验 |
| R05 | 数据接口兼容性校验 |
| R06 | 工作温度及防护能力校验 |
| R07 | 操作系统、ROS、CPU及驱动或SDK兼容性校验 |

违反硬约束的组合直接排除。公开资料不足时，系统保留缺失字段和判断原因，并将对应规则标记为人工复核或资料不足。

## 主要 API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/v2/health` | 检查服务、数据库和数据统计状态 |
| GET | `/api/v2/drones` | 查询无人机目录 |
| GET | `/api/v2/sensors` | 查询传感器目录 |
| GET | `/api/v2/computers` | 查询机载计算平台目录 |
| GET | `/api/v2/stats` | 查询目录与验证数据统计 |
| POST | `/api/v2/compatibility/check` | 检查指定设备组合的兼容性 |
| POST | `/api/v2/recommendations` | 使用结构化参数生成推荐结果 |
| POST | `/api/v2/recommendations/semantic` | 使用自然语言任务生成语义推荐结果 |

## 测试与验证

运行全部自动化测试：

```bash
python -m pytest -q
```

运行黄金案例脚本：

```bash
python test_golden_cases.py
```

最终演示版本的验证结果：

- 语义解析专项测试通过
- 候选设备与推荐服务测试通过
- 阶段接口回归测试通过
- 完整自动化测试全部通过，未发现失败项
- 黄金案例 10 项通过、0 项失败
- 健康接口返回 `status=ok`

## 项目结构

```text
ican-ai-smart-assistant/
├─ app.py
├─ task_input.html
├─ requirement_confirmation.html
├─ candidate_devices.html
├─ initial_solution.html
├─ semantic_parser.py
├─ semantic_candidate_service.py
├─ semantic_recommendation_service.py
├─ decision_service.py
├─ rules_engine.py
├─ config/
├─ data/
├─ docs/
├─ tests/
├─ requirements.txt
├─ test_golden_cases.py
└─ README.md
```

## 当前版本

- 默认分支：`master`
- 最终演示提交：`5dd1c80`
- Gitee：<https://gitee.com/dreamy-mist/ican-ai-smart-assistant/tree/master/>

## 已知限制

- 部分公开设备资料缺少价格、续航、电压或软件兼容性字段。
- 数据不足的组合只能作为暂定推荐，不能替代工程人员的最终审核。
- 系统当前以本地 Flask 服务和静态 HTML 页面运行，尚未部署为公网在线应用。

## 团队成员

| 成员 | 主要职责 |
| --- | --- |
| 孙子茜 | 数据收集、规则与项目验收 |
| 孟令祺 | 后端开发与推荐服务 |
| 孟妍蕾 | 前端开发与页面联调 |

## 开发日志

### 2026-08-31

- 完成四个前端功能页面
- 建立 Gitee 项目仓库

### 2026-09-08

- 完成 SQLite 数据库建表和基础数据导入
- 完成后端基础查询与筛选接口

### 2026-09-21

- 修复 ID 映射问题并增加 CORS 支持
- 接入三类兼容性规格数据
- 候选设备页面接入真实后端接口

### 2026-09-28

- 完成自然语言需求解析和任务确认流程
- 完成无人机、传感器与计算平台 Top3 组合推荐
- 完成 R01～R07 规则状态、缺失字段和风险提示展示
- 修复页面跳转过程中的任务要求丢失问题
- 完成最终自动化测试与黄金案例验证
- 将最终演示版本合并到 `master`
