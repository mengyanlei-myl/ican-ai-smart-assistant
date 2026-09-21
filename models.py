from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
db = SQLAlchemy()

class Drone(db.Model):
    __tablename__ = 'drones'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    device_id = db.Column(db.String(100), nullable=True)  # 新增：存储Excel中的无人机ID
    brand = db.Column(db.String(100), nullable=False)
    model = db.Column(db.String(100), nullable=False)
    max_payload = db.Column(db.Float, nullable=True)
    endurance = db.Column(db.Float, nullable=True)
    weight = db.Column(db.Float, nullable=True)
    flight_range = db.Column(db.Float, nullable=True)
    price = db.Column(db.Float, nullable=True)
    power = db.Column(db.Float, nullable=True)
    voltage = db.Column(db.String(50), nullable=True)
    working_temperature = db.Column(db.String(100), nullable=True)
    protection_level = db.Column(db.String(50), nullable=True)
    source_url = db.Column(db.String(255), nullable=True)
    update_date = db.Column(db.DateTime, default=datetime.now)

class Sensor(db.Model):
    __tablename__ = 'sensors'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    device_id = db.Column(db.String(100), nullable=True)  # 新增：存储Excel中的传感器ID
    category = db.Column(db.String(100), nullable=False)
    brand = db.Column(db.String(100), nullable=False)
    model = db.Column(db.String(100), nullable=False)
    functions = db.Column(db.String(255), nullable=True)
    detection_range = db.Column(db.Float, nullable=True)
    accuracy = db.Column(db.String(50), nullable=True)
    weight = db.Column(db.Float, nullable=True)
    power = db.Column(db.Float, nullable=True)
    voltage = db.Column(db.String(50), nullable=True)
    interfaces = db.Column(db.String(255), nullable=True)
    working_temperature = db.Column(db.String(100), nullable=True)
    protection_level = db.Column(db.String(50), nullable=True)
    price = db.Column(db.Float, nullable=True)
    source_url = db.Column(db.String(255), nullable=True)
    update_date = db.Column(db.DateTime, default=datetime.now)

class Computer(db.Model):
    __tablename__ = 'computers'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    device_id = db.Column(db.String(100), nullable=True)  # 新增：存储Excel中的计算平台ID
    brand = db.Column(db.String(100), nullable=False)
    model = db.Column(db.String(100), nullable=False)
    cpu = db.Column(db.String(100), nullable=True)
    ram = db.Column(db.Float, nullable=True)
    storage = db.Column(db.Float, nullable=True)
    weight = db.Column(db.Float, nullable=True)
    power = db.Column(db.Float, nullable=True)
    voltage = db.Column(db.String(50), nullable=True)
    interfaces = db.Column(db.String(255), nullable=True)
    working_temperature = db.Column(db.String(100), nullable=True)
    protection_level = db.Column(db.String(50), nullable=True)
    price = db.Column(db.Float, nullable=True)
    source_url = db.Column(db.String(255), nullable=True)
    update_date = db.Column(db.DateTime, default=datetime.now)