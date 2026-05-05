from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.b_interface_fsu_status import BInterfaceFsuStatus
from app.modules.b_interface.xml_protocol import ParsedBInterfaceMessage


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


def _device_codes(parsed: ParsedBInterfaceMessage) -> list[str]:
    return [device.code or device.id for device in parsed.devices if device.code or device.id]


def _to_dict(row: BInterfaceFsuStatus) -> dict:
    return {
        "fsu_id": row.fsu_id,
        "fsu_code": row.fsu_code,
        "fsu_ip": row.fsu_ip,
        "mac_id": row.mac_id,
        "reg_mode": row.reg_mode,
        "fsu_vendor": row.fsu_vendor,
        "fsu_type": row.fsu_type,
        "fsu_class": row.fsu_class,
        "version": row.version,
        "dict_version": row.dict_version,
        "device_list": row.device_list or [],
        "last_login_at": row.last_login_at.isoformat() if row.last_login_at else None,
        "last_seen_at": row.last_seen_at.isoformat() if row.last_seen_at else None,
        "remote_addr": row.remote_addr,
    }


def upsert_login_status(parsed: ParsedBInterfaceMessage, remote_addr: str) -> dict | None:
    fsu_id = (parsed.fsu_id or parsed.fsu_code or "").strip()
    if not fsu_id:
        return None
    now = _now()
    session = _session_factory()
    try:
        row = session.scalar(select(BInterfaceFsuStatus).where(BInterfaceFsuStatus.fsu_id == fsu_id))
        if row is None and parsed.fsu_code:
            row = session.scalar(select(BInterfaceFsuStatus).where(BInterfaceFsuStatus.fsu_code == parsed.fsu_code))
        if row is None:
            row = BInterfaceFsuStatus(fsu_id=fsu_id)
            session.add(row)
        row.fsu_id = fsu_id
        row.fsu_code = parsed.fsu_code or row.fsu_code
        row.fsu_ip = parsed.fsu_ip or row.fsu_ip
        row.mac_id = parsed.mac_id or row.mac_id
        row.reg_mode = parsed.reg_mode or row.reg_mode
        row.fsu_vendor = parsed.fsu_vendor or row.fsu_vendor
        row.fsu_type = parsed.fsu_type or row.fsu_type
        row.fsu_class = parsed.fsu_class or row.fsu_class
        row.version = parsed.version or row.version
        row.dict_version = parsed.dict_version or row.dict_version
        row.device_list = _device_codes(parsed)
        row.last_login_at = now
        row.last_seen_at = now
        row.remote_addr = remote_addr or row.remote_addr
        session.commit()
        session.refresh(row)
        return _to_dict(row)
    finally:
        session.close()


def list_fsu_statuses(limit: int = 100) -> list[dict]:
    session = _session_factory()
    try:
        rows = session.scalars(
            select(BInterfaceFsuStatus).order_by(desc(BInterfaceFsuStatus.last_login_at), desc(BInterfaceFsuStatus.updated_at)).limit(limit)
        ).all()
        return [_to_dict(row) for row in rows]
    finally:
        session.close()


def get_fsu_status(fsu_id: str) -> dict | None:
    session = _session_factory()
    try:
        row = session.scalar(select(BInterfaceFsuStatus).where(BInterfaceFsuStatus.fsu_id == fsu_id))
        return _to_dict(row) if row is not None else None
    finally:
        session.close()


def get_latest_login_status() -> dict | None:
    session = _session_factory()
    try:
        row = session.scalar(
            select(BInterfaceFsuStatus).order_by(desc(BInterfaceFsuStatus.last_login_at), desc(BInterfaceFsuStatus.updated_at)).limit(1)
        )
        return _to_dict(row) if row is not None else None
    finally:
        session.close()
