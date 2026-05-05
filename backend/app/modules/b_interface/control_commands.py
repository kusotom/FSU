from __future__ import annotations

from dataclasses import dataclass, field
import html
from typing import TYPE_CHECKING
from typing import Iterable
import xml.etree.ElementTree as ET

from app.modules.b_interface.command_policy import (
    BInterfaceCommandPolicy,
    CommandPolicyDecision,
    evaluate_command_policy,
)
from app.modules.b_interface.logging_utils import sanitize_xml_text

if TYPE_CHECKING:
    from app.modules.b_interface.xml_protocol import ParsedBInterfaceMessage


UPGRADE_COMMANDS = {"AUTO_UPGRADE", "SET_AUTOUPGRADE", "SET_FSUUPGRADE", "SET_UPGRADE"}
KNOWN_CONTROL_COMMANDS = {"SET_FSUREBOOT", *UPGRADE_COMMANDS}
NON_CONTROL_SET_COMMANDS = {"SET_LOGININFO"}
SENSITIVE_PARAM_NAMES = {
    "password",
    "passwd",
    "pwd",
    "token",
    "secret",
    "authorization",
    "ftp_password",
    "ftppassword",
    "ftp_pwd",
}


@dataclass(frozen=True)
class ControlCommandDetection:
    is_control_command: bool
    command_name: str
    normalized_name: str


@dataclass(frozen=True)
class ControlCommandResult:
    command: str
    direction: str
    allowed: bool
    blocked: bool
    dry_run: bool
    executed: bool
    reason: str
    parse_ok: bool
    policy_allowed: bool
    result_code: str
    result_desc: str
    fsu_id: str
    fsu_code: str
    params: dict[str, str] = field(default_factory=dict)
    response_xml: str = ""
    response_xml_sanitized: str = ""
    request_xml_sanitized: str = ""
    error_message: str = ""
    message_name: str = ""
    message_code: str = ""


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


def _code_plus_one(message_code: str, fallback: str) -> str:
    try:
        return str(int(message_code) + 1)
    except (TypeError, ValueError):
        return fallback


def _xml_escape(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=False)


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


def detect_control_command(parsed_request: ParsedBInterfaceMessage) -> ControlCommandDetection:
    normalized = (parsed_request.message_name or "").strip().upper()
    if normalized in NON_CONTROL_SET_COMMANDS:
        return ControlCommandDetection(False, "", normalized)
    if normalized in KNOWN_CONTROL_COMMANDS:
        return ControlCommandDetection(True, normalized, normalized)
    if ("UPGRADE" in normalized or "REBOOT" in normalized or normalized.startswith("SET_FSU")) or normalized == "SET_SOMETHING":
        return ControlCommandDetection(True, "UNKNOWN_CONTROL_COMMAND", normalized)
    return ControlCommandDetection(False, "", normalized)


def _extract_control_params(raw_xml: str) -> dict[str, str]:
    if not raw_xml.strip():
        return {}
    root = ET.fromstring(raw_xml.strip())
    info = _child(root, "Info")
    if info is None:
        return {}
    params: dict[str, str] = {}
    for elem in list(info):
        name = _local_name(elem.tag)
        if name == "DeviceList":
            devices = []
            for device in list(elem):
                device_id = device.attrib.get("Id") or device.attrib.get("Code") or (device.text or "").strip()
                if device_id:
                    devices.append(device_id)
            if devices:
                params["device_list"] = ",".join(devices)
            continue
        value = (elem.text or "").strip()
        if not value and elem.attrib:
            value = json_like_attrs(elem.attrib)
        if value:
            params[name] = "***" if name.lower() in SENSITIVE_PARAM_NAMES else value
    return params


def json_like_attrs(attrs: dict[str, str]) -> str:
    parts = []
    for key, value in attrs.items():
        parts.append(f"{key}={value}")
    return ",".join(parts)


def _fallback_ack_name(parsed_request: ParsedBInterfaceMessage) -> str:
    normalized = (parsed_request.message_name or "").strip().upper()
    if normalized:
        return f"{normalized}_ACK"
    return "ERROR_ACK"


def _build_control_response(parsed_request: ParsedBInterfaceMessage, command_name: str, decision: CommandPolicyDecision) -> str:
    ack_name = _fallback_ack_name(parsed_request)
    fallback_code = "1702" if command_name == "SET_FSUREBOOT" else "602"
    return _response_xml(
        ack_name,
        _code_plus_one(parsed_request.message_code, fallback_code),
        (
            f"    <Result>{'1' if decision.allowed else '0'}</Result>",
            f"    <Status>{_xml_escape('accepted_dry_run' if decision.allowed else 'blocked_by_policy')}</Status>",
            f"    <Allowed>{str(decision.allowed).lower()}</Allowed>",
            f"    <Blocked>{str(decision.blocked).lower()}</Blocked>",
            f"    <DryRun>{str(decision.dry_run).lower()}</DryRun>",
            "    <Executed>false</Executed>",
            f"    <Reason>{_xml_escape(decision.reason)}</Reason>",
            f"    <ResultCode>{_xml_escape(decision.reason)}</ResultCode>",
            f"    <ResultDesc>{_xml_escape('accepted_dry_run' if decision.allowed else 'disabled_by_default')}</ResultDesc>",
        ),
    )


def handle_sc_to_fsu_control_command(
    parsed_request: ParsedBInterfaceMessage,
    policy: BInterfaceCommandPolicy | None = None,
) -> ControlCommandResult:
    detection = detect_control_command(parsed_request)
    if not detection.is_control_command:
        raise ValueError("not a control command")
    effective_command = detection.command_name
    decision = evaluate_command_policy(detection.command_name if detection.command_name != "UNKNOWN_CONTROL_COMMAND" else "", policy)
    if effective_command == "UNKNOWN_CONTROL_COMMAND":
        decision = CommandPolicyDecision(
            allowed=False,
            blocked=True,
            reason="unknown_control_command",
            dry_run=True,
            command_name=effective_command,
            executed=False,
        )
    response_xml = _build_control_response(parsed_request, effective_command, decision)
    return ControlCommandResult(
        command=effective_command,
        direction="SC_TO_FSU",
        allowed=decision.allowed,
        blocked=decision.blocked,
        dry_run=decision.dry_run,
        executed=False,
        reason=decision.reason,
        parse_ok=True,
        policy_allowed=decision.allowed,
        result_code=decision.reason,
        result_desc="accepted_dry_run" if decision.allowed else "disabled_by_default" if decision.reason == "disabled_by_default" else decision.reason,
        fsu_id=parsed_request.fsu_id,
        fsu_code=parsed_request.fsu_code,
        params=_extract_control_params(parsed_request.raw_xml),
        response_xml=response_xml,
        response_xml_sanitized=sanitize_xml_text(response_xml),
        request_xml_sanitized=parsed_request.sanitized_xml,
        error_message="",
        message_name=parsed_request.message_name,
        message_code=parsed_request.message_code,
    )


def handle_sc_to_fsu_control_xml(
    xml_text: str,
    policy: BInterfaceCommandPolicy | None = None,
) -> ControlCommandResult:
    try:
        from app.modules.b_interface.xml_protocol import parse_b_interface_xml

        parsed = parse_b_interface_xml(xml_text)
    except Exception as exc:
        return ControlCommandResult(
            command="UNKNOWN_CONTROL_COMMAND",
            direction="SC_TO_FSU",
            allowed=False,
            blocked=True,
            dry_run=True,
            executed=False,
            reason="parse_error",
            parse_ok=False,
            policy_allowed=False,
            result_code="parse_error",
            result_desc="invalid control XML",
            fsu_id="",
            fsu_code="",
            params={},
            response_xml="",
            response_xml_sanitized="",
            request_xml_sanitized=sanitize_xml_text(xml_text),
            error_message=str(exc),
            message_name="",
            message_code="",
        )
    try:
        return handle_sc_to_fsu_control_command(parsed, policy)
    except Exception as exc:
        return ControlCommandResult(
            command="UNKNOWN_CONTROL_COMMAND",
            direction="SC_TO_FSU",
            allowed=False,
            blocked=True,
            dry_run=True,
            executed=False,
            reason="policy_blocked",
            parse_ok=False,
            policy_allowed=False,
            result_code="policy_blocked",
            result_desc="control command handling failed",
            fsu_id=parsed.fsu_id,
            fsu_code=parsed.fsu_code,
            params={},
            response_xml="",
            response_xml_sanitized="",
            request_xml_sanitized=parsed.sanitized_xml,
            error_message=str(exc),
            message_name=parsed.message_name,
            message_code=parsed.message_code,
        )
