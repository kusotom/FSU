from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import html
import json
from typing import Callable
import xml.etree.ElementTree as ET

from sqlalchemy import delete, desc, or_, select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.b_interface_realtime import BInterfaceRealtime
from app.modules.b_interface.config_loader import resolve_signal_mapping
from app.modules.b_interface.logging_utils import sanitize_xml_text


SessionFactory = Callable[[], Session]
_session_factory: SessionFactory = SessionLocal


@dataclass(frozen=True)
class ParsedRealtimeValue:
    fsu_id: str
    fsu_code: str
    device_id: str
    device_code: str
    semaphore_id: str
    semaphore_type: str
    measured_val: str
    setup_val: str
    status: str
    mapping_status: str
    device_type: str
    standard_signal_id: str
    mapped_ids: tuple[str, ...]
    base_type_id: str
    local_signal_id: str
    signal_name: str
    unit: str
    signal_category: str
    signal_type: str
    channel_no: str
    signal_meanings: str
    raw_xml: str
    collected_at: datetime


def set_session_factory(factory: SessionFactory) -> None:
    global _session_factory
    _session_factory = factory


def reset_session_factory() -> None:
    global _session_factory
    _session_factory = SessionLocal


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    if ":" in tag:
        return tag.rsplit(":", 1)[1]
    return tag


def _child(root: ET.Element | None, name: str) -> ET.Element | None:
    if root is None:
        return None
    for elem in list(root):
        if _local_name(elem.tag) == name:
            return elem
    return None


def _text(root: ET.Element | None, names: tuple[str, ...], default: str = "") -> str:
    if root is None:
        return default
    for name in names:
        for elem in list(root):
            if _local_name(elem.tag) == name and elem.text:
                value = elem.text.strip()
                if value:
                    return value
    return default


def _attr(root: ET.Element | None, names: tuple[str, ...], default: str = "") -> str:
    if root is None:
        return default
    lowered = {key.lower(): value for key, value in root.attrib.items()}
    for name in names:
        if name in root.attrib and root.attrib[name]:
            return root.attrib[name].strip()
        if lowered.get(name.lower()):
            return lowered[name.lower()].strip()
    return default


def _parse_datetime(value: str) -> datetime:
    text = (value or "").strip()
    if not text:
        return datetime.now(timezone.utc)
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y/%m/%d %H:%M:%S", "%Y%m%d%H%M%S"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return datetime.now(timezone.utc)


def _element_to_xml(elem: ET.Element) -> str:
    return sanitize_xml_text(ET.tostring(elem, encoding="unicode"))


def parse_get_data_ack(xml_text: str) -> list[ParsedRealtimeValue]:
    if not xml_text or not xml_text.strip():
        return []
    root = ET.fromstring(html.unescape(xml_text.strip()))
    pk_type = _child(root, "PK_Type")
    message_name = _text(pk_type, ("Name",), "").upper()
    if message_name != "GET_DATA_ACK":
        return []
    info = _child(root, "Info")
    fsu_id = _text(info, ("FsuId", "FsuID"), "")
    fsu_code = _text(info, ("FsuCode", "FsuId", "FsuID"), "")
    collected_at = _parse_datetime(_text(info, ("Time", "SampleTime", "CollectTime", "DataTime"), ""))
    values = _child(info, "Values")
    device_list_root = _child(values, "DeviceList") if values is not None else _child(info, "DeviceList")
    if device_list_root is None:
        return []
    rows: list[ParsedRealtimeValue] = []
    for device in list(device_list_root):
        if _local_name(device.tag) != "Device":
            continue
        device_id = _attr(device, ("Id", "ID", "DeviceId", "Code")) or _text(device, ("Id", "ID", "DeviceId"), "")
        device_code = _attr(device, ("Code", "DeviceCode", "Id", "ID")) or _text(device, ("Code", "DeviceCode"), "") or device_id
        for semaphore in device.iter():
            if _local_name(semaphore.tag) not in {"TSemaphore", "Semaphore", "Signal", "TSignal"}:
                continue
            semaphore_id = _attr(semaphore, ("Id", "ID", "Code", "SignalId", "SemaphoreId")) or _text(
                semaphore, ("Id", "ID", "Code", "SignalId", "SemaphoreId"), ""
            )
            if not semaphore_id:
                continue
            mapping = resolve_signal_mapping(device_id or device_code, device_code or device_id, semaphore_id)
            rows.append(
                ParsedRealtimeValue(
                    fsu_id=fsu_id or fsu_code,
                    fsu_code=fsu_code or fsu_id,
                    device_id=device_id or device_code,
                    device_code=device_code or device_id,
                    semaphore_id=semaphore_id,
                    semaphore_type=_attr(semaphore, ("Type", "SignalType")) or _text(semaphore, ("Type", "SignalType"), ""),
                    measured_val=_attr(semaphore, ("MeasuredVal", "Value", "Val")) or _text(semaphore, ("MeasuredVal", "Value", "Val"), ""),
                    setup_val=_attr(semaphore, ("SetupVal",)) or _text(semaphore, ("SetupVal",), ""),
                    status=_attr(semaphore, ("Status",)) or _text(semaphore, ("Status",), ""),
                    mapping_status=mapping.mapping_status,
                    device_type=mapping.device_type,
                    standard_signal_id=mapping.standard_signal_id,
                    mapped_ids=mapping.mapped_ids,
                    base_type_id=mapping.base_type_id,
                    local_signal_id=mapping.local_signal_id,
                    signal_name=mapping.signal_name,
                    unit=mapping.unit,
                    signal_category=mapping.signal_category,
                    signal_type=mapping.signal_type,
                    channel_no=mapping.channel_no,
                    signal_meanings=mapping.signal_meanings,
                    raw_xml=_element_to_xml(semaphore),
                    collected_at=collected_at,
                )
            )
    return rows


def save_realtime_values(values: list[ParsedRealtimeValue]) -> list[dict]:
    if not values:
        return []
    session = _session_factory()
    try:
        touched_devices: set[tuple[str, str]] = set()
        for item in values:
            touched_devices.add((item.fsu_id, item.device_id or item.device_code))
        for fsu_id, device_id in touched_devices:
            session.execute(
                delete(BInterfaceRealtime).where(
                    BInterfaceRealtime.fsu_id == fsu_id,
                    or_(BInterfaceRealtime.device_id == device_id, BInterfaceRealtime.device_code == device_id),
                )
            )
        for item in values:
            session.add(
                BInterfaceRealtime(
                    fsu_id=item.fsu_id,
                    fsu_code=item.fsu_code,
                    device_id=item.device_id,
                    device_code=item.device_code,
                    semaphore_id=item.semaphore_id,
                    semaphore_type=item.semaphore_type or None,
                    measured_val=item.measured_val or None,
                    setup_val=item.setup_val or None,
                    status=item.status or None,
                    mapping_status=item.mapping_status or None,
                    device_type=item.device_type or None,
                    standard_signal_id=item.standard_signal_id or None,
                    mapped_ids=json.dumps(list(item.mapped_ids), ensure_ascii=False) if item.mapped_ids else None,
                    base_type_id=item.base_type_id or None,
                    local_signal_id=item.local_signal_id or None,
                    signal_name=item.signal_name or None,
                    unit=item.unit or None,
                    signal_category=item.signal_category or None,
                    signal_type=item.signal_type or None,
                    channel_no=item.channel_no or None,
                    signal_meanings=item.signal_meanings or None,
                    raw_xml=f"[mapping_status={item.mapping_status}] {item.raw_xml}",
                    collected_at=item.collected_at,
                )
            )
        session.commit()
        return list_realtime(limit=max(len(values), 1), fsu_id=values[0].fsu_id)
    finally:
        session.close()


def _to_dict(row: BInterfaceRealtime) -> dict:
    try:
        mapped_ids = json.loads(row.mapped_ids) if row.mapped_ids else []
    except json.JSONDecodeError:
        mapped_ids = []
    return {
        "fsu_id": row.fsu_id,
        "fsu_code": row.fsu_code,
        "device_id": row.device_id,
        "device_code": row.device_code,
        "semaphore_id": row.semaphore_id,
        "semaphore_type": row.semaphore_type,
        "measured_val": row.measured_val,
        "setup_val": row.setup_val,
        "status": row.status,
        "mapping_status": row.mapping_status or "unmapped",
        "device_type": row.device_type,
        "standard_signal_id": row.standard_signal_id,
        "mapped_ids": mapped_ids,
        "base_type_id": row.base_type_id,
        "local_signal_id": row.local_signal_id,
        "signal_name": row.signal_name,
        "unit": row.unit,
        "signal_category": row.signal_category,
        "signal_type": row.signal_type,
        "channel_no": row.channel_no,
        "signal_meanings": row.signal_meanings,
        "raw_xml": row.raw_xml,
        "collected_at": row.collected_at.isoformat() if row.collected_at else None,
    }


def list_realtime(limit: int = 100, fsu_id: str | None = None, device_id: str | None = None) -> list[dict]:
    session = _session_factory()
    try:
        stmt = select(BInterfaceRealtime)
        if fsu_id:
            stmt = stmt.where(BInterfaceRealtime.fsu_id == fsu_id)
        if device_id:
            stmt = stmt.where(or_(BInterfaceRealtime.device_id == device_id, BInterfaceRealtime.device_code == device_id))
        rows = session.scalars(stmt.order_by(desc(BInterfaceRealtime.collected_at), desc(BInterfaceRealtime.updated_at)).limit(limit)).all()
        return [_to_dict(row) for row in rows]
    finally:
        session.close()
