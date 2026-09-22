import sqlite3
import json
from flask_cors import CORS
from flask import Flask, request, jsonify
from models import db, Drone, Sensor, Computer
from config import Config
from rules_engine import evaluate_combo


def _to_float(value, default=None):
    """把查询参数或 JSON 值安全转成 float；空值/非法值返回 default。"""
    if value is None:
        return default
    if isinstance(value, str) and value.strip() == '':
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    CORS(app)
    db.init_app(app)

    with app.app_context():
        db.create_all()

    @app.route('/api/drones', methods=['GET'])
    def get_drones():
        query = Drone.query

        min_payload = _to_float(request.args.get('min_payload'))
        max_price = _to_float(request.args.get('max_price'))
        brand = request.args.get('brand')

        if min_payload is not None:
            # 关键：max_payload 为 NULL 的设备不因为“未知”被排除
            query = query.filter(
                (Drone.max_payload == None) | (Drone.max_payload >= min_payload)
            )

        if max_price is not None:
            # 关键：price 为 NULL 的设备不因为“未知”被排除
            query = query.filter(
                (Drone.price == None) | (Drone.price <= max_price)
            )

        if brand:
            query = query.filter(Drone.brand.ilike(f"%{brand}%"))

        drones = query.all()

        return jsonify([{
            'id': d.id,
            'device_id': d.device_id,
            'brand': d.brand,
            'model': d.model,
            'max_payload': d.max_payload,
            'endurance': d.endurance,
            'weight': d.weight,
            'price': d.price,
            'power': d.power,
            'voltage': d.voltage,
            'working_temperature': d.working_temperature,
            'protection_level': d.protection_level,
            'source_url': d.source_url,
            'update_date': d.update_date.isoformat() if d.update_date else None
        } for d in drones])

    @app.route('/api/sensors', methods=['GET'])
    def get_sensors():
        query = Sensor.query

        category = request.args.get('category')
        max_price = _to_float(request.args.get('max_price'))
        min_detection_range = _to_float(request.args.get('min_detection_range'))
        function = request.args.get('function')

        if category:
            query = query.filter(Sensor.category.ilike(f"%{category}%"))

        if max_price is not None:
            # 关键：price 为 NULL 的传感器也保留
            query = query.filter(
                (Sensor.price == None) | (Sensor.price <= max_price)
            )

        if min_detection_range is not None:
            # 关键：detection_range 为 NULL 的传感器也保留
            query = query.filter(
                (Sensor.detection_range == None) |
                (Sensor.detection_range >= min_detection_range)
            )

        if function:
            query = query.filter(Sensor.functions.ilike(f"%{function}%"))

        sensors = query.all()

        return jsonify([{
            'id': s.id,
            'device_id': s.device_id,
            'category': s.category,
            'brand': s.brand,
            'model': s.model,
            'functions': s.functions,
            'detection_range': s.detection_range,
            'accuracy': s.accuracy,
            'weight': s.weight,
            'power': s.power,
            'voltage': s.voltage,
            'interfaces': s.interfaces,
            'working_temperature': s.working_temperature,
            'protection_level': s.protection_level,
            'price': s.price,
            'source_url': s.source_url,
            'update_date': s.update_date.isoformat() if s.update_date else None
        } for s in sensors])

    @app.route('/api/computers', methods=['GET'])
    def get_computers():
        query = Computer.query

        min_ram = _to_float(request.args.get('min_ram'))
        max_price = _to_float(request.args.get('max_price'))
        brand = request.args.get('brand')

        if min_ram is not None:
            # 关键：ram 为 NULL 的计算平台也保留
            query = query.filter(
                (Computer.ram == None) | (Computer.ram >= min_ram)
            )

        if max_price is not None:
            # 关键：price 为 NULL 的计算平台也保留
            query = query.filter(
                (Computer.price == None) | (Computer.price <= max_price)
            )

        if brand:
            query = query.filter(Computer.brand.ilike(f"%{brand}%"))

        computers = query.all()

        return jsonify([{
            'id': c.id,
            'device_id': c.device_id,
            'brand': c.brand,
            'model': c.model,
            'cpu': c.cpu,
            'ram': c.ram,
            'storage': c.storage,
            'weight': c.weight,
            'power': c.power,
            'voltage': c.voltage,
            'interfaces': c.interfaces,
            'working_temperature': c.working_temperature,
            'protection_level': c.protection_level,
            'price': c.price,
            'source_url': c.source_url,
            'update_date': c.update_date.isoformat() if c.update_date else None
        } for c in computers])

    @app.route('/api/filter', methods=['POST'])
    def filter_devices():
        data = request.get_json(silent=True)
        if not data:
            return jsonify({'error': '请求体需为JSON'}), 400

        budget = _to_float(data.get('budget'), default=float('inf'))
        payload = _to_float(data.get('payload'), default=0)
        endurance = _to_float(data.get('endurance'), default=0)
        det_range = _to_float(data.get('detection_range'), default=0)

        required_funcs = data.get('required_functions', [])
        if not isinstance(required_funcs, list):
            required_funcs = []
        required_funcs = [str(f).strip() for f in required_funcs if str(f).strip()]

        # 注意：
        # budget 为空/None 时默认无穷大，等于不限制价格；
        # payload/endurance/det_range 为空/None 时默认 0，等于不限制下限。
        # 如果字段本身为 NULL，下面判断用 `is not None` 包住，所以 NULL 会保留。

        drones_all = Drone.query.all()
        drones_pass, drones_fail = [], []
        for d in drones_all:
            reasons = []

            if d.price is not None and d.price > budget:
                reasons.append("价格超出预算")
            if d.max_payload is not None and d.max_payload < payload:
                reasons.append("最大载荷不足")
            if d.endurance is not None and d.endurance < endurance:
                reasons.append("续航时间不足")

            if reasons:
                drones_fail.append({
                    'device': d.model,
                    'brand': d.brand,
                    'reasons': reasons
                })
            else:
                drones_pass.append({
                    'id': d.id,
                    'device_id': d.device_id,
                    'model': d.model,
                    'brand': d.brand
                })

        sensors_all = Sensor.query.all()
        sensors_pass, sensors_fail = [], []
        for s in sensors_all:
            reasons = []

            if s.price is not None and s.price > budget:
                reasons.append("价格超出预算")
            if s.weight is not None and s.weight > payload:
                reasons.append("重量超过载荷")

            if required_funcs:
                func_str = s.functions or ''
                func_list = [f.strip() for f in func_str.split(',') if f.strip()]
                # 原逻辑：任一要求功能被覆盖即通过。
                # 如果你希望“必须覆盖全部 required_funcs”，把 any 改成 all。
                covered = any(req in func_list for req in required_funcs)
                if not covered:
                    reasons.append(f"功能不覆盖要求({','.join(required_funcs)})")

            if s.detection_range is not None and s.detection_range < det_range:
                reasons.append("探测距离不足")

            if reasons:
                sensors_fail.append({
                    'device': s.model,
                    'brand': s.brand,
                    'reasons': reasons
                })
            else:
                sensors_pass.append({
                    'id': s.id,
                    'device_id': s.device_id,
                    'model': s.model,
                    'brand': s.brand
                })

        computers_all = Computer.query.all()
        computers_pass, computers_fail = [], []
        for c in computers_all:
            reasons = []

            if c.price is not None and c.price > budget:
                reasons.append("价格超出预算")
            if c.weight is not None and c.weight > payload:
                reasons.append("重量超过载荷")

            if reasons:
                computers_fail.append({
                    'device': c.model,
                    'brand': c.brand,
                    'reasons': reasons
                })
            else:
                computers_pass.append({
                    'id': c.id,
                    'device_id': c.device_id,
                    'model': c.model,
                    'brand': c.brand
                })

        return jsonify({
            'drones': {'pass': drones_pass, 'fail': drones_fail},
            'sensors': {'pass': sensors_pass, 'fail': sensors_fail},
            'computers': {'pass': computers_pass, 'fail': computers_fail}
        })

    # =========================================================
    # 新增：API v2 推荐接口
    # =========================================================
    @app.route('/api/v2/recommend', methods=['POST'])
    def recommend_v2():
        data = request.get_json(silent=True)
        if not data:
            return jsonify({'error': '请求体需为JSON'}), 400
        
        # 1. 获取前端传来的启用规则和任务需求
        enabled_rules = data.get('enabled_rules', [])
        requirements = data.get('requirements', {})
        
        # 2. 从数据库读取所有 v2 兼容性设备
        conn = sqlite3.connect('data/low_altitude_selection.db')
        cursor = conn.cursor()
        cursor.execute("SELECT device_id, raw_data FROM v2_compatibility")
        rows = cursor.fetchall()
        conn.close()
        
        all_devices = {row[0]: json.loads(row[1]) for row in rows}
        
        # 3. 按设备类型分组（根据列名判断）
        uavs = [d for d in all_devices.values() if '无人机ID' in d]
        sensors = [d for d in all_devices.values() if '传感器ID' in d]
        computers = [d for d in all_devices.values() if '计算平台ID' in d]
        
        recommendations = []
        
        # 4. 穷举所有组合，调用规则引擎打分
        for uav in uavs:
            for sensor in sensors:
                for computer in computers:
                    combo_data = {
                        'uav': uav,
                        'sensor': sensor,
                        'computer': computer,
                        'requirements': requirements
                    }
                    status, details = evaluate_combo(combo_data, enabled_rules)
                    
                    # 只有 pass 和 manual_review 才作为推荐返回，fail 直接丢弃
                    if status in ['pass', 'manual_review']:
                        recommendations.append({
                            'status': status,
                            'details': details,
                            'uav': uav.get('无人机ID'),
                            'sensor': sensor.get('传感器ID'),
                            'computer': computer.get('计算平台ID')
                        })
        
        # 5. 排序：优先推荐 pass，再推荐 manual_review
        recommendations.sort(key=lambda x: 0 if x['status'] == 'pass' else 1)
        
        # 6. 返回 Top 3 组合
        return jsonify({
            'status': 'success',
            'total_found': len(recommendations),
            'top_3': recommendations[:3]
        })

    return app


if __name__ == '__main__':
    app = create_app()
    app.run(debug=True, host='0.0.0.0', port=5000)