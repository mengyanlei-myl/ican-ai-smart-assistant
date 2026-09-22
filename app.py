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


def _infer_enabled_rules(requirements):
    """后端根据前端传来的 requirements 字段，自动推断应启用哪些规则"""
    enabled_rules = []
    
    # 如果传了载荷，启用 R01
    if requirements.get('任务载荷/安装余量(kg)') is not None:
        enabled_rules.append('R01')
    # 如果传了预算，启用 R02（当前数据大概率转人工，但逻辑上要启用）
    if requirements.get('预算(CNY)') is not None:
        enabled_rules.append('R02')
    # 如果传了必需接口，启用 R05
    if requirements.get('必需接口'):
        enabled_rules.append('R05')
    # 如果传了温度要求，启用 R06
    if requirements.get('工作温度最低值(℃)') is not None or requirements.get('工作温度最高值(℃)') is not None:
        enabled_rules.append('R06')
    # 如果传了传感器类别且是视觉/相机类，启用 R07
    sensor_category = str(requirements.get('传感器类别', ''))
    if sensor_category and ('视觉' in sensor_category or '相机' in sensor_category or '摄像头' in sensor_category):
        enabled_rules.append('R07')
        
    return enabled_rules


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    CORS(app)
    db.init_app(app)

    with app.app_context():
        db.create_all()

    # ==================== V1 接口（原样保留） ====================
    @app.route('/api/drones', methods=['GET'])
    def get_drones():
        query = Drone.query
        min_payload = _to_float(request.args.get('min_payload'))
        max_price = _to_float(request.args.get('max_price'))
        brand = request.args.get('brand')

        if min_payload is not None:
            query = query.filter((Drone.max_payload == None) | (Drone.max_payload >= min_payload))
        if max_price is not None:
            query = query.filter((Drone.price == None) | (Drone.price <= max_price))
        if brand:
            query = query.filter(Drone.brand.ilike(f"%{brand}%"))

        drones = query.all()
        return jsonify([{
            'id': d.id, 'device_id': d.device_id, 'brand': d.brand, 'model': d.model,
            'max_payload': d.max_payload, 'endurance': d.endurance, 'weight': d.weight,
            'price': d.price, 'power': d.power, 'voltage': d.voltage,
            'working_temperature': d.working_temperature, 'protection_level': d.protection_level,
            'source_url': d.source_url, 'update_date': d.update_date.isoformat() if d.update_date else None
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
            query = query.filter((Sensor.price == None) | (Sensor.price <= max_price))
        if min_detection_range is not None:
            query = query.filter((Sensor.detection_range == None) | (Sensor.detection_range >= min_detection_range))
        if function:
            query = query.filter(Sensor.functions.ilike(f"%{function}%"))

        sensors = query.all()
        return jsonify([{
            'id': s.id, 'device_id': s.device_id, 'category': s.category, 'brand': s.brand, 'model': s.model,
            'functions': s.functions, 'detection_range': s.detection_range, 'accuracy': s.accuracy,
            'weight': s.weight, 'power': s.power, 'voltage': s.voltage, 'interfaces': s.interfaces,
            'working_temperature': s.working_temperature, 'protection_level': s.protection_level,
            'price': s.price, 'source_url': s.source_url, 'update_date': s.update_date.isoformat() if s.update_date else None
        } for s in sensors])

    @app.route('/api/computers', methods=['GET'])
    def get_computers():
        query = Computer.query
        min_ram = _to_float(request.args.get('min_ram'))
        max_price = _to_float(request.args.get('max_price'))
        brand = request.args.get('brand')

        if min_ram is not None:
            query = query.filter((Computer.ram == None) | (Computer.ram >= min_ram))
        if max_price is not None:
            query = query.filter((Computer.price == None) | (Computer.price <= max_price))
        if brand:
            query = query.filter(Computer.brand.ilike(f"%{brand}%"))

        computers = query.all()
        return jsonify([{
            'id': c.id, 'device_id': c.device_id, 'brand': c.brand, 'model': c.model,
            'cpu': c.cpu, 'ram': c.ram, 'storage': c.storage, 'weight': c.weight,
            'power': c.power, 'voltage': c.voltage, 'interfaces': c.interfaces,
            'working_temperature': c.working_temperature, 'protection_level': c.protection_level,
            'price': c.price, 'source_url': c.source_url, 'update_date': c.update_date.isoformat() if c.update_date else None
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

        drones_all = Drone.query.all()
        drones_pass, drones_fail = [], []
        for d in drones_all:
            reasons = []
            if d.price is not None and d.price > budget: reasons.append("价格超出预算")
            if d.max_payload is not None and d.max_payload < payload: reasons.append("最大载荷不足")
            if d.endurance is not None and d.endurance < endurance: reasons.append("续航时间不足")

            if reasons:
                drones_fail.append({'device': d.model, 'brand': d.brand, 'reasons': reasons})
            else:
                drones_pass.append({'id': d.id, 'device_id': d.device_id, 'model': d.model, 'brand': d.brand})

        sensors_all = Sensor.query.all()
        sensors_pass, sensors_fail = [], []
        for s in sensors_all:
            reasons = []
            if s.price is not None and s.price > budget: reasons.append("价格超出预算")
            if s.weight is not None and s.weight > payload: reasons.append("重量超过载荷")

            if required_funcs:
                func_str = s.functions or ''
                func_list = [f.strip() for f in func_str.split(',') if f.strip()]
                covered = any(req in func_list for req in required_funcs)
                if not covered:
                    reasons.append(f"功能不覆盖要求({','.join(required_funcs)})")

            if s.detection_range is not None and s.detection_range < det_range:
                reasons.append("探测距离不足")

            if reasons:
                sensors_fail.append({'device': s.model, 'brand': s.brand, 'reasons': reasons})
            else:
                sensors_pass.append({'id': s.id, 'device_id': s.device_id, 'model': s.model, 'brand': s.brand})

        computers_all = Computer.query.all()
        computers_pass, computers_fail = [], []
        for c in computers_all:
            reasons = []
            if c.price is not None and c.price > budget: reasons.append("价格超出预算")
            if c.weight is not None and c.weight > payload: reasons.append("重量超过载荷")

            if reasons:
                computers_fail.append({'device': c.model, 'brand': c.brand, 'reasons': reasons})
            else:
                computers_pass.append({'id': c.id, 'device_id': c.device_id, 'model': c.model, 'brand': c.brand})

        return jsonify({
            'drones': {'pass': drones_pass, 'fail': drones_fail},
            'sensors': {'pass': sensors_pass, 'fail': sensors_fail},
            'computers': {'pass': computers_pass, 'fail': computers_fail}
        })

    # ==================== V2 接口 ====================
    @app.route('/api/v2/devices', methods=['GET'])
    def get_v2_devices():
        device_type = request.args.get('type', '').lower()
        conn = sqlite3.connect('data/low_altitude_selection.db')
        cursor = conn.cursor()
        cursor.execute("SELECT device_id, raw_data FROM v2_compatibility")
        rows = cursor.fetchall()
        conn.close()
        
        results = []
        for device_id, raw_json in rows:
            data = json.loads(raw_json)
            if device_type == 'uav' and '无人机ID' in data:
                results.append(data)
            elif device_type == 'sensor' and '传感器ID' in data:
                results.append(data)
            elif device_type == 'computer' and '计算平台ID' in data:
                results.append(data)
            elif not device_type:
                results.append(data)
                
        return jsonify({'status': 'success', 'total': len(results), 'data': results})

    @app.route('/api/v2/compatibility', methods=['POST'])
    def check_v2_compatibility():
        data = request.get_json(silent=True)
        if not data:
            return jsonify({'error': '请求体需为JSON'}), 400
        
        uav_id = data.get('uav_id')
        sensor_id = data.get('sensor_id')
        computer_id = data.get('computer_id')
        # 兼容性检查接口保留手动传规则的能力，也支持自动推断
        enabled_rules = data.get('enabled_rules') or _infer_enabled_rules(data.get('requirements', {}))
        
        conn = sqlite3.connect('data/low_altitude_selection.db')
        cursor = conn.cursor()
        
        def get_device(dev_id):
            if not dev_id: return None
            cursor.execute("SELECT raw_data FROM v2_compatibility WHERE device_id = ?", (dev_id,))
            row = cursor.fetchone()
            return json.loads(row[0]) if row else None
            
        uav = get_device(uav_id)
        sensor = get_device(sensor_id)
        computer = get_device(computer_id)
        conn.close()
        
        if not all([uav, sensor, computer]):
            return jsonify({'status': 'error', 'message': '部分设备ID不存在'}), 404
            
        combo_data = {
            'uav': uav,
            'sensor': sensor,
            'computer': computer,
            'requirements': data.get('requirements', {})
        }
        
        overall_status, details = evaluate_combo(combo_data, enabled_rules)
        return jsonify({'status': 'success', 'overall_status': overall_status, 'details': details})

    @app.route('/api/v2/recommend', methods=['POST'])
    def recommend_v2():
        data = request.get_json(silent=True)
        if not data:
            return jsonify({'error': '请求体需为JSON'}), 400
        
        requirements = data.get('requirements', {})
        
        # 【关键修复】后端自动根据 requirements 推断启用的规则
        # 如果前端强制传了 enabled_rules，则使用前端的；否则后端自动推断
        enabled_rules = data.get('enabled_rules')
        if not enabled_rules:
            enabled_rules = _infer_enabled_rules(requirements)
        
        conn = sqlite3.connect('data/low_altitude_selection.db')
        cursor = conn.cursor()
        cursor.execute("SELECT device_id, raw_data FROM v2_compatibility")
        rows = cursor.fetchall()
        conn.close()
        
        all_devices = {row[0]: json.loads(row[1]) for row in rows}
        
        uavs = [d for d in all_devices.values() if '无人机ID' in d]
        sensors = [d for d in all_devices.values() if '传感器ID' in d]
        computers = [d for d in all_devices.values() if '计算平台ID' in d]
        
        recommendations = []
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
                    
                    if status in ['pass', 'manual_review']:
                        recommendations.append({
                            'status': status,
                            'details': details,
                            'uav': uav.get('无人机ID'),
                            'sensor': sensor.get('传感器ID'),
                            'computer': computer.get('计算平台ID')
                        })
        
        # 【关键修复】把 pass 和 manual_review 彻底分开返回
        pass_list = [item for item in recommendations if item['status'] == 'pass']
        manual_review_list = [item for item in recommendations if item['status'] == 'manual_review']

        # 为每个组合补充 reason 解释文本
        for item in pass_list:
            item['reason'] = "满足所有启用的硬性约束，推荐优先使用。"
        for item in manual_review_list:
            missing_rules = [d['rule_id'] for d in item['details'] if d['status'] == 'manual_review']
            item['reason'] = f"数据存在缺失，需人工确认以下规则: {', '.join(missing_rules)}"

        # 各自的排序逻辑
        pass_list.sort(key=lambda x: x.get('uav', ''))
        manual_review_list.sort(
            key=lambda x: len([d for d in x['details'] if d['status'] == 'manual_review'])
        )

        # 为了兼容旧前端，额外提供一个合并的 top_3
        combined = pass_list + manual_review_list
        top_3 = combined[:3]

        # 返回分开的列表
        return jsonify({
            'status': 'success',
            'enabled_rules': enabled_rules,
            'total_found': len(recommendations),
            'total_pass': len(pass_list),
            'total_manual_review': len(manual_review_list),
            'pass_list': pass_list,                   # 完全分开的 pass 列表
            'manual_review_list': manual_review_list, # 完全分开的 manual_review 列表
            'top_3': top_3                            # 兼容旧字段
        })

    # ==================== V2 健康检查 ====================
    @app.route('/api/health', methods=['GET'])
    def health_check():
        conn = sqlite3.connect('data/low_altitude_selection.db')
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM drones")
        drones_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM sensors")
        sensors_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM computers")
        computers_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM v2_compatibility WHERE raw_data LIKE '%\"数据状态\": \"verified\"%'")
        verified_total = cursor.fetchone()[0]
        
        conn.close()
        
        return jsonify({
            "status": "ok",
            "database": "ok",
            "compatibility_version": "v2",
            "catalog_counts": {
                "drones": drones_count,
                "sensors": sensors_count,
                "computers": computers_count
            },
            "verified_counts": {
                "drones": verified_total,
                "sensors": 0,
                "computers": 0
            }
        })

    return app


if __name__ == '__main__':
    app = create_app()
    app.run(debug=True, host='0.0.0.0', port=5000)