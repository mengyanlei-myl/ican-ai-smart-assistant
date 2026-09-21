# API 契约文档 v1

## 1. /api/drones
- 请求地址：http://127.0.0.1:5000/api/drones
- 最外层是数组还是对象：数组
- 总记录数：100
- 字段定义（字段名、类型、是否为空）：
  - `brand`：字符串，不为空
  - `endurance`：数字，可能为空
  - `id`：整数，不为空
  - `max_payload`：数字，可能为空
  - `model`：字符串，不为空
  - `power`：数字，可能为空
  - `price`：数字，可能为空
  - `protection_level`：字符串，可能为空（注：数据中有值，但按任务要求列出）
  - `source_url`：字符串，不为空
  - `update_date`：字符串/日期，可能为空
  - `voltage`：数字/字符串，可能为空
  - `weight`：数字，可能为空
  - `working_temperature`：字符串，可能为空（注：数据中有值）
- 真实示例：
```json
[
  {
    "brand": "DJI",
    "endurance": null,
    "id": 201,
    "max_payload": null,
    "model": "Matrice 400",
    "power": null,
    "price": null,
    "protection_level": "IP55",
    "source_url": "https://enterprise.dji.com/matrice-400",
    "update_date": null,
    "voltage": null,
    "weight": null,
    "working_temperature": "-20~50"
  },
  {
    "brand": "DJI",
    "endurance": null,
    "id": 202,
    "max_payload": 9.2,
    "model": "Matrice 350 RTK",
    "power": null,
    "price": null,
    "protection_level": "IP55",
    "source_url": "https://enterprise.dji.com/matrice-350-rtk",
    "update_date": null,
    "voltage": null,
    "weight": null,
    "working_temperature": "-20~50"
  }
]


## 2. /api/sensors
- 请求地址：http://127.0.0.1:5000/api/sensors
- 最外层是数组还是对象：数组
- 总记录数：99
- 字段定义（字段名、类型、是否为空）：
  - `accuracy`：字符串，可能为空（当前值为"待补充"）
  - `brand`：字符串，不为空
  - `category`：字符串，不为空
  - `detection_range`：数字/字符串，可能为空
  - `functions`：字符串，不为空
  - `id`：整数，不为空
  - `interfaces`：字符串，不为空
  - `model`：字符串，不为空
  - `power`：数字/字符串，可能为空
  - `price`：数字，可能为空
  - `protection_level`：字符串，可能为空（当前值为"待补充"）
  - `source_url`：字符串，不为空
  - `update_date`：字符串/日期，可能为空
  - `voltage`：数字/字符串，可能为空
  - `weight`：数字，可能为空
  - `working_temperature`：字符串，可能为空（当前值为"待补充"）
- 真实示例：
```json
[
  {
    "accuracy": "\u5f85\u8865\u5145",
    "brand": "Allied Vision",
    "category": "\u53ef\u89c1\u5149\u76f8\u673a",
    "detection_range": null,
    "functions": "Allied Vision Alvium USB3 Industrial Camera",
    "id": 199,
    "interfaces": "USB3",
    "model": "Alvium 1800 U-2050c",
    "power": null,
    "price": null,
    "protection_level": "\u5f85\u8865\u5145",
    "source_url": "https://www.alliedvision.com/en/products/cameras/alvium/",
    "update_date": null,
    "voltage": null,
    "weight": null,
    "working_temperature": "\u5f85\u8865\u5145"
  },
  {
    "accuracy": "\u5f85\u8865\u5145",
    "brand": "Basler",
    "category": "\u53ef\u89c1\u5149\u76f8\u673a",
    "detection_range": null,
    "functions": "Basler ace 2 GigE Industrial Camera",
    "id": 200,
    "interfaces": "GigE",
    "model": "a2A1920-51gmPRO",
    "power": null,
    "price": null,
    "protection_level": "\u5f85\u8865\u5145",
    "source_url": "https://www.baslerweb.com/en/shop/a2a1920-51gmpro/",
    "update_date": null,
    "voltage": null,
    "weight": null,
    "working_temperature": "\u5f85\u8865\u5145"
  }
]


## 3. /api/computers
- 请求地址：http://127.0.0.1:5000/api/computers
- 最外层是数组还是对象：数组
- 总记录数：50
- 字段定义（字段名、类型、是否为空）：
  - `brand`：字符串，不为空
  - `cpu`：字符串，不为空
  - `id`：整数，不为空
  - `interfaces`：字符串，不为空
  - `model`：字符串，不为空
  - `power`：数字，可能为空
  - `price`：数字，可能为空
  - `protection_level`：字符串，可能为空
  - `ram`：字符串，不为空
  - `source_url`：字符串，不为空
  - `storage`：字符串，可能为空
  - `update_date`：字符串/日期，可能为空
  - `voltage`：字符串，可能为空
  - `weight`：数字，可能为空
  - `working_temperature`：字符串，可能为空
- 真实示例：
```json
[
  {
    "brand": "NVIDIA",
    "cpu": "NVIDIA Blackwell GPU\uff1bTensor Cores; 14\u6838 Arm Neoverse V3AE",
    "id": 101,
    "interfaces": "\u6a21\u5757\u63a5\u53e3\u7531\u8f7d\u677f\u5f15\u51fa\uff1b\u652f\u6301\u9ad8\u901f\u4ee5\u592a\u7f51; UART/I\u00b2C/SPI/GPIO/CAN\uff08\u7531\u8f7d\u677f\u5f15\u51fa\uff09",
    "model": "Jetson T5000",
    "power": 40.0,
    "price": null,
    "protection_level": null,
    "ram": "128GB LPDDR5X\uff1b273GB/s",
    "source_url": "https://www.nvidia.com/en-us/autonomous-machines/embedded-systems/jetson-thor/",
    "storage": null,
    "update_date": null,
    "voltage": "HV 7~20V\uff08\u6a21\u5757\u7535\u6e90\u8f68\uff09",
    "weight": null,
    "working_temperature": null
  },
  {
    "brand": "NVIDIA",
    "cpu": "NVIDIA Blackwell GPU\uff1bTensor Cores",
    "id": 102,
    "interfaces": "\u6a21\u5757\u63a5\u53e3\u7531\u8f7d\u677f\u5f15\u51fa; UART/I\u00b2C/SPI/GPIO/CAN\uff08\u7531\u8f7d\u677f\u5f15\u51fa\uff09",
    "model": "Jetson T4000",
    "power": null,
    "price": null,
    "protection_level": null,
    "ram": "64GB LPDDR5X",
    "source_url": "https://www.nvidia.com/en-us/autonomous-machines/embedded-systems/jetson-thor/",
    "storage": null,
    "update_date": null,
    "voltage": null,
    "weight": null,
    "working_temperature": null
  }
]