from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

from sqlalchemy import desc, or_, select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.b_interface_alarm import BInterfaceAlarmHistory, BInterfaceCurrentAlarm
from app.modules.b_interface.xml_protocol import AlarmRecord, ParsedBInterfaceMessage


SessionFactory = Callable[[], Session]
_session_factory: SessionFactory = SessionLocal


def set_session_factory(factory: SessionFactory) -> None:
    global _session_factory
    _session_factory = factory


def reset_session_factory() -> None:
    global _session_factory
    _session_factory = SessionLocal


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_alarm_timestamp(value: str) -> datetime | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _duration_seconds(begin_time: str | None, end_time: str | None) -> int | None:
    begin_dt = _parse_alarm_timestamp(begin_time or "")
    end_dt = _parse_alarm_timestamp(end_time or "")
    if begin_dt is None or end_dt is None:
        return None
    return max(0, int((end_dt - begin_dt).total_seconds()))


def _row_to_dict(row: BInterfaceCurrentAlarm | BInterfaceAlarmHistory, source: str) -> dict:
    payload = {
        "fsu_id": row.fsu_id,
        "fsu_code": row.fsu_code,
        "serial_no": row.serial_no,
        "alarm_id": row.alarm_id,
        "device_id": row.device_id,
        "device_code": row.device_code,
        "alarm_time": row.alarm_time,
        "alarm_level": row.alarm_level,
        "alarm_flag": row.alarm_flag,
        "alarm_desc": row.alarm_desc,
        "first_seen_at": row.first_seen_at.isoformat() if row.first_seen_at else None,
        "last_seen_at": row.last_seen_at.isoformat() if row.last_seen_at else None,
        "status": row.status,
        "source": source,
    }
    if isinstance(row, BInterfaceAlarmHistory):
        payload.update(
            {
                "begin_time": row.begin_time,
                "end_time": row.end_time,
                "cleared_at": row.cleared_at.isoformat() if row.cleared_at else None,
                "duration_seconds": row.duration_seconds,
            }
        )
    return payload


def _normalized_alarm(parsed: ParsedBInterfaceMessage, alarm: AlarmRecord) -> dict:
    return {
        "fsu_id": (alarm.fsu_id or parsed.fsu_id or parsed.fsu_code or "").strip(),
        "fsu_code": (alarm.fsu_code or parsed.fsu_code or parsed.fsu_id or "").strip(),
        "serial_no": (alarm.serial_no or "").strip(),
        "alarm_id": (alarm.id or "").strip(),
        "device_id": (alarm.device_id or "").strip(),
        "device_code": (alarm.device_code or "").strip(),
        "alarm_time": (alarm.alarm_time or "").strip(),
        "alarm_level": (alarm.alarm_level or "").strip(),
        "alarm_flag": (alarm.alarm_flag or "").strip().upper(),
        "alarm_desc": (alarm.alarm_desc or "").strip(),
    }


def _find_current_alarm(session: Session, normalized: dict) -> BInterfaceCurrentAlarm | None:
    fsu_id = normalized["fsu_id"]
    if not fsu_id:
        return None
    if normalized["serial_no"]:
        return session.scalar(
            select(BInterfaceCurrentAlarm)
            .where(
                BInterfaceCurrentAlarm.fsu_id == fsu_id,
                BInterfaceCurrentAlarm.serial_no == normalized["serial_no"],
            )
            .order_by(desc(BInterfaceCurrentAlarm.last_seen_at), desc(BInterfaceCurrentAlarm.id))
            .limit(1)
        )
    if normalized["alarm_id"] and (normalized["device_id"] or normalized["device_code"]):
        device_value = normalized["device_id"] or normalized["device_code"]
        return session.scalar(
            select(BInterfaceCurrentAlarm)
            .where(
                BInterfaceCurrentAlarm.fsu_id == fsu_id,
                BInterfaceCurrentAlarm.alarm_id == normalized["alarm_id"],
                or_(
                    BInterfaceCurrentAlarm.device_id == device_value,
                    BInterfaceCurrentAlarm.device_code == device_value,
                ),
            )
            .order_by(desc(BInterfaceCurrentAlarm.last_seen_at), desc(BInterfaceCurrentAlarm.id))
            .limit(1)
        )
    return None


def _apply_current_row(row: BInterfaceCurrentAlarm, normalized: dict, now: datetime, *, preserve_first_seen: bool) -> None:
    row.fsu_id = normalized["fsu_id"] or row.fsu_id
    row.fsu_code = normalized["fsu_code"] or row.fsu_code
    row.serial_no = normalized["serial_no"] or row.serial_no
    row.alarm_id = normalized["alarm_id"] or row.alarm_id
    row.device_id = normalized["device_id"] or row.device_id
    row.device_code = normalized["device_code"] or row.device_code
    row.alarm_time = normalized["alarm_time"] or row.alarm_time
    row.alarm_level = normalized["alarm_level"] or row.alarm_level
    row.alarm_flag = normalized["alarm_flag"] or row.alarm_flag
    row.alarm_desc = normalized["alarm_desc"] or row.alarm_desc
    row.status = "active"
    if not preserve_first_seen or row.first_seen_at is None:
        row.first_seen_at = now
    row.last_seen_at = now


def _history_from_current(
    current: BInterfaceCurrentAlarm | None,
    normalized: dict,
    now: datetime,
    *,
    status: str,
) -> BInterfaceAlarmHistory:
    begin_time = normalized["alarm_time"]
    first_seen_at = now
    if current is not None:
        begin_time = current.alarm_time or begin_time
        first_seen_at = current.first_seen_at or now
    end_time = normalized["alarm_time"] or (current.alarm_time if current is not None else "")
    return BInterfaceAlarmHistory(
        fsu_id=normalized["fsu_id"] or (current.fsu_id if current is not None else ""),
        fsu_code=normalized["fsu_code"] or (current.fsu_code if current is not None else None),
        serial_no=normalized["serial_no"] or (current.serial_no if current is not None else None),
        alarm_id=normalized["alarm_id"] or (current.alarm_id if current is not None else None),
        device_id=normalized["device_id"] or (current.device_id if current is not None else None),
        device_code=normalized["device_code"] or (current.device_code if current is not None else None),
        alarm_time=end_time or (current.alarm_time if current is not None else None),
        alarm_level=normalized["alarm_level"] or (current.alarm_level if current is not None else None),
        alarm_flag=normalized["alarm_flag"] or (current.alarm_flag if current is not None else None),
        alarm_desc=normalized["alarm_desc"] or (current.alarm_desc if current is not None else None),
        first_seen_at=first_seen_at,
        last_seen_at=now,
        status=status,
        begin_time=begin_time or None,
        end_time=end_time or None,
        cleared_at=now,
        duration_seconds=_duration_seconds(begin_time or None, end_time or None),
    )


def process_send_alarm(parsed: ParsedBInterfaceMessage) -> list[dict]:
    if parsed.message_name != "SEND_ALARM" or not parsed.alarms:
        return []
    session = _session_factory()
    now = _now()
    processed: list[dict] = []
    try:
        for alarm in parsed.alarms:
            normalized = _normalized_alarm(parsed, alarm)
            if not normalized["fsu_id"]:
                continue
            current = _find_current_alarm(session, normalized)
            flag = normalized["alarm_flag"]
            if flag == "BEGIN":
                if current is None:
                    current = BInterfaceCurrentAlarm(fsu_id=normalized["fsu_id"])
                    session.add(current)
                    _apply_current_row(current, normalized, now, preserve_first_seen=False)
                else:
                    _apply_current_row(current, normalized, now, preserve_first_seen=True)
                processed.append(_row_to_dict(current, "current"))
                continue
            if flag == "END":
                history = _history_from_current(current, normalized, now, status="cleared" if current is not None else "end_only")
                session.add(history)
                if current is not None:
                    session.delete(current)
                processed.append(_row_to_dict(history, "history"))
                continue
            history = _history_from_current(current, normalized, now, status="unknown")
            session.add(history)
            processed.append(_row_to_dict(history, "history"))
        session.commit()
        return processed
    finally:
        session.close()


def list_current_alarms(limit: int = 100) -> list[dict]:
    session = _session_factory()
    try:
        rows = session.scalars(
            select(BInterfaceCurrentAlarm)
            .order_by(desc(BInterfaceCurrentAlarm.last_seen_at), desc(BInterfaceCurrentAlarm.updated_at))
            .limit(limit)
        ).all()
        return [_row_to_dict(row, "current") for row in rows]
    finally:
        session.close()


def list_alarm_history(limit: int = 100) -> list[dict]:
    session = _session_factory()
    try:
        rows = session.scalars(
            select(BInterfaceAlarmHistory)
            .order_by(desc(BInterfaceAlarmHistory.cleared_at), desc(BInterfaceAlarmHistory.updated_at))
            .limit(limit)
        ).all()
        return [_row_to_dict(row, "history") for row in rows]
    finally:
        session.close()


def list_recent_alarms(limit: int = 100) -> list[dict]:
    current = list_current_alarms(limit)
    history = list_alarm_history(limit)

    def sort_key(item: dict) -> tuple[str, str]:
        return (
            item.get("last_seen_at") or item.get("cleared_at") or "",
            item.get("status") or "",
        )

    combined = sorted(current + history, key=sort_key, reverse=True)
    return combined[:limit]
