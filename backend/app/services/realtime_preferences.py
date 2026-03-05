import json
import re
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.system_config import SystemConfig

IMPORTANT_POINT_KEYS_CONFIG_KEY = "realtime.important_point_keys"
DEFAULT_IMPORTANT_POINT_KEYS = [
    "mains_voltage",
    "mains_current",
    "mains_frequency",
    "battery_group_voltage",
    "battery_temp",
    "dc_branch_current",
    "room_temp",
    "room_humidity",
    "water_leak_status",
    "smoke_status",
    "ac_running_status",
    "ac_fault_status",
    "gen_running_status",
    "gen_fault_status",
    "door_access_status",
]
POINT_KEY_PATTERN = re.compile(r"^[a-zA-Z0-9_:\-]{1,64}$")


def _normalize_point_keys(point_keys: list[str]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in point_keys:
        key = str(item or "").strip()
        if not key:
            continue
        if not POINT_KEY_PATTERN.fullmatch(key):
            continue
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(key)
    return cleaned


def get_important_point_keys(db: Session) -> list[str]:
    row = db.scalar(select(SystemConfig).where(SystemConfig.config_key == IMPORTANT_POINT_KEYS_CONFIG_KEY))
    if row is None:
        return DEFAULT_IMPORTANT_POINT_KEYS.copy()

    try:
        raw = json.loads(row.config_value or "[]")
    except Exception:
        return DEFAULT_IMPORTANT_POINT_KEYS.copy()
    if not isinstance(raw, list):
        return DEFAULT_IMPORTANT_POINT_KEYS.copy()

    normalized = _normalize_point_keys([str(item) for item in raw])
    if not normalized:
        return DEFAULT_IMPORTANT_POINT_KEYS.copy()
    return normalized


def update_important_point_keys(db: Session, point_keys: list[str]) -> list[str]:
    normalized = _normalize_point_keys(point_keys)
    if not normalized:
        raise ValueError("关键监控项不能为空")

    row = db.scalar(select(SystemConfig).where(SystemConfig.config_key == IMPORTANT_POINT_KEYS_CONFIG_KEY))
    payload = json.dumps(normalized, ensure_ascii=False)
    now = datetime.now(timezone.utc)
    if row is None:
        row = SystemConfig(
            config_key=IMPORTANT_POINT_KEYS_CONFIG_KEY,
            config_value=payload,
            created_at=now,
            updated_at=now,
        )
        db.add(row)
    else:
        row.config_value = payload
        row.updated_at = now
    db.commit()
    return normalized
