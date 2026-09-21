from flask_cors import CORS
from flask import Flask, request, jsonify
from models import db, Drone, Sensor, Computer
from config import Config

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
        if request.args.get('min_payload'):
            query = query.filter(Drone.max_payload >= float(request.args.get('min_payload')))
        if request.args.get('max_price'):
            query = query.filter(Drone.price <= float(request.args.get('max_price')))
        if request.args.get('brand'):
            query = query.filter(Drone.brand.ilike(f"%{request.args.get('brand')}%"))
        drones = query.all()
        return jsonify([{
            'id': d.id,
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
        if request.args.get('category'):
            query = query.filter(Sensor.category.ilike(f"%{request.args.get('category')}%"))
        if request.args.get('max_price'):
            query = query.filter(Sensor.price <= float(request.args.get('max_price')))
        if request.args.get('min_detection_range'):
            query = query.filter(Sensor.detection_range >= float(request.args.get('min_detection_range')))
        if request.args.get('function'):
            query = query.filter(Sensor.functions.ilike(f"%{request.args.get('function')}%"))
        sensors = query.all()
        return jsonify([{
            'id': s.id,
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
        if request.args.get('min_ram'):
            query = query.filter(Computer.ram >= float(request.args.get('min_ram')))
        if request.args.get('max_price'):
            query = query.filter(Computer.price <= float(request.args.get('max_price')))
        if request.args.get('brand'):
            query = query.filter(Computer.brand.ilike(f"%{request.args.get('brand')}%"))
        computers = query.all()
        return jsonify([{
            'id': c.id,
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
        data = request.get_json()
        if not data:
            return jsonify({'error': '请求体需为JSON'}), 400

        budget = data.get('budget', float('inf'))
        payload = data.get('payload', 0)
        endurance = data.get('endurance', 0)
        required_funcs = data.get('required_functions', [])
        det_range = data.get('detection_range', 0)

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
                drones_fail.append({'device': d.model, 'brand': d.brand, 'reasons': reasons})
            else:
                drones_pass.append({'id': d.id, 'model': d.model, 'brand': d.brand})

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
                covered = any(req in func_list for req in required_funcs)
                if not covered:
                    reasons.append(f"功能不覆盖要求({','.join(required_funcs)})")
            if s.detection_range is not None and s.detection_range < det_range:
                reasons.append("探测距离不足")
            if reasons:
                sensors_fail.append({'device': s.model, 'brand': s.brand, 'reasons': reasons})
            else:
                sensors_pass.append({'id': s.id, 'model': s.model, 'brand': s.brand})

        computers_all = Computer.query.all()
        computers_pass, computers_fail = [], []
        for c in computers_all:
            reasons = []
            if c.price is not None and c.price > budget:
                reasons.append("价格超出预算")
            if c.weight is not None and c.weight > payload:
                reasons.append("重量超过载荷")
            if reasons:
                computers_fail.append({'device': c.model, 'brand': c.brand, 'reasons': reasons})
            else:
                computers_pass.append({'id': c.id, 'model': c.model, 'brand': c.brand})

        return jsonify({
            'drones': {'pass': drones_pass, 'fail': drones_fail},
            'sensors': {'pass': sensors_pass, 'fail': sensors_fail},
            'computers': {'pass': computers_pass, 'fail': computers_fail}
        })

    return app

if __name__ == '__main__':
    app = create_app()
    app.run(debug=True, host='0.0.0.0', port=5000)