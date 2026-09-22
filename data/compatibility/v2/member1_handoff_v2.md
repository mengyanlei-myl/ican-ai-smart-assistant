# 成员一数据扩充 v2 交接说明

更新日期：2026-09-22

## 本轮完成情况

- 首批设备保持无人机10、传感器10、计算平台5，未替换设备。
- verified 2条、partial 23条、catalog_only 0条。
- 本轮新增38个有官方证据的非空字段，主要来自Stereolabs、Basler、u-blox、Hailo和UP官方文档。
- 关键非空字段证据覆盖率保持100%。
- golden cases：3个pass、4个fail、3个manual_review；7个案例可根据其明确启用的规则完整自动判断。

## 规则启用口径

- 只有案例“启用规则”列中的规则参与总体状态计算。
- 用户未提出预算时不启用R02，价格为空不影响其他规则。
- 用户未提出温度或防护要求时不启用相应R06条件。
- 启用规则所需字段齐全且满足条件时为pass；明确不满足时为fail；需要但缺失或存在冲突时为manual_review。
- 任一启用规则为fail，总体为fail；没有fail但至少一项为manual_review，总体为manual_review；全部启用规则pass时总体为pass。
- 空值必须导入为NULL，不得转换为0。

## 给成员二

- 正式导入使用`02_最终文件`，并按`device_id_mapping_v2.xlsx`的“最终采用ID”去重。
- 重点ID映射：`DJI_Matrice_400 → UAV-DJI-M400`、`Inspired_Flight_IF800_Tomcat → UAV-IFLIGHT-IF800`、`DJI_Matrice_30T → UAV-DJI-M30T`。
- `data_quality_report_v2.xlsx`的“规则支持率”“设备规则能力”“案例自动判断”工作表给出了R01–R07的可用范围。
- `golden_cases_v1.xlsx`新增“启用规则”“未启用规则”“证据定位”列，联调时不得执行未启用规则。
- Stereolabs ZED 2i已补齐5V供电、机械螺纹、ZED SDK、操作系统和ROS 2资料，状态升级为verified。
- Basler五款相机已补齐官方电压、C-mount、pylon SDK和操作系统；没有官方ROS资料时继续留空，不填“否”。

## 给成员三

- `verified`显示“已核验”，`partial`显示“部分核验”，`catalog_only`显示“仅确认型号”。
- `manual_review`显示“需人工确认”，同时显示启用规则和具体缺失字段。
- 未启用规则不要显示为失败或待复核。
- 官方来源建议显示为可点击的“查看官方来源”，多链接逐条展示。
- 演示组合：
  - 普通白天巡检：Matrice 400 + Basler a2a1920-160umbas + UP Squared Pro 7000，启用R01，预期pass。
  - 激光雷达建模：IF800 Tomcat + Livox Mid-360 + UP Squared Pro 7000，启用R01，预期pass。
  - 夜间热成像：Matrice 400 + FLIR Boson 640 + Raspberry Pi 5，启用R01/R05/R07，预期manual_review。

## 剩余风险

- R02支持率为0：首批设备仍缺可靠人民币官方或授权价格；外币价格未直接写入CNY。
- 多数JOUAV设备缺少公开的载荷输出电压、输出功率和标准机械挂载资料。
- 多数计算平台没有IP等级；只有任务明确要求防护时才影响R06。
- CW-20E官方页面同页出现5 kg和6 kg载荷，继续留空并记录conflict。
- CW-80E旧目录25 kg、当前官网20 kg，继续不纳入首批核心集。
- FlyCart 30的95 kg最大起飞重量已从标准化有效载荷中清空。
- Basler新增库仅覆盖可见光工业相机，不能替代热成像、激光雷达或RTK/IMU。
- 同系列不同SKU、供电模式、镜头、内存和开发套件参数不得混用。

本轮未修改原始文件、v1基准文件、数据库、后端、前端或推荐算法，也未上传或推送Gitee。
