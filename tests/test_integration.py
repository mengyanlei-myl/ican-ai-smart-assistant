import hashlib
import json
import sqlite3

from app import create_app
from import_all import import_all
from rules_engine import evaluate_combo


SNAPSHOT_TABLES = (
    "drones",
    "sensors",
    "computers",
    "v2_compatibility",
    "verification_evidence",
)


def snapshot(conn):
    payload = []
    for table in SNAPSHOT_TABLES:
        payload.extend(conn.execute(f"SELECT * FROM {table} ORDER BY id").fetchall())
    return hashlib.sha256(repr(payload).encode("utf-8")).hexdigest()


def test_import_is_idempotent_and_has_791_catalog_rows(tmp_path):
    db_path = tmp_path / "integration.db"
    first = import_all(db_path)
    with sqlite3.connect(db_path) as conn:
        first_snapshot = snapshot(conn)
    second = import_all(db_path)
    with sqlite3.connect(db_path) as conn:
        second_snapshot = snapshot(conn)
        counts = {
            table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in SNAPSHOT_TABLES
        }
        unique_counts = {
            table: conn.execute(f"SELECT COUNT(DISTINCT device_id) FROM {table}").fetchone()[0]
            for table in ("drones", "sensors", "computers", "v2_compatibility")
        }
    assert first["source_digest"] == second["source_digest"]
    assert first_snapshot == second_snapshot
    assert counts == {
        "drones": 281,
        "sensors": 460,
        "computers": 50,
        "v2_compatibility": 25,
        "verification_evidence": 214,
    }
    assert unique_counts == {"drones": 281, "sensors": 460, "computers": 50, "v2_compatibility": 25}


def test_trusted_layer_is_merged_and_nulls_remain_null(tmp_path):
    db_path = tmp_path / "trusted.db"
    import_all(db_path)
    with sqlite3.connect(db_path) as conn:
        raw_data, evidence_count, status = conn.execute(
            "SELECT raw_data, evidence_count, verification_status FROM v2_compatibility WHERE device_id = ?",
            ("Stereolabs_ZED_2i",),
        ).fetchone()
        all_payloads = [json.loads(row[0]) for row in conn.execute("SELECT raw_data FROM v2_compatibility")]
    data = json.loads(raw_data)
    assert data["传感器ID"] == "Stereolabs_ZED_2i"
    assert evidence_count > 0
    assert status == "verified"
    assert any(value is None for payload in all_payloads for value in payload.values())


def test_health_endpoint_reports_integrated_counts():
    app = create_app()
    response = app.test_client().get("/api/health")
    assert response.status_code == 200
    body = response.get_json()
    assert body["catalog_counts"] == {"drones": 281, "sensors": 460, "computers": 50}
    assert body["verification_evidence"] == 214


def test_missing_rule_data_requires_manual_review():
    combo = {"uav": {}, "sensor": {}, "computer": {}, "requirements": {"任务载荷/安装余量(kg)": 0.5}}
    status, _ = evaluate_combo(combo, ["R01"])
    assert status == "manual_review"
