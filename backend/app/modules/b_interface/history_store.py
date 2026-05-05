from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import html
import json
from typing import Callable
import xml.etree.ElementTree as ET

from sqlalchemy import desc, or_, select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.b_interface_history import BInterfaceHistory
from app.modules.b_interface.config_loader import resolve_signal_mapping
from app.modules.b_interface.logging_utils import sanitize_xml_text


SessionFactory = Callable[[], Session]
_session_factory: SessionFactory = SessionLocal


@dataclass(frozen=True)
class ParsedHistoryValue:
    fsu_id: str
    fsu_code: str
    device_id: str
    device_code: str
    device_type: str
    semaphore_id: str
    semaphore_type: str
    measured_val: str
    setup_val: str
    status: str
    sample_time: datetime
    result: str
    mapping_status: str
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
    raw_fragment: str
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


def _children(root: ET.Element | None, name: str) -> list[ET.Element]:
    if root is None:
        return []
    return [elem for elem in list(root) if _local_name(elem.tag) == name]


def _child(root: ET.Element | None, name: str) -> ET.Element | None:
    for elem in _children(root, name):
        return elem
    return None


def _text(root: ET.Element | None, names: tuple[str, ...], default: str = "") -> str:
    if root is None:
        return default
    for name in names:
        for elem in root.iter():
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
        value = root.attrib.get(name) or lowered.get(name.lower())
        if value:
            return value.strip()
    return default


def _parse_datetime(value: str, fallback: datetime | None = None) -> datetime:
    text = (value or "").strip()
    if not text:
        return fallback or datetime.now(timezone.utc)
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
        return fallback or datetime.now(timezone.utc)


def _element_to_xml(elem: ET.Element) -> str:
    return sanitize_xml_text(ET.tostring(elem, encoding="unicode"))


def _extract_sample_time(elem: ET.Element, collected_at: datetime) -> datetime:
    text = _attr(elem, ("Time", "SampleTime", "CollectTime", "MeasuredTime", "RecordTime")) or _text(
        elem, ("Time", "SampleTime", "CollectTime", "MeasuredTime", "RecordTime"), ""
    )
    return _parse_datetime(text, fallback=collected_at)


def _iter_history_semaphores(values_root: ET.Element | None) -> list[tuple[str, str, ET.Element]]:
    if values_root is None:
        return []
    pairs: list[tuple[str, str, ET.Element]] = []
    device_list = _child(values_root, "DeviceList")
    if device_list is not None:
        for device in _children(device_list, "Device"):
            device_id = _attr(device, ("Id", "ID", "DeviceId", "Code")) or _text(device, ("Id", "DeviceId"), "")
            device_code = _attr(device, ("Code", "DeviceCode", "Id", "ID")) or _text(device, ("Code", "DeviceCode"), "") or device_id
            for semaphore in device.iter():
                if _local_name(semaphore.tag) in {"TSemaphore", "Semaphore", "Signal", "TSignal"}:
                    pairs.append((device_id, device_code, semaphore))
    semaphore_list = _child(values_root, "TSemaphoreList")
    if semaphore_list is not None:
        for semaphore in semaphore_list.iter():
            if _local_name(semaphore.tag) not in {"TSemaphore", "Semaphore", "Signal", "TSignal"}:
                continue
            device_id = _attr(semaphore, ("DeviceId", "Id", "Code")) or _text(semaphore, ("DeviceId",), "")
            device_code = _attr(semaphore, ("DeviceCode", "Code", "Id")) or _text(semaphore, ("DeviceCode",), "") or device_id
            pairs.append((device_id, device_code, semaphore))
    return pairs


def parse_get_hisdata_ack(xml_text: str, max_records: int = 5000) -> list[ParsedHistoryValue]:
    if not xml_text or not xml_text.strip():
        return []
    root = ET.fromstring(html.unescape(xml_text.strip()))
    pk_type = _child(root, "PK_Type")
    message_name = _text(pk_type, ("Name",), "").upper()
    if message_name != "GET_HISDATA_ACK":
        return []
    info = _child(root, "Info")
    fsu_id = _text(info, ("FsuId", "FsuID"), "")
    fsu_code = _text(info, ("FsuCode", "FsuId", "FsuID"), "")
    result = _text(info, ("Result",), "")
    collected_at = _parse_datetime(
        _text(info, ("Time", "SampleTime", "CollectTime", "MeasuredTime", "RecordTime"), ""),
        fallback=datetime.now(timezone.utc),
    )
    values = _child(info, "Values")
    pairs = _iter_history_semaphores(values if values is not None else info)
    rows: list[ParsedHistoryValue] = []
    for device_id, device_code, semaphore in pairs[:max_records]:
        semaphore_id = _attr(semaphore, ("Id", "ID", "Code", "SignalId", "SemaphoreId")) or _text(
            semaphore, ("Id", "ID", "Code", "SignalId", "SemaphoreId"), ""
        )
        if not semaphore_id:
            continue
        resolved_device_id = device_id or device_code
        resolved_device_code = device_code or device_id
        mapping = resolve_signal_mapping(resolved_device_id, resolved_device_code, semaphore_id)
        rows.append(
            ParsedHistoryValue(
                fsu_id=fsu_id or fsu_code,
                fsu_code=fsu_code or fsu_id,
                device_id=resolved_device_id,
                device_code=resolved_device_code,
                device_type=mapping.device_type,
                semaphore_id=semaphore_id,
                semaphore_type=_attr(semaphore, ("Type", "SignalType")) or _text(semaphore, ("Type", "SignalType"), ""),
                measured_val=_attr(semaphore, ("MeasuredVal", "Value", "Val")) or _text(semaphore, ("MeasuredVal", "Value", "Val"), ""),
                setup_val=_attr(semaphore, ("SetupVal",)) or _text(semaphore, ("SetupVal",), ""),
                status=_attr(semaphore, ("Status",)) or _text(semaphore, ("Status",), ""),
                sample_time=_extract_sample_time(semaphore, collected_at),
                result=result,
                mapping_status=mapping.mapping_status,
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
                raw_fragment=_element_to_xml(semaphore),
                collected_at=collected_at,
            )
        )
    return rows


def save_history_values(values: list[ParsedHistoryValue], source_call_id: str | None = None) -> list[dict]:
    if not values:
        return []
    session = _session_factory()
    try:
        for item in values:
            existing = session.scalar(
                select(BInterfaceHistory).where(
                    BInterfaceHistory.fsu_id == item.fsu_id,
                    BInterfaceHistory.device_id == item.device_id,
                    BInterfaceHistory.semaphore_id == item.semaphore_id,
                    BInterfaceHistory.sample_time == item.sample_time,
                )
            )
            if existing is None:
                session.add(
                    BInterfaceHistory(
                        fsu_id=item.fsu_id,
                        fsu_code=item.fsu_code or None,
                        device_id=item.device_id or None,
                        device_code=item.device_code or None,
                        device_type=item.device_type or None,
                        semaphore_id=item.semaphore_id,
                        semaphore_type=item.semaphore_type or None,
                        measured_val=item.measured_val or None,
                        setup_val=item.setup_val or None,
                        status=item.status or None,
                        sample_time=item.sample_time,
                        mapping_status=item.mapping_status or None,
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
                        raw_fragment=item.raw_fragment or None,
                        source_call_id=source_call_id or None,
                        collected_at=item.collected_at,
                    )
                )
                continue
            existing.fsu_code = item.fsu_code or existing.fsu_code
            existing.device_code = item.device_code or existing.device_code
            existing.device_type = item.device_type or existing.device_type
            existing.semaphore_type = item.semaphore_type or existing.semaphore_type
            existing.measured_val = item.measured_val or existing.measured_val
            existing.setup_val = item.setup_val or existing.setup_val
            existing.status = item.status or existing.status
            existing.mapping_status = item.mapping_status or existing.mapping_status
            existing.standard_signal_id = item.standard_signal_id or existing.standard_signal_id
            existing.mapped_ids = json.dumps(list(item.mapped_ids), ensure_ascii=False) if item.mapped_ids else existing.mapped_ids
            existing.base_type_id = item.base_type_id or existing.base_type_id
            existing.local_signal_id = item.local_signal_id or existing.local_signal_id
            existing.signal_name = item.signal_name or existing.signal_name
            existing.unit = item.unit or existing.unit
            existing.signal_category = item.signal_category or existing.signal_category
            existing.signal_type = item.signal_type or existing.signal_type
            existing.channel_no = item.channel_no or existing.channel_no
            existing.signal_meanings = item.signal_meanings or existing.signal_meanings
            existing.raw_fragment = item.raw_fragment or existing.raw_fragment
            existing.source_call_id = source_call_id or existing.source_call_id
            existing.collected_at = item.collected_at or existing.collected_at
        session.commit()
        return list_history(limit=min(max(len(values), 1), 5000), fsu_id=values[0].fsu_id)
    finally:
        session.close()


def _to_dict(row: BInterfaceHistory) -> dict:
    try:
        mapped_ids = json.loads(row.mapped_ids) if row.mapped_ids else []
    except json.JSONDecodeError:
        mapped_ids = []
    return {
        "fsu_id": row.fsu_id,
        "fsu_code": row.fsu_code,
        "device_id": row.device_id,
        "device_code": row.device_code,
        "device_type": row.device_type,
        "semaphore_id": row.semaphore_id,
        "semaphore_type": row.semaphore_type,
        "measured_val": row.measured_val,
        "setup_val": row.setup_val,
        "status": row.status,
        "sample_time": row.sample_time.isoformat() if row.sample_time else None,
        "mapping_status": row.mapping_status or "unmapped",
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
        "raw_fragment": row.raw_fragment,
        "source_call_id": row.source_call_id,
        "collected_at": row.collected_at.isoformat() if row.collected_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def list_history(
    limit: int = 500,
    fsu_id: str | None = None,
    device_id: str | None = None,
    semaphore_id: str | None = None,
    mapping_status: str | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
) -> list[dict]:
    session = _session_factory()
    try:
        stmt = select(BInterfaceHistory)
        if fsu_id:
            stmt = stmt.where(BInterfaceHistory.fsu_id == fsu_id)
        if device_id:
            stmt = stmt.where(or_(BInterfaceHistory.device_id == device_id, BInterfaceHistory.device_code == device_id))
        if semaphore_id:
            stmt = stmt.where(BInterfaceHistory.semaphore_id == semaphore_id)
        if mapping_status:
            stmt = stmt.where(BInterfaceHistory.mapping_status == mapping_status)
        if start_time is not None:
            stmt = stmt.where(BInterfaceHistory.sample_time >= start_time)
        if end_time is not None:
            stmt = stmt.where(BInterfaceHistory.sample_time <= end_time)
        rows = session.scalars(stmt.order_by(desc(BInterfaceHistory.sample_time), desc(BInterfaceHistory.id)).limit(limit)).all()
        return [_to_dict(row) for row in rows]
    finally:
        session.close()
