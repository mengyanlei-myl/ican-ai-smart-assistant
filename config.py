import os
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'data', 'low_altitude_selection.db')
UAV_EXCEL_PATH = os.path.join(BASE_DIR, 'data', 'uav_model_database.xlsx')
SENSOR_EXCEL_PATH = os.path.join(BASE_DIR, 'data', 'sensor_model_database.xlsx')
COMPUTER_EXCEL_PATH = os.path.join(BASE_DIR, 'data', 'compute_platform_database.xlsx')
class Config:
    SQLALCHEMY_DATABASE_URI = f'sqlite:///{DB_PATH}'
    SQLALCHEMY_TRACK_MODIFICATIONS = False