from __future__ import annotations

import html
import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.api.routes.ingest import _ingest_telemetry_sync
from app.models.alarm import AlarmEvent
from app.models.b_device import BDevice, BDeviceConfig
from app.models.device import FSUDevice, MonitorPoint
from app.models.site import Site
from app.schemas.telemetry import MetricItem, TelemetryIngestRequest


B2016_NS = "http://SCService.chinatowercom.com"
FSU_SERVICE_NS = "http://FSUService.chinatowercom.com"
SOAP_ENV_NS = "http://schemas.xmlsoap.org/soap/envelope/"


@dataclass
class B2016Packet:
    raw_text: str
    root: ET.Element
    packet_name: str
    packet_code: str
    is_soap: bool = False


@dataclass
class B2016ProcessResult:
    packet_name: str
    packet_code: str
    response_xml: str
    ingested_metrics: int = 0
    ingested_alarms: int = 0
    updated_devices: int = 0


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_now_text() -> str:
    return utc_now().strftime("%Y-%m-%d %H:%M:%S")


def decode_payload(raw: bytes) -> str:
    for encoding in ("utf-8", "gb18030", "gbk", "latin1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    if ":" in tag:
        return tag.rsplit(":", 1)[1]
    return tag


def iter_by_name(root: ET.Element, name: str) -> Iterable[ET.Element]:
    for elem in root.iter():
        if local_name(elem.tag) == name:
            yield elem


def first_by_name(root: ET.Element | None, name: str) -> ET.Element | None:
    if root is None:
        return None
    return next(iter_by_name(root, name), None)


def child_by_name(root: ET.Element | None, name: str) -> ET.Element | None:
    if root is None:
        return None
    for child in list(root):
        if local_name(child.tag) == name:
            return child
    return None


def child_text(root: ET.Element | None, name: str, default: str = "") -> str:
    child = child_by_name(root, name)
    if child is None or child.text is None:
        return default
    return child.text.strip()


def child_text_any(root: ET.Element | None, names: Iterable[str], default: str = "") -> str:
    for name in names:
        value = child_text(root, name)
        if value:
            return value
    return default


def attr_any(root: ET.Element | None, names: Iterable[str], default: str = "") -> str:
    if root is None:
        return default
    for name in names:
        value = root.attrib.get(name)
        if value:
            return value.strip()
    lowered = {key.lower(): value for key, value in root.attrib.items()}
    for name in names:
        value = lowered.get(name.lower())
        if value:
            return value.strip()
    return default


def first_text(root: ET.Element, name: str, default: str = "") -> str:
    elem = first_by_name(root, name)
    if elem is None or elem.text is None:
        return default
    return elem.text.strip()


def parse_xml(text: str) -> ET.Element:
    return ET.fromstring(text.strip("\ufeff\r\n\t "))


def parse_packet(raw: bytes) -> B2016Packet:
    text = decode_payload(raw)
    outer = parse_xml(text)
    is_soap = local_name(outer.tag) == "Envelope"
    protocol_text = text
    root = outer

    if is_soap:
        xml_data = first_text(outer, "xmlData") or first_text(outer, "return")
        if not xml_data:
            for elem in outer.iter():
                candidate = html.unescape((elem.text or "").strip())
                if "<Request" in candidate or "<Response" in candidate:
                    xml_data = candidate
                    break
        if not xml_data:
            raise ValueError("SOAP payload does not contain xmlData or return XML")
        protocol_text = html.unescape(xml_data)
        root = parse_xml(protocol_text)

    pk_type = first_by_name(root, "PK_Type")
    packet_name = child_text(pk_type, "Name")
    packet_code = child_text(pk_type, "Code")
    if not packet_name:
        raise ValueError("B interface packet missing PK_Type/Name")
    return B2016Packet(
        raw_text=protocol_text,
        root=root,
        packet_name=packet_name.upper(),
        packet_code=packet_code,
        is_soap=is_soap,
    )


def xml_response(name: str, code: str, info_items: list[tuple[str, str]] | None = None) -> str:
    info_items = info_items or [("Result", "1")]
    info_xml = "\n".join(
        f"        <{key}>{html.escape(str(value), quote=False)}</{key}>"
        for key, value in info_items
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<Response>\n"
        "    <PK_Type>\n"
        f"        <Name>{name}</Name>\n"
        f"        <Code>{code}</Code>\n"
        "    </PK_Type>\n"
        "    <Info>\n"
        f"{info_xml}\n"
        "    </Info>\n"
        "</Response>\n"
    )


def soap_response(inner_xml: str) -> str:
    escaped = html.escape(inner_xml, quote=False)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<SOAP-ENV:Envelope xmlns:SOAP-ENV="{SOAP_ENV_NS}" xmlns:ns1="{B2016_NS}">'
        "<SOAP-ENV:Body>"
        "<ns1:invokeResponse>"
        f"<return>{escaped}</return>"
        "</ns1:invokeResponse>"
        "</SOAP-ENV:Body>"
        "</SOAP-ENV:Envelope>\n"
    )


def wsdl_response() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<definitions name="SCService" targetNamespace="http://SCService.chinatowercom.com" '
        'xmlns:soap="http://schemas.xmlsoap.org/wsdl/soap/" '
        'xmlns:tns="http://SCService.chinatowercom.com" '
        'xmlns:xsd="http://www.w3.org/2001/XMLSchema" '
        'xmlns="http://schemas.xmlsoap.org/wsdl/">'
        "<documentation>China Tower B interface 2016 SCService invoke(xmlData).</documentation>"
        "</definitions>\n"
    )


def request_xml(name: str, code: str, info_items: list[tuple[str, str]] | None = None) -> str:
    info_items = info_items or []
    info_xml = "\n".join(
        f"        <{key}>{html.escape(str(value), quote=False)}</{key}>"
        for key, value in info_items
    )
    if info_xml:
        info_block = f"    <Info>\n{info_xml}\n    </Info>\n"
    else:
        info_block = "    <Info />\n"
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<Request>\n"
        "    <PK_Type>\n"
        f"        <Name>{name}</Name>\n"
        f"        <Code>{code}</Code>\n"
        "    </PK_Type>\n"
        f"{info_block}"
        "</Request>\n"
    )


def device_list_xml(device_codes: Iterable[str]) -> str:
    lines = ["        <DeviceList>"]
    for device_code in dict.fromkeys(code for code in device_codes if code):
        escaped = html.escape(str(device_code), quote=True)
        lines.append(f'            <Device Id="{escaped}" Code="{escaped}"/>')
    lines.append("        </DeviceList>")
    return "\n".join(lines)


def vertiv_get_data_xml(fsu_code: str, device_codes: Iterable[str] | None = None) -> str:
    # eStoneII WebProvider rejects bare GET_DATA without DeviceList and may restart the local 8080 service.
    devices = list(device_codes or [])
    device_list = device_list_xml(devices)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<Request>\n"
        "    <PK_Type>\n"
        "        <Name>GET_DATA</Name>\n"
        "        <Code>401</Code>\n"
        "    </PK_Type>\n"
        "    <Info>\n"
        f"        <FsuId>{html.escape(fsu_code, quote=False)}</FsuId>\n"
        f"        <FsuCode>{html.escape(fsu_code, quote=False)}</FsuCode>\n"
        f"{device_list}\n"
        "    </Info>\n"
        "</Request>\n"
    )


def vertiv_get_fsuinfo_xml(fsu_code: str) -> str:
    return request_xml("GET_FSUINFO", "101", [("FsuId", fsu_code), ("FsuCode", fsu_code)])


def soap_request(inner_xml: str, namespace: str = B2016_NS) -> str:
    escaped = html.escape(inner_xml, quote=False)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<SOAP-ENV:Envelope xmlns:SOAP-ENV="{SOAP_ENV_NS}" '
        'xmlns:SOAP-ENC="http://schemas.xmlsoap.org/soap/encoding/" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        'xmlns:xsd="http://www.w3.org/2001/XMLSchema" '
        f'xmlns:ns1="{namespace}">'
        '<SOAP-ENV:Body SOAP-ENV:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
        "<ns1:invoke>"
        f"<xmlData>{escaped}</xmlData>"
        "</ns1:invoke>"
        "</SOAP-ENV:Body>"
        "</SOAP-ENV:Envelope>\n"
    )


def parse_datetime(value: str | None) -> datetime:
    if not value:
        return utc_now()
    text = value.strip()
    patterns = (
        "%Y-%m-%d %H:%M:%S",
        "%Y/%m/%d %H:%M:%S",
        "%Y%m%d%H%M%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S%z",
    )
    for pattern in patterns:
        try:
            parsed = datetime.strptime(text, pattern)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed
        except ValueError:
            pass
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except ValueError:
        return utc_now()


def to_float(value: str | None, default: float = 0.0) -> float:
    if value is None:
        return default
    text = str(value).strip()
    if not text:
        return default
    try:
        return float(text)
    except ValueError:
        lowered = text.lower()
        if lowered in {"true", "on", "open", "alarm", "active"}:
            return 1.0
        if lowered in {"false", "off", "close", "closed", "normal"}:
            return 0.0
        return default


def signal_category(signal_type: str) -> str:
    mapping = {
        "0": "status",
        "1": "power",
        "2": "control",
        "3": "analog_output",
        "di": "status",
        "ai": "power",
        "do": "control",
        "ao": "analog_output",
    }
    return mapping.get(signal_type.strip().lower(), "b2016")


def get_or_create_site(db: Session, site_code: str, site_name: str | None = None) -> Site:
    site = db.scalar(select(Site).where(Site.code == site_code))
    if site is None:
        site = Site(code=site_code, name=site_name or f"B2016 Site {site_code}")
        db.add(site)
        db.flush()
    elif site_name:
        site.name = site_name
    return site


def get_or_create_fsu_device(
    db: Session,
    *,
    site: Site,
    device_code: str,
    device_name: str | None = None,
    vendor: str | None = None,
) -> FSUDevice:
    device = db.scalar(select(FSUDevice).where(FSUDevice.code == device_code))
    if device is None:
        device = FSUDevice(
            site_id=site.id,
            code=device_code,
            name=device_name or f"B2016 Device {device_code}",
            vendor=vendor or "BInterface2016",
            status="online",
            last_seen_at=utc_now(),
        )
        db.add(device)
        db.flush()
    else:
        device.site_id = site.id
        device.status = "online"
        device.last_seen_at = utc_now()
        if device_name:
            device.name = device_name
        if vendor:
            device.vendor = vendor
    return device


def get_or_create_point(
    db: Session,
    *,
    device: FSUDevice,
    point_key: str,
    point_name: str | None = None,
    category: str = "b2016",
    unit: str | None = None,
) -> MonitorPoint:
    point = db.scalar(
        select(MonitorPoint).where(
            and_(MonitorPoint.device_id == device.id, MonitorPoint.point_key == point_key)
        )
    )
    if point is None:
        point = MonitorPoint(
            device_id=device.id,
            point_key=point_key,
            point_name=point_name or point_key,
            category=category,
            unit=unit,
        )
        db.add(point)
        db.flush()
    else:
        point.point_name = point_name or point.point_name
        point.category = category or point.category
        point.unit = unit
    return point


def upsert_b_device_config(db: Session, device: BDevice, key: str, value: object, *, is_system: bool = True):
    config = db.scalar(
        select(BDeviceConfig).where(
            and_(BDeviceConfig.device_id == device.id, BDeviceConfig.config_key == key)
        )
    )
    text = "" if value is None else str(value)
    if len(text) > 512:
        text = text[:512]
    if config is None:
        config = BDeviceConfig(
            device_id=device.id,
            config_key=key,
            config_value=text,
            is_system=is_system,
        )
        db.add(config)
    else:
        config.config_value = text
        config.is_system = is_system
        config.updated_at = utc_now()


def upsert_fsu_info(packet: B2016Packet, db: Session) -> tuple[str, int]:
    info = first_by_name(packet.root, "Info")
    fsu_code = child_text_any(info, ("FsuCode", "FsuID", "FsuId")) or "UNKNOWN-FSU"
    fsu_id = child_text_any(info, ("FsuId", "FsuID")) or fsu_code
    fsu_ip = child_text_any(info, ("FsuIP", "FsuIp", "IP"))
    vendor = child_text_any(info, ("FSUVendor", "FSUManufactor", "Vendor")) or "Vertiv/AMS"
    fsu_type = child_text_any(info, ("FSUType", "HWType", "Model")) or "FSU"
    version = child_text_any(info, ("Version", "Vervion", "SoftwareVersion"))
    site = get_or_create_site(db, fsu_code)
    get_or_create_fsu_device(
        db,
        site=site,
        device_code=fsu_code,
        device_name=f"B2016 FSU {fsu_code}",
        vendor=vendor,
    )

    b_device = db.scalar(select(BDevice).where(BDevice.device_code == fsu_code))
    if b_device is None:
        b_device = BDevice(
            device_code=fsu_code,
            device_name=f"B2016 FSU {fsu_code}",
            site_code=fsu_code,
            vendor=vendor,
            model=fsu_type,
            ip_address=fsu_ip or None,
            software_version=version or None,
            protocol_version="2016",
            status="online",
            last_seen_at=utc_now(),
        )
        db.add(b_device)
        db.flush()
    else:
        b_device.site_code = fsu_code
        b_device.vendor = vendor
        b_device.model = fsu_type
        b_device.ip_address = fsu_ip or b_device.ip_address
        b_device.software_version = version or b_device.software_version
        b_device.protocol_version = "2016"
        b_device.status = "online"
        b_device.last_seen_at = utc_now()
        b_device.updated_at = utc_now()

    upsert_b_device_config(db, b_device, "FsuId", fsu_id)
    for key in (
        "UserName",
        "PaSCword",
        "MacId",
        "ImsiId",
        "NetworkType",
        "LockedNetworkType",
        "Carrier",
        "NMVendor",
        "NMType",
        "Reg_Mode",
        "Internet_mode",
        "FSUClass",
        "DictVersion",
        "MainVPN_One",
        "MainVPN_Two",
        "MainVPN_Three",
        "SpareVPN_One",
        "Disaster_Recovery_One",
    ):
        value = child_text(info, key)
        if value:
            upsert_b_device_config(db, b_device, key, value)

    device_codes: list[str] = []
    device_list = first_by_name(info, "DeviceList")
    if device_list is not None:
        for elem in iter_by_name(device_list, "Device"):
            code = attr_any(elem, ("Code", "Id", "ID", "DeviceCode", "DeviceId"))
            if not code:
                continue
            if code not in device_codes:
                device_codes.append(code)
            get_or_create_fsu_device(db, site=site, device_code=code, vendor=vendor)
    if device_codes:
        upsert_b_device_config(db, b_device, "DeviceList", json.dumps(device_codes, ensure_ascii=False))

    return fsu_code, len(device_codes)


def handle_login(packet: B2016Packet, db: Session, sc_ip: str) -> B2016ProcessResult:
    _fsu_code, device_count = upsert_fsu_info(packet, db)
    db.commit()
    response = xml_response("LOGIN_ACK", "102", [("RightLevel", "2"), ("SCIP", sc_ip)])
    return B2016ProcessResult(packet.packet_name, packet.packet_code, response, updated_devices=device_count)


def handle_fsuinfo_ack(packet: B2016Packet, db: Session) -> B2016ProcessResult:
    _fsu_code, device_count = upsert_fsu_info(packet, db)
    db.commit()
    return B2016ProcessResult(
        packet.packet_name,
        packet.packet_code,
        xml_response("RECEIVE_ACK", "200", [("Result", "1")]),
        updated_devices=device_count,
    )


def handle_logout(packet: B2016Packet, db: Session) -> B2016ProcessResult:
    info = first_by_name(packet.root, "Info")
    fsu_code = child_text(info, "FsuCode") or child_text(info, "FsuId")
    if fsu_code:
        b_device = db.scalar(select(BDevice).where(BDevice.device_code == fsu_code))
        if b_device is not None:
            b_device.status = "offline"
            b_device.updated_at = utc_now()
        fsu = db.scalar(select(FSUDevice).where(FSUDevice.code == fsu_code))
        if fsu is not None:
            fsu.status = "offline"
        db.commit()
    return B2016ProcessResult(packet.packet_name, packet.packet_code, xml_response("LOGOUT_ACK", "104"))


def alarm_is_recovery(flag: str) -> bool:
    text = (flag or "").strip().lower()
    return text in {"0", "2", "recover", "recovered", "clear", "cleared", "end", "normal"}


def handle_send_alarm(packet: B2016Packet, db: Session) -> B2016ProcessResult:
    count = 0
    for alarm_elem in iter_by_name(packet.root, "TAlarm"):
        fsu_code = child_text(alarm_elem, "FsuCode") or child_text(alarm_elem, "FsuId") or "UNKNOWN-FSU"
        device_code = child_text(alarm_elem, "DeviceCode") or child_text(alarm_elem, "DeviceId") or fsu_code
        point_key = child_text(alarm_elem, "Id") or f"alarm:{child_text(alarm_elem, 'SerialNo') or 'unknown'}"
        alarm_desc = child_text(alarm_elem, "AlarmDesc") or point_key
        alarm_time = parse_datetime(child_text(alarm_elem, "AlarmTime"))
        alarm_level = int(to_float(child_text(alarm_elem, "AlarmLevel"), 2.0))
        alarm_flag = child_text(alarm_elem, "AlarmFlag")
        serial_no = child_text(alarm_elem, "SerialNo")
        site = get_or_create_site(db, fsu_code)
        device = get_or_create_fsu_device(db, site=site, device_code=device_code, vendor="BInterface2016")
        point = get_or_create_point(
            db,
            device=device,
            point_key=point_key,
            point_name=alarm_desc,
            category="alarm",
        )
        alarm_code = serial_no or f"{device_code}:{point_key}"
        active_alarm = db.scalar(
            select(AlarmEvent)
            .where(
                and_(
                    AlarmEvent.device_id == device.id,
                    AlarmEvent.point_id == point.id,
                    AlarmEvent.alarm_code == alarm_code,
                    AlarmEvent.status.in_(["active", "acknowledged"]),
                )
            )
            .order_by(AlarmEvent.started_at.desc())
        )
        if alarm_is_recovery(alarm_flag):
            if active_alarm is not None:
                active_alarm.status = "recovered"
                active_alarm.recovered_at = alarm_time
                active_alarm.updated_at = utc_now()
        elif active_alarm is None:
            alarm = AlarmEvent(
                site_id=site.id,
                device_id=device.id,
                point_id=point.id,
                alarm_code=alarm_code,
                alarm_name=alarm_desc,
                alarm_level=alarm_level,
                status="active",
                trigger_value=1.0,
                content=alarm_desc,
                started_at=alarm_time,
                created_at=utc_now(),
                updated_at=utc_now(),
            )
            db.add(alarm)
        else:
            active_alarm.alarm_name = alarm_desc
            active_alarm.alarm_level = alarm_level
            active_alarm.content = alarm_desc
            active_alarm.updated_at = utc_now()
        count += 1
    db.commit()
    return B2016ProcessResult(
        packet.packet_name,
        packet.packet_code,
        xml_response("SEND_ALARM_ACK", "502", [("Result", "1")]),
        ingested_alarms=count,
    )


def extract_device_signal_metrics(packet: B2016Packet) -> list[TelemetryIngestRequest]:
    info = first_by_name(packet.root, "Info")
    fsu_code = child_text_any(info, ("FsuCode", "FsuID", "FsuId")) or "UNKNOWN-FSU"
    collected_at = parse_datetime(
        child_text_any(info, ("Time", "SampleTime", "EndTime", "DataTime", "CollectTime"))
    )
    requests: list[TelemetryIngestRequest] = []
    device_list = first_by_name(packet.root, "DeviceList")
    if device_list is None:
        return requests

    for device_elem in iter_by_name(device_list, "Device"):
        device_code = attr_any(device_elem, ("Code", "Id", "ID", "DeviceCode", "DeviceId"), fsu_code)
        device_name = attr_any(device_elem, ("Name", "DeviceName"), f"B2016 Device {device_code}")
        metrics: list[MetricItem] = []
        semaphore_elems = [
            elem
            for elem in device_elem.iter()
            if local_name(elem.tag) in {"TSemaphore", "Semaphore", "Signal", "TSignal"}
        ]
        for sem in semaphore_elems:
            signal_id = attr_any(sem, ("Id", "ID", "Code", "SignalId", "SemaphoreId")) or child_text_any(
                sem, ("Id", "ID", "Code", "SignalId", "SemaphoreId")
            )
            if not signal_id:
                continue
            signal_type = attr_any(sem, ("Type", "SignalType")) or child_text_any(sem, ("Type", "SignalType"))
            raw_value = (
                attr_any(sem, ("MeasuredVal", "SetupVal", "Status", "Value", "Val", "value"))
                or child_text_any(sem, ("MeasuredVal", "SetupVal", "Status", "Value", "Val", "value"))
            )
            unit = attr_any(sem, ("Unit", "UnitName")) or child_text_any(sem, ("Unit", "UnitName")) or None
            signal_name = attr_any(sem, ("Name", "SignalName")) or child_text_any(sem, ("Name", "SignalName"))
            metrics.append(
                MetricItem(
                    key=signal_id,
                    name=signal_name or f"B2016 {signal_id}",
                    value=to_float(raw_value),
                    unit=unit,
                    category=signal_category(signal_type),
                )
            )
        if metrics:
            requests.append(
                TelemetryIngestRequest(
                    site_code=fsu_code,
                    site_name=f"B2016 Site {fsu_code}",
                    fsu_code=device_code,
                    fsu_name=device_name,
                    collected_at=collected_at,
                    metrics=metrics,
                )
            )
    return requests


def handle_data_ack(packet: B2016Packet, db: Session) -> B2016ProcessResult:
    ingest_requests = extract_device_signal_metrics(packet)
    metric_count = 0
    for payload in ingest_requests:
        _ingest_telemetry_sync(payload, db=db, commit=False)
        metric_count += len(payload.metrics)
    db.commit()
    return B2016ProcessResult(
        packet.packet_name,
        packet.packet_code,
        xml_response("RECEIVE_ACK", "200", [("Result", "1")]),
        ingested_metrics=metric_count,
    )


def handle_time_check(packet: B2016Packet) -> B2016ProcessResult:
    return B2016ProcessResult(
        packet.packet_name,
        packet.packet_code,
        xml_response("TIME_CHECK_ACK", "1302", [("Time", utc_now_text()), ("Result", "1")]),
    )


def process_packet(raw: bytes, db: Session, *, sc_ip: str) -> B2016ProcessResult:
    packet = parse_packet(raw)
    name = packet.packet_name
    if name == "LOGIN":
        return handle_login(packet, db, sc_ip=sc_ip)
    if name == "LOGOUT":
        return handle_logout(packet, db)
    if name == "SEND_ALARM":
        return handle_send_alarm(packet, db)
    if name in {"GET_DATA_ACK", "GET_HISDATA_ACK"}:
        return handle_data_ack(packet, db)
    if name == "GET_FSUINFO_ACK":
        return handle_fsuinfo_ack(packet, db)
    if name == "TIME_CHECK":
        return handle_time_check(packet)

    code_by_name = {
        "GET_LOGININFO": "1502",
        "SET_LOGININFO": "1504",
        "GET_FTP": "1602",
        "SET_FTP": "1604",
        "GET_THRESHOLD": "1902",
        "SET_THRESHOLD": "2002",
        "SET_POINT": "1002",
    }
    response_name = name if name.endswith("_ACK") else f"{name}_ACK"
    response_code = code_by_name.get(name, "200")
    return B2016ProcessResult(
        packet.packet_name,
        packet.packet_code,
        xml_response(response_name, response_code, [("Result", "1")]),
    )


def maybe_wrap_response(packet: B2016Packet, inner_xml: str) -> str:
    if packet.is_soap:
        return soap_response(inner_xml)
    return inner_xml


def extract_host_ip(host_header: str | None, fallback: str = "127.0.0.1") -> str:
    if not host_header:
        return fallback
    host = host_header.strip()
    if host.startswith("["):
        match = re.match(r"^\[([^\]]+)\]", host)
        return match.group(1) if match else fallback
    return host.split(":", 1)[0] or fallback
