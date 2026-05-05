from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import html
from typing import Iterable
import xml.etree.ElementTree as ET

from app.core.config import settings
from app.modules.b_interface.config_loader import BInterfaceConfig, DeviceRecord
from app.modules.b_interface.control_commands import detect_control_command, handle_sc_to_fsu_control_command
from app.modules.b_interface.logging_utils import sanitize_xml_text


@dataclass(frozen=True)
class AlarmRecord:
    serial_no: str = ""
    id: str = ""
    fsu_id: str = ""
    fsu_code: str = ""
    alarm_time: str = ""
    alarm_level: str = ""
    alarm_flag: str = ""
    alarm_desc: str = ""
    device_id: str = ""
    device_code: str = ""
    signal_id: str = ""
    signal_number: str = ""
    measured_val: str = ""
    status: str = ""


@dataclass(frozen=True)
class DeviceEnvelope:
    id: str = ""
    code: str = ""


@dataclass(frozen=True)
class ParsedBInterfaceMessage:
    root_name: str
    message_name: str
    message_code: str
    fsu_id: str
    fsu_code: str
    username: str
    password: str
    fsu_ip: str = ""
    mac_id: str = ""
    reg_mode: str = ""
    fsu_vendor: str = ""
    fsu_type: str = ""
    fsu_class: str = ""
    version: str = ""
    dict_version: str = ""
    devices: tuple[DeviceEnvelope, ...] = field(default_factory=tuple)
    alarms: tuple[AlarmRecord, ...] = field(default_factory=tuple)
    raw_xml: str = ""
    sanitized_xml: str = ""


@dataclass(frozen=True)
class BusinessResponse:
    response_xml: str
    message_kind: str
    control_result: object | None = None


class BInterfaceXmlError(ValueError):
    pass


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


def _text(root: ET.Element | None, name: str, default: str = "") -> str:
    elem = _child(root, name)
    if elem is None or elem.text is None:
        return default
    return elem.text.strip()


def _text_any(root: ET.Element | None, names: Iterable[str], default: str = "") -> str:
    for name in names:
        value = _text(root, name)
        if value:
            return value
    return default


def _iter_named(root: ET.Element | None, name: str) -> Iterable[ET.Element]:
    if root is None:
        return ()
    return (elem for elem in root.iter() if _local_name(elem.tag) == name)


def _attr_any(root: ET.Element | None, names: Iterable[str]) -> str:
    if root is None:
        return ""
    lowered = {key.lower(): value for key, value in root.attrib.items()}
    for name in names:
        if name in root.attrib and root.attrib[name]:
            return root.attrib[name].strip()
        match = lowered.get(name.lower())
        if match:
            return match.strip()
    return ""


def _all_children(root: ET.Element | None, name: str) -> list[ET.Element]:
    if root is None:
        return []
    return [elem for elem in list(root) if _local_name(elem.tag) == name]


def parse_b_interface_xml(xml_data: str) -> ParsedBInterfaceMessage:
    if not xml_data or not xml_data.strip():
        raise BInterfaceXmlError("xmlData is empty")
    try:
        root = ET.fromstring(xml_data.strip())
    except ET.ParseError as exc:
        raise BInterfaceXmlError(f"invalid business XML: {exc}") from exc

    root_name = _local_name(root.tag)
    if root_name not in {"Request", "Response"}:
        raise BInterfaceXmlError(f"unsupported business XML root: {root_name}")

    pk_type = _child(root, "PK_Type")
    if pk_type is None:
        raise BInterfaceXmlError("missing PK_Type")
    message_name = _text(pk_type, "Name").upper()
    message_code = _text(pk_type, "Code")
    if not message_name:
        raise BInterfaceXmlError("missing PK_Type/Name")

    info = _child(root, "Info")
    fsu_id = _text_any(info, ("FsuId", "FsuID"))
    fsu_code = _text_any(info, ("FsuCode", "FsuID", "FsuId"))
    username = _text_any(info, ("UserName",))
    password = _text_any(info, ("PaSCword", "PaSCWord", "PassWord", "Password", "pwd", "FTPPwd", "IPSecPwd"))
    fsu_ip = _text_any(info, ("FsuIP", "FsuIp", "IP"))
    mac_id = _text_any(info, ("MacId",))
    reg_mode = _text_any(info, ("Reg_Mode",))
    fsu_vendor = _text_any(info, ("FSUVendor",))
    fsu_type = _text_any(info, ("FSUType",))
    fsu_class = _text_any(info, ("FSUClass",))
    version = _text_any(info, ("Version",))
    dict_version = _text_any(info, ("DictVersion",))

    devices_root = _child(info, "DeviceList")
    devices: list[DeviceEnvelope] = []
    for device in _all_children(devices_root, "Device"):
        text_value = (device.text or "").strip()
        devices.append(
            DeviceEnvelope(
                id=_attr_any(device, ("Id", "ID", "DeviceId", "Code")) or text_value,
                code=_attr_any(device, ("Code", "DeviceCode", "Id", "ID")) or text_value,
            )
        )

    alarms: list[AlarmRecord] = []
    values = _child(info, "Values")
    t_alarm_list = _child(values, "TAlarmList") if values is not None else None
    alarm_candidates = _all_children(t_alarm_list, "TAlarm") if t_alarm_list is not None else []
    if not alarm_candidates:
        alarm_candidates = [elem for elem in root.iter() if _local_name(elem.tag) in {"Alarm", "TAlarm"}]
    for alarm in alarm_candidates:
        alarms.append(
            AlarmRecord(
                serial_no=_text_any(alarm, ("SerialNo",)),
                id=_text_any(alarm, ("Id", "ID")),
                fsu_id=_text_any(alarm, ("FsuId", "FsuID")),
                fsu_code=_text_any(alarm, ("FsuCode", "FsuID", "FsuId")),
                alarm_time=_text_any(alarm, ("AlarmTime",)),
                alarm_level=_text_any(alarm, ("AlarmLevel",)),
                alarm_flag=_text_any(alarm, ("AlarmFlag",)),
                alarm_desc=_text_any(alarm, ("AlarmDesc",)),
                device_id=_text_any(alarm, ("DeviceId",)),
                device_code=_text_any(alarm, ("DeviceCode",)),
                signal_id=_text_any(alarm, ("SignalId",)),
                signal_number=_text_any(alarm, ("SignalNumber",)),
                measured_val=_text_any(alarm, ("MeasuredVal",)),
                status=_text_any(alarm, ("Status",)),
            )
        )
    if (not fsu_id or not fsu_code) and alarms:
        first_alarm = alarms[0]
        fsu_id = fsu_id or first_alarm.fsu_id or first_alarm.fsu_code
        fsu_code = fsu_code or first_alarm.fsu_code or first_alarm.fsu_id

    return ParsedBInterfaceMessage(
        root_name=root_name,
        message_name=message_name,
        message_code=message_code,
        fsu_id=fsu_id,
        fsu_code=fsu_code,
        username=username,
        password=password,
        fsu_ip=fsu_ip,
        mac_id=mac_id,
        reg_mode=reg_mode,
        fsu_vendor=fsu_vendor,
        fsu_type=fsu_type,
        fsu_class=fsu_class,
        version=version,
        dict_version=dict_version,
        devices=tuple(devices),
        alarms=tuple(alarms),
        raw_xml=xml_data,
        sanitized_xml=sanitize_xml_text(xml_data),
    )


def _xml_escape(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=False)


def _device_list_xml(devices: Iterable[DeviceRecord]) -> str:
    lines = ["    <DeviceList>"]
    for device in devices:
        lines.append(
            f'      <Device Id="{_xml_escape(device.id)}" Code="{_xml_escape(device.code)}" Name="{_xml_escape(device.name)}" />'
        )
    lines.append("    </DeviceList>")
    return "\n".join(lines)


def _response_xml(name: str, code: str, info_lines: Iterable[str]) -> str:
    joined = "\n".join(info_lines)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<Response>\n"
        "  <PK_Type>\n"
        f"    <Name>{_xml_escape(name)}</Name>\n"
        f"    <Code>{_xml_escape(code)}</Code>\n"
        "  </PK_Type>\n"
        "  <Info>\n"
        f"{joined}\n"
        "  </Info>\n"
        "</Response>\n"
    )


def _code_plus_one(message_code: str, fallback: str) -> str:
    try:
        return str(int(message_code) + 1)
    except (TypeError, ValueError):
        return fallback


def _device_records_from_request(parsed: ParsedBInterfaceMessage, config: BInterfaceConfig) -> tuple[DeviceRecord, ...]:
    if parsed.devices:
        return tuple(
            DeviceRecord(
                name="",
                type="",
                id=device.id or device.code,
                code=device.code or device.id,
            )
            for device in parsed.devices
            if device.id or device.code
        ) or config.devices
    return config.devices


def build_business_response(parsed: ParsedBInterfaceMessage, config: BInterfaceConfig) -> BusinessResponse:
    fsu_id = parsed.fsu_id or config.fsu_id
    fsu_code = parsed.fsu_code or config.fsu_code
    name = parsed.message_name
    detection = detect_control_command(parsed)
    if detection.is_control_command:
        control = handle_sc_to_fsu_control_command(parsed)
        return BusinessResponse(response_xml=control.response_xml, message_kind=control.command, control_result=control)

    if name == "LOGIN":
        response_mode = (settings.b_interface_response_mode or "compat").strip().lower()
        if response_mode == "strict":
            info_lines = (
                f"    <SCIP>{_xml_escape(config.sc_ip or '192.168.100.123')}</SCIP>",
                "    <RightLevel>2</RightLevel>",
            )
        else:
            info_lines = (
                f"    <FsuId>{_xml_escape(fsu_id)}</FsuId>",
                f"    <FsuCode>{_xml_escape(fsu_code)}</FsuCode>",
                "    <RightLevel>2</RightLevel>",
                f"    <SCIP>{_xml_escape(config.sc_ip or '192.168.100.123')}</SCIP>",
                "    <Result>1</Result>",
            )
        xml_text = _response_xml(
            "LOGIN_ACK",
            "102",
            info_lines,
        )
        return BusinessResponse(response_xml=xml_text, message_kind="LOGIN")

    if name == "GET_DATA":
        devices = _device_records_from_request(parsed, config)
        xml_text = _response_xml(
            "GET_DATA_ACK",
            "402",
            (
                f"    <FsuId>{_xml_escape(fsu_id)}</FsuId>",
                f"    <FsuCode>{_xml_escape(fsu_code)}</FsuCode>",
                _device_list_xml(devices),
                "    <Result>1</Result>",
            ),
        )
        return BusinessResponse(response_xml=xml_text, message_kind="GET_DATA")

    if name == "SEND_ALARM":
        response_mode = (settings.b_interface_response_mode or "compat").strip().lower()
        if response_mode == "strict":
            info_lines = (
                "    <Result>1</Result>",
            )
        else:
            info_lines = (
                f"    <FsuId>{_xml_escape(fsu_id)}</FsuId>",
                f"    <FsuCode>{_xml_escape(fsu_code)}</FsuCode>",
                f"    <AlarmCount>{_xml_escape(len(parsed.alarms))}</AlarmCount>",
                "    <Result>1</Result>",
            )
        xml_text = _response_xml(
            "SEND_ALARM_ACK",
            "502",
            info_lines,
        )
        return BusinessResponse(response_xml=xml_text, message_kind="SEND_ALARM")

    if name == "TIME_CHECK":
        xml_text = _response_xml(
            "TIME_CHECK_ACK",
            _code_plus_one(parsed.message_code, "1302"),
            (
                f"    <Time>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</Time>",
                "    <Result>1</Result>",
            ),
        )
        return BusinessResponse(response_xml=xml_text, message_kind="TIME_CHECK")

    if name == "GET_FSUINFO":
        vendor = config.monitor_units.fsu_vendor or "Unknown"
        fsu_type = config.monitor_units.fsu_type or "PrototypeFSU"
        fsu_class = config.monitor_units.fsu_class or "PrototypeClass"
        xml_text = _response_xml(
            "GET_FSUINFO_ACK",
            _code_plus_one(parsed.message_code, "1202"),
            (
                f"    <FsuId>{_xml_escape(fsu_id)}</FsuId>",
                f"    <FsuCode>{_xml_escape(fsu_code)}</FsuCode>",
                f"    <FSUVendor>{_xml_escape(vendor)}</FSUVendor>",
                f"    <FSUType>{_xml_escape(fsu_type)}</FSUType>",
                f"    <FSUClass>{_xml_escape(fsu_class)}</FSUClass>",
                "    <Result>1</Result>",
            ),
        )
        return BusinessResponse(response_xml=xml_text, message_kind="GET_FSUINFO")

    if name == "GET_LOGININFO":
        xml_text = _response_xml(
            "GET_LOGININFO_ACK",
            _code_plus_one(parsed.message_code, "1502"),
            (
                f"    <SCIP>{_xml_escape(config.sc_ip)}</SCIP>",
                "    <Port>8080</Port>",
                "    <ServicePath>/services/SCService</ServicePath>",
                "    <Result>1</Result>",
            ),
        )
        return BusinessResponse(response_xml=xml_text, message_kind="GET_LOGININFO")

    if name == "SET_LOGININFO":
        xml_text = _response_xml(
            "SET_LOGININFO_ACK",
            _code_plus_one(parsed.message_code, "1504"),
            (
                "    <Result>1</Result>",
                "    <Status>ignored_in_prototype</Status>",
                "    <Persisted>false</Persisted>",
            ),
        )
        return BusinessResponse(response_xml=xml_text, message_kind="SET_LOGININFO")

    xml_text = _response_xml(
        "ERROR_ACK",
        "900",
        (
            "    <Result>0</Result>",
            "    <Error>unsupported_in_prototype</Error>",
            f"    <MessageType>{_xml_escape(name)}</MessageType>",
        ),
    )
    return BusinessResponse(response_xml=xml_text, message_kind="UNKNOWN")
