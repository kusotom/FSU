from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable
import xml.etree.ElementTree as ET

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.b_interface_info_cache import BInterfaceFsuInfoCache, BInterfaceLoginInfoCache
from app.modules.b_interface.logging_utils import sanitize_xml_text


SessionFactory = Callable[[], Session]
_session_factory: SessionFactory = SessionLocal


@dataclass(frozen=True)
class ParsedFsuInfoAck:
    fsu_id: str
    fsu_code: str
    cpu_usage: str
    mem_usage: str
    result: str
    raw_xml_sanitized: str
    collected_at: datetime


@dataclass(frozen=True)
class ParsedLoginInfoAck:
    fsu_id: str
    fsu_code: str
    sc_ip: str
    fsu_ip: str
    username: str
    ipsec_ip: str
    ipsec_user: str
    ftp_user: str
    device_list: tuple[str, ...]
    result: str
    raw_xml_sanitized: str
    collected_at: datetime


def set_session_factory(factory: SessionFactory) -> None:
    global _session_factory
    _session_factory = factory


def reset_session_factory() -> None:
    global _session_factory
    _session_factory = SessionLocal


def _now() -> datetime:
    return datetime.now(timezone.utc)


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


def _parse_xml(xml_text: str) -> ET.Element:
    return ET.fromstring(xml_text.strip())


def parse_get_fsuinfo_ack(xml_text: str) -> ParsedFsuInfoAck:
    root = _parse_xml(xml_text)
    info = _child(root, "Info")
    status = _child(info, "TFSUStatus")
    return ParsedFsuInfoAck(
        fsu_id=_text(info, ("FsuId", "FsuID"), ""),
        fsu_code=_text(info, ("FsuCode", "FsuId", "FsuID"), ""),
        cpu_usage=_text(status, ("CPUUsage",), ""),
        mem_usage=_text(status, ("MEMUsage",), ""),
        result=_text(info, ("Result",), ""),
        raw_xml_sanitized=sanitize_xml_text(xml_text),
        collected_at=_now(),
    )


def parse_get_logininfo_ack(xml_text: str) -> ParsedLoginInfoAck:
    root = _parse_xml(xml_text)
    info = _child(root, "Info")
    device_list_root = _child(info, "DeviceList")
    devices: list[str] = []
    if device_list_root is not None:
        for device in list(device_list_root):
            if _local_name(device.tag) != "Device":
                continue
            text_value = (device.text or "").strip()
            code = device.attrib.get("Code") or device.attrib.get("Id") or text_value
            if code:
                devices.append(code.strip())
    return ParsedLoginInfoAck(
        fsu_id=_text(info, ("FsuId", "FsuID"), ""),
        fsu_code=_text(info, ("FsuCode", "FsuId", "FsuID"), ""),
        sc_ip=_text(info, ("SCIP",), ""),
        fsu_ip=_text(info, ("FsuIP", "FsuIp", "IP"), ""),
        username=_text(info, ("UserName",), ""),
        ipsec_ip=_text(info, ("IPSecIP",), ""),
        ipsec_user=_text(info, ("IPSecUser",), ""),
        ftp_user=_text(info, ("FTPUser",), ""),
        device_list=tuple(devices),
        result=_text(info, ("Result",), ""),
        raw_xml_sanitized=sanitize_xml_text(xml_text),
        collected_at=_now(),
    )


def save_fsuinfo_ack(parsed: ParsedFsuInfoAck) -> dict:
    session = _session_factory()
    try:
        row = BInterfaceFsuInfoCache(
            fsu_id=parsed.fsu_id or parsed.fsu_code or "",
            fsu_code=parsed.fsu_code or parsed.fsu_id or None,
            cpu_usage=parsed.cpu_usage or None,
            mem_usage=parsed.mem_usage or None,
            result=parsed.result or None,
            raw_xml_sanitized=parsed.raw_xml_sanitized,
            collected_at=parsed.collected_at,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return _fsuinfo_to_dict(row)
    finally:
        session.close()


def save_logininfo_ack(parsed: ParsedLoginInfoAck) -> dict:
    session = _session_factory()
    try:
        row = BInterfaceLoginInfoCache(
            fsu_id=parsed.fsu_id or parsed.fsu_code or "",
            fsu_code=parsed.fsu_code or parsed.fsu_id or None,
            sc_ip=parsed.sc_ip or None,
            fsu_ip=parsed.fsu_ip or None,
            username=parsed.username or None,
            ipsec_ip=parsed.ipsec_ip or None,
            ipsec_user=parsed.ipsec_user or None,
            ftp_user=parsed.ftp_user or None,
            device_list=list(parsed.device_list) if parsed.device_list else None,
            result=parsed.result or None,
            raw_xml_sanitized=parsed.raw_xml_sanitized,
            collected_at=parsed.collected_at,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return _logininfo_to_dict(row)
    finally:
        session.close()


def _fsuinfo_to_dict(row: BInterfaceFsuInfoCache) -> dict:
    return {
        "fsu_id": row.fsu_id,
        "fsu_code": row.fsu_code,
        "cpu_usage": row.cpu_usage,
        "mem_usage": row.mem_usage,
        "result": row.result,
        "raw_xml_sanitized": row.raw_xml_sanitized,
        "collected_at": row.collected_at.isoformat() if row.collected_at else None,
    }


def _logininfo_to_dict(row: BInterfaceLoginInfoCache) -> dict:
    return {
        "fsu_id": row.fsu_id,
        "fsu_code": row.fsu_code,
        "sc_ip": row.sc_ip,
        "fsu_ip": row.fsu_ip,
        "username": row.username,
        "ipsec_ip": row.ipsec_ip,
        "ipsec_user": row.ipsec_user,
        "ftp_user": row.ftp_user,
        "device_list": row.device_list or [],
        "result": row.result,
        "raw_xml_sanitized": row.raw_xml_sanitized,
        "collected_at": row.collected_at.isoformat() if row.collected_at else None,
    }


def get_latest_fsuinfo(fsu_id: str) -> dict | None:
    session = _session_factory()
    try:
        row = session.scalar(
            select(BInterfaceFsuInfoCache)
            .where(BInterfaceFsuInfoCache.fsu_id == fsu_id)
            .order_by(desc(BInterfaceFsuInfoCache.collected_at), desc(BInterfaceFsuInfoCache.updated_at))
            .limit(1)
        )
        return _fsuinfo_to_dict(row) if row is not None else None
    finally:
        session.close()


def get_latest_logininfo(fsu_id: str) -> dict | None:
    session = _session_factory()
    try:
        row = session.scalar(
            select(BInterfaceLoginInfoCache)
            .where(BInterfaceLoginInfoCache.fsu_id == fsu_id)
            .order_by(desc(BInterfaceLoginInfoCache.collected_at), desc(BInterfaceLoginInfoCache.updated_at))
            .limit(1)
        )
        return _logininfo_to_dict(row) if row is not None else None
    finally:
        session.close()
