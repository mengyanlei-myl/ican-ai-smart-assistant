import sqlite3
import json
from flask_cors import CORS
from flask import Flask, request, jsonify
from models import db, Drone, Sensor, Computer
from config import Config, DB_PATH
from rules_engine import evaluate_combo
from decision_service import (
    ApiValidationError,
    DeviceNotFoundError,
    check_compatibility,
    list_catalog,
    recommend,
    stats,
)
from semantic_recommendation_service import recommend_from_text


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


def create_app(config_override=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    app.config['DATABASE_PATH'] = DB_PATH
    if config_override:
        app.config.update(config_override)
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
        conn = sqlite3.connect(app.config['DATABASE_PATH'])
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
        
        conn = sqlite3.connect(app.config['DATABASE_PATH'])
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
        
        conn = sqlite3.connect(app.config['DATABASE_PATH'])
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

    # ==================== 阶段 7：目录、判定与推荐 API ====================
    def pagination_args():
        try:
            page = int(request.args.get('page', 1))
            page_size = int(request.args.get('page_size', 20))
        except (TypeError, ValueError):
            raise ApiValidationError('page 和 page_size 必须是整数')
        if page < 1:
            raise ApiValidationError('page 必须大于等于 1')
        if page_size < 1 or page_size > 100:
            raise ApiValidationError('page_size 必须在 1～100 之间')
        return page, page_size

    def catalog_response(device_type):
        page, page_size = pagination_args()
        verification_status = request.args.get('verification_status')
        if verification_status and verification_status not in {'verified', 'partial', 'catalog_only'}:
            raise ApiValidationError('verification_status 必须是 verified、partial 或 catalog_only')
        return list_catalog(
            app.config['DATABASE_PATH'], device_type,
            q=request.args.get('q'), page=page, page_size=page_size,
            verification_status=verification_status,
            brand=request.args.get('brand') or request.args.get('厂家'),
            category=request.args.get('category') or request.args.get('类别'),
        )

    @app.errorhandler(ApiValidationError)
    def handle_validation_error(error):
        return jsonify({'status': 'error', 'error': str(error)}), 400

    @app.errorhandler(DeviceNotFoundError)
    def handle_not_found(error):
        return jsonify({'status': 'error', 'error': str(error)}), 404

    @app.route('/api/v2/drones', methods=['GET'])
    def list_v2_drones():
        return jsonify(catalog_response('drone'))

    @app.route('/api/v2/sensors', methods=['GET'])
    def list_v2_sensors():
        return jsonify(catalog_response('sensor'))

    @app.route('/api/v2/computers', methods=['GET'])
    def list_v2_computers():
        return jsonify(catalog_response('computer'))

    @app.route('/api/v2/compatibility/check', methods=['POST'])
    def compatibility_check_v2():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            raise ApiValidationError('请求体必须是 JSON 对象')
        drone_id = payload.get('drone_id')
        sensor_ids = payload.get('sensor_ids')
        computer_id = payload.get('computer_id')
        requirements = payload.get('task_requirements', {})
        enabled_rules = payload.get('enabled_rules')
        if not isinstance(drone_id, str) or not drone_id.strip():
            raise ApiValidationError('drone_id 必须是非空字符串')
        if not isinstance(sensor_ids, list) or not sensor_ids or any(not isinstance(item, str) or not item.strip() for item in sensor_ids):
            raise ApiValidationError('sensor_ids 必须是包含至少一个非空 ID 的数组')
        if len(set(sensor_ids)) != len(sensor_ids):
            raise ApiValidationError('sensor_ids 不得重复')
        if not isinstance(computer_id, str) or not computer_id.strip():
            raise ApiValidationError('computer_id 必须是非空字符串')
        if not isinstance(requirements, dict):
            raise ApiValidationError('task_requirements 必须是对象')
        if enabled_rules is not None:
            if not isinstance(enabled_rules, list) or not enabled_rules or any(rule not in {'R01', 'R02', 'R03', 'R04', 'R05', 'R06', 'R07'} for rule in enabled_rules):
                raise ApiValidationError('enabled_rules 必须是 R01～R07 的非空数组')
            if len(set(enabled_rules)) != len(enabled_rules):
                raise ApiValidationError('enabled_rules 不得重复')
        return jsonify(check_compatibility(app.config['DATABASE_PATH'], drone_id.strip(), [item.strip() for item in sensor_ids], computer_id.strip(), requirements, enabled_rules))

    @app.route('/api/v2/recommendations', methods=['POST'])
    def recommendations_v2():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            raise ApiValidationError('请求体必须是 JSON 对象')
        requirements = payload.get('requirements', {})
        if not isinstance(requirements, dict):
            raise ApiValidationError('requirements 必须是对象')
        top_n = payload.get('top_n', 10)
        if isinstance(top_n, bool) or not isinstance(top_n, int) or top_n < 1 or top_n > 50:
            raise ApiValidationError('top_n 必须是 1～50 的整数')
        allow_manual = payload.get('allow_manual_review', True)
        if not isinstance(allow_manual, bool):
            raise ApiValidationError('allow_manual_review 必须是布尔值')
        weights = payload.get('weights', {})
        if not isinstance(weights, dict):
            raise ApiValidationError('weights 必须是对象')
        return jsonify(recommend(app.config['DATABASE_PATH'], requirements, top_n, allow_manual, weights))

    @app.route('/api/v2/recommendations/semantic', methods=['POST'])
    def semantic_recommendations_v2():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            raise ApiValidationError('请求体必须是 JSON 对象')
        allowed_fields = {'text', 'top_n', 'allow_manual_review', 'weights', 'confirmed_requirements'}
        unknown_fields = sorted(set(payload) - allowed_fields)
        if unknown_fields:
            raise ApiValidationError(f"不允许的请求字段: {', '.join(unknown_fields)}")
        if 'text' not in payload:
            raise ApiValidationError('text 为必填字段')
        text = payload['text']
        if not isinstance(text, str):
            raise ApiValidationError('text 必须是字符串')
        top_n = payload.get('top_n', 10)
        if isinstance(top_n, bool) or not isinstance(top_n, int) or top_n < 1 or top_n > 50:
            raise ApiValidationError('top_n 必须是 1～50 的整数')
        allow_manual = payload.get('allow_manual_review', True)
        if not isinstance(allow_manual, bool):
            raise ApiValidationError('allow_manual_review 必须是布尔值')
        weights = payload.get('weights', {})
        if not isinstance(weights, dict):
            raise ApiValidationError('weights 必须是对象')
        confirmed_requirements = payload.get('confirmed_requirements', {})
        if not isinstance(confirmed_requirements, dict):
            raise ApiValidationError('confirmed_requirements 必须是对象')
        return jsonify(recommend_from_text(
            text, top_n, allow_manual, weights,
            confirmed_requirements=confirmed_requirements,
            db_path=app.config['DATABASE_PATH']
        ))

    @app.route('/api/v2/stats', methods=['GET'])
    def stats_v2():
        return jsonify(stats(app.config['DATABASE_PATH']))

    # ==================== V2 健康检查 ====================
    @app.route('/api/v2/health', methods=['GET'])
    @app.route('/api/health', methods=['GET'])
    def health_check():
        current = stats(app.config['DATABASE_PATH'])
        payload = {
            "status": "ok",
            "database": "ok",
            "compatibility_version": "v2",
            "catalog_counts": {
                "drones": current["catalog_counts"]["drone"],
                "sensors": current["catalog_counts"]["sensor"],
                "computers": current["catalog_counts"]["computer"],
            },
            "verified_counts": current["verification_status_counts"],
            "compatibility_records": current["compatibility_records"],
            "verification_evidence": current["field_evidence_records"],
        }
        if request.path == '/api/v2/health':
            payload["api_version"] = "v2"
        return jsonify(payload)

    return app


if __name__ == '__main__':
    app = create_app()
    app.run(debug=True, host='0.0.0.0', port=5000)
