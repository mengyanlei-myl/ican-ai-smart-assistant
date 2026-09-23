"""Import the 791-device catalog and merge the verified compatibility layer.

The import is an atomic, idempotent snapshot: running it repeatedly produces the
same catalog, compatibility, and evidence rows. Empty spreadsheet cells remain
NULL/JSON null; they are never coerced to zero.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "low_altitude_selection.db"
V2_DIR = DATA_DIR / "compatibility" / "v2"

CATALOGS = {
    "uav": (DATA_DIR / "drone_database_v2_cleaned.xlsx", "drones", "无人机ID"),
    "sensor": (DATA_DIR / "sensor_database_v2_cleaned.xlsx", "sensors", "传感器ID"),
    "computer": (DATA_DIR / "compute_platform_database.xlsx", "computers", "计算平台ID"),
}

COMPATIBILITY_FILES = {
    "uav": (V2_DIR / "compatibility_specs_v2_completed.xlsx", "无人机兼容参数", "无人机ID", "检索证据"),
    "sensor": (V2_DIR / "sensor_compatibility_specs_v2_completed.xlsx", "传感器兼容参数", "传感器ID", "检索证据"),
    "computer": (V2_DIR / "computer_compatibility_specs_v2_completed.xlsx", "计算平台兼容参数", "计算平台ID", "检索证据"),
}


def clean_value(value: Any) -> Any:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


def row_dict(row: pd.Series) -> dict[str, Any]:
    return {str(key).strip(): clean_value(value) for key, value in row.items()}


def number(value: Any, scale: float = 1.0) -> float | None:
    value = clean_value(value)
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value) * scale
    match = re.search(r"[-+]?\d+(?:\.\d+)?", str(value).replace(",", ""))
    return float(match.group()) * scale if match else None


def json_text(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS drones (
            id INTEGER PRIMARY KEY AUTOINCREMENT, device_id TEXT, brand TEXT NOT NULL,
            model TEXT NOT NULL, max_payload REAL, endurance REAL, weight REAL,
            flight_range REAL, price REAL, power REAL, voltage TEXT,
            working_temperature TEXT, protection_level TEXT, source_url TEXT,
            update_date TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS sensors (
            id INTEGER PRIMARY KEY AUTOINCREMENT, device_id TEXT, category TEXT NOT NULL,
            brand TEXT NOT NULL, model TEXT NOT NULL, functions TEXT,
            detection_range REAL, accuracy TEXT, weight REAL, power REAL, voltage TEXT,
            interfaces TEXT, working_temperature TEXT, protection_level TEXT,
            price REAL, source_url TEXT, update_date TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS computers (
            id INTEGER PRIMARY KEY AUTOINCREMENT, device_id TEXT, brand TEXT NOT NULL,
            model TEXT NOT NULL, cpu TEXT, ram REAL, storage REAL, weight REAL,
            power REAL, voltage TEXT, interfaces TEXT, working_temperature TEXT,
            protection_level TEXT, price REAL, source_url TEXT, update_date TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS v2_compatibility (
            id INTEGER PRIMARY KEY AUTOINCREMENT, device_id TEXT UNIQUE,
            device_type TEXT, raw_data TEXT NOT NULL, catalog_data TEXT,
            evidence_count INTEGER NOT NULL DEFAULT 0, verification_status TEXT
        );
        CREATE TABLE IF NOT EXISTS verification_evidence (
            id INTEGER PRIMARY KEY AUTOINCREMENT, device_type TEXT NOT NULL,
            device_id TEXT NOT NULL, field_name TEXT, source_url TEXT,
            evidence_status TEXT, raw_data TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS import_state (
            import_name TEXT PRIMARY KEY, source_digest TEXT NOT NULL,
            imported_at TEXT NOT NULL, row_count INTEGER NOT NULL
        );
        """
    )
    additions = {
        "drones": {"raw_data": "TEXT", "data_status": "TEXT", "verification_status": "TEXT", "evidence_count": "INTEGER NOT NULL DEFAULT 0"},
        "sensors": {"raw_data": "TEXT", "data_status": "TEXT", "verification_status": "TEXT", "evidence_count": "INTEGER NOT NULL DEFAULT 0"},
        "computers": {"raw_data": "TEXT", "data_status": "TEXT", "verification_status": "TEXT", "evidence_count": "INTEGER NOT NULL DEFAULT 0"},
        "v2_compatibility": {"device_type": "TEXT", "catalog_data": "TEXT", "evidence_count": "INTEGER NOT NULL DEFAULT 0", "verification_status": "TEXT"},
    }
    for table, columns in additions.items():
        existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        for column, definition in columns.items():
            if column not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def load_id_mapping() -> dict[str, str]:
    path = V2_DIR / "device_id_mapping_v2.xlsx"
    frame = pd.read_excel(path, sheet_name="ID映射")
    mapping: dict[str, str] = {}
    for _, row in frame.iterrows():
        final_id = clean_value(row.get("最终采用ID"))
        if not final_id:
            continue
        for column in ("旧ID", "新ID", "最终采用ID"):
            source_id = clean_value(row.get(column))
            if source_id:
                mapping[str(source_id)] = str(final_id)
    return mapping


def load_compatibility(mapping: dict[str, str]):
    records: dict[tuple[str, str], dict[str, Any]] = {}
    evidence: list[tuple[str, str, dict[str, Any]]] = []
    for device_type, (path, sheet, id_column, evidence_sheet) in COMPATIBILITY_FILES.items():
        for _, row in pd.read_excel(path, sheet_name=sheet).iterrows():
            data = row_dict(row)
            original_id = data.get(id_column)
            if not original_id:
                raise ValueError(f"{path.name}: compatibility row has no {id_column}")
            device_id = mapping.get(str(original_id), str(original_id))
            data[id_column] = device_id
            records[(device_type, device_id)] = data
        for _, row in pd.read_excel(path, sheet_name=evidence_sheet).iterrows():
            data = row_dict(row)
            original_id = data.get(id_column)
            if not original_id:
                raise ValueError(f"{path.name}: evidence row has no {id_column}")
            device_id = mapping.get(str(original_id), str(original_id))
            data[id_column] = device_id
            evidence.append((device_type, device_id, data))
    return records, evidence


def catalog_projection(device_type: str, data: dict[str, Any]) -> dict[str, Any]:
    if device_type == "uav":
        return {
            "brand": data.get("厂家"), "model": data.get("型号"),
            "max_payload": number(data.get("标准化最大有效载荷kg") or data.get("最大有效载荷kg")),
            "endurance": number(data.get("最大飞行时间min")), "weight": number(data.get("空机重量kg")),
            "flight_range": None, "price": number(data.get("价格参考")),
            "power": number(data.get("最大外设供电W")), "voltage": data.get("可用电压"),
            "working_temperature": None, "protection_level": data.get("防护等级"),
            "source_url": data.get("官方链接"), "data_status": data.get("标准化数据状态") or data.get("采集状态"),
        }
    if device_type == "sensor":
        return {
            "category": data.get("标准化类别") or data.get("传感器子类") or data.get("传感器大类"),
            "brand": data.get("厂家"), "model": data.get("型号"), "functions": data.get("完整名称"),
            "detection_range": number(data.get("探测距离/量程(m)")), "accuracy": data.get("精度"),
            "weight": number(data.get("标准化重量(kg)")) if data.get("标准化重量(kg)") is not None else number(data.get("重量(g)"), 0.001),
            "power": number(data.get("功耗(W)")), "voltage": None, "interfaces": data.get("接口"),
            "working_temperature": data.get("工作温度"), "protection_level": data.get("防护等级"),
            "price": number(data.get("标准化参考价格(CNY)")), "source_url": data.get("官方链接"),
            "data_status": data.get("标准化数据状态") or data.get("采集状态"),
        }
    return {
        "brand": data.get("厂家"), "model": data.get("型号"),
        "cpu": "; ".join(str(v) for v in (data.get("CPU"), data.get("GPU/NPU/FPGA")) if v),
        "ram": number(data.get("内存")), "storage": number(data.get("板载存储")),
        "weight": number(data.get("重量(g)"), 0.001), "power": number(data.get("功耗/功耗模式(W)")),
        "voltage": data.get("供电要求"),
        "interfaces": "; ".join(str(v) for v in (data.get("USB/网络"), data.get("相机/高速扩展"), data.get("UART/CAN/GPIO")) if v),
        "working_temperature": data.get("工作温度(°C)"), "protection_level": None,
        "price": number(data.get("官方价格/采购状态")), "source_url": data.get("官方链接"),
        "data_status": data.get("采集状态"),
    }


def source_digest(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def import_all(db_path: Path = DB_PATH) -> dict[str, int | str]:
    source_paths = [item[0] for item in CATALOGS.values()]
    source_paths += [item[0] for item in COMPATIBILITY_FILES.values()]
    source_paths.append(V2_DIR / "device_id_mapping_v2.xlsx")
    missing = [str(path) for path in source_paths if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing import sources: " + ", ".join(missing))

    mapping = load_id_mapping()
    compatibility, evidence = load_compatibility(mapping)
    evidence_counts: dict[tuple[str, str], int] = {}
    for device_type, device_id, _ in evidence:
        key = (device_type, device_id)
        evidence_counts[key] = evidence_counts.get(key, 0) + 1

    conn = sqlite3.connect(db_path)
    counts: dict[str, int | str] = {}
    try:
        ensure_schema(conn)
        conn.execute("BEGIN IMMEDIATE")
        for table in ("drones", "sensors", "computers", "v2_compatibility", "verification_evidence"):
            conn.execute(f"DELETE FROM {table}")
            conn.execute("DELETE FROM sqlite_sequence WHERE name = ?", (table,))

        for device_type, (path, table, id_column) in CATALOGS.items():
            frame = pd.read_excel(path)
            seen: set[str] = set()
            for _, row in frame.iterrows():
                catalog = row_dict(row)
                raw_id = catalog.get(id_column)
                if not raw_id:
                    raise ValueError(f"{path.name}: catalog row has no {id_column}")
                device_id = mapping.get(str(raw_id), str(raw_id))
                if device_id in seen:
                    raise ValueError(f"{path.name}: duplicate final ID {device_id}")
                seen.add(device_id)
                catalog[id_column] = device_id
                trusted = compatibility.get((device_type, device_id))
                merged = dict(catalog)
                if trusted:
                    merged.update({key: value for key, value in trusted.items() if value is not None})
                projected = catalog_projection(device_type, merged)
                verification_status = trusted.get("数据状态") if trusted else None
                common = {
                    "device_id": device_id, **projected, "raw_data": json_text(merged),
                    "verification_status": verification_status,
                    "evidence_count": evidence_counts.get((device_type, device_id), 0),
                    "update_date": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
                }
                columns = list(common)
                conn.execute(
                    f"INSERT INTO {table} ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                    [common[column] for column in columns],
                )
            counts[table] = len(seen)

        catalog_by_key: dict[tuple[str, str], dict[str, Any]] = {}
        for device_type, (_, table, _) in CATALOGS.items():
            for device_id, raw in conn.execute(f"SELECT device_id, raw_data FROM {table}"):
                catalog_by_key[(device_type, device_id)] = json.loads(raw)

        for (device_type, device_id), trusted in compatibility.items():
            catalog = catalog_by_key.get((device_type, device_id))
            # The verified recommendation layer is intentionally allowed to
            # contain curated devices outside the broad 791-row catalog.
            # Overlapping IDs are enriched with catalog data; curated-only IDs
            # retain their verified record without inflating catalog counts.
            merged = dict(catalog or {})
            merged.update({key: value for key, value in trusted.items() if value is not None})
            conn.execute(
                "INSERT INTO v2_compatibility (device_id,device_type,raw_data,catalog_data,evidence_count,verification_status) VALUES (?,?,?,?,?,?)",
                (device_id, device_type, json_text(merged), json_text(catalog) if catalog else None, evidence_counts.get((device_type, device_id), 0), trusted.get("数据状态")),
            )

        for device_type, device_id, data in evidence:
            conn.execute(
                "INSERT INTO verification_evidence (device_type,device_id,field_name,source_url,evidence_status,raw_data) VALUES (?,?,?,?,?,?)",
                (device_type, device_id, data.get("字段名称"), data.get("官方链接") or data.get("官方来源链接"), data.get("证据状态") or data.get("结论"), json_text(data)),
            )

        counts["compatibility"] = len(compatibility)
        counts["evidence"] = len(evidence)
        counts["total_catalog"] = sum(int(counts[name]) for name in ("drones", "sensors", "computers"))
        digest = source_digest(source_paths)
        counts["source_digest"] = digest
        conn.execute(
            "INSERT INTO import_state(import_name,source_digest,imported_at,row_count) VALUES(?,?,?,?) "
            "ON CONFLICT(import_name) DO UPDATE SET source_digest=excluded.source_digest, imported_at=excluded.imported_at, row_count=excluded.row_count",
            ("catalog_v2", digest, datetime.now(timezone.utc).isoformat(), counts["total_catalog"]),
        )
        conn.commit()
        return counts
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    result = import_all()
    print(json.dumps(result, ensure_ascii=False, indent=2))
