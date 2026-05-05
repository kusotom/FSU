from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import html
from time import perf_counter
from urllib.parse import urlparse
import xml.etree.ElementTree as ET

import httpx

from app.core.config import settings
from app.modules.b_interface.logging_utils import sanitize_xml_text
from app.modules.b_interface.wsdl import FSU_NAMESPACE


SOAP_ENV_NS = "http://schemas.xmlsoap.org/soap/envelope/"
SOAP_ENC_NS = "http://schemas.xmlsoap.org/soap/encoding/"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"
XSD_NS = "http://www.w3.org/2001/XMLSchema"


@dataclass
class OutboundCallResult:
    ok: bool
    action: str
    fsu_id: str
    fsu_code: str
    endpoint: str
    dry_run: bool
    request_xml_sanitized: str
    soap_request_sanitized: str
    http_status: int | None
    response_text_sanitized: str
    invoke_return_sanitized: str
    business_name: str
    business_code: str
    error_type: str
    error_message: str
    elapsed_ms: int
    created_at: str
    request_xml: str
    xmlData: str
    soap_request: str
    invoke_return: str = ""


def _utc_now_text() -> str:
    return datetime.now(timezone.utc).isoformat()


def _xml_escape(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=False)


def _response_code(name: str) -> str:
    return {
        "GET_DATA": "401",
        "GET_HISDATA": "601",
        "TIME_CHECK": "1301",
        "GET_FSUINFO": "1701",
        "GET_LOGININFO": "1501",
    }[name]


def _request_xml(name: str, code: str, info_lines: list[str]) -> str:
    joined = "\n".join(info_lines)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<Request>\n"
        "  <PK_Type>\n"
        f"    <Name>{_xml_escape(name)}</Name>\n"
        f"    <Code>{_xml_escape(code)}</Code>\n"
        "  </PK_Type>\n"
        "  <Info>\n"
        f"{joined}\n"
        "  </Info>\n"
        "</Request>\n"
    )


def _device_list_xml(device_list: list[str]) -> list[str]:
    lines = ["    <DeviceList>"]
    for device_code in dict.fromkeys(code for code in device_list if code):
        escaped = _xml_escape(device_code)
        lines.append(f'      <Device Id="{escaped}" Code="{escaped}">{escaped}</Device>')
    lines.append("    </DeviceList>")
    return lines


def build_all_devices_code(seed: str) -> str:
    text = (seed or "").strip()
    length = len(text) if text else 9
    return "9" * max(length, 9)


def build_get_data_xml(fsu_id: str, fsu_code: str, device_list: list[str]) -> str:
    info_lines = [
        f"    <FsuId>{_xml_escape(fsu_id)}</FsuId>",
        f"    <FsuCode>{_xml_escape(fsu_code)}</FsuCode>",
    ]
    info_lines.extend(_device_list_xml(device_list))
    return _request_xml("GET_DATA", _response_code("GET_DATA"), info_lines)


def build_get_hisdata_xml(fsu_id: str, fsu_code: str, device_list: list[str], start_time: str, end_time: str) -> str:
    info_lines = [
        f"    <FsuId>{_xml_escape(fsu_id)}</FsuId>",
        f"    <FsuCode>{_xml_escape(fsu_code)}</FsuCode>",
        f"    <StartTime>{_xml_escape(start_time)}</StartTime>",
        f"    <EndTime>{_xml_escape(end_time)}</EndTime>",
    ]
    info_lines.extend(_device_list_xml(device_list))
    return _request_xml("GET_HISDATA", _response_code("GET_HISDATA"), info_lines)


def build_time_check_xml(fsu_id: str, fsu_code: str) -> str:
    return _request_xml(
        "TIME_CHECK",
        _response_code("TIME_CHECK"),
        [
            f"    <FsuId>{_xml_escape(fsu_id)}</FsuId>",
            f"    <FsuCode>{_xml_escape(fsu_code)}</FsuCode>",
        ],
    )


def build_get_fsuinfo_xml(fsu_id: str, fsu_code: str) -> str:
    return _request_xml(
        "GET_FSUINFO",
        _response_code("GET_FSUINFO"),
        [
            f"    <FsuId>{_xml_escape(fsu_id)}</FsuId>",
            f"    <FsuCode>{_xml_escape(fsu_code)}</FsuCode>",
        ],
    )


def build_get_logininfo_xml(fsu_id: str, fsu_code: str) -> str:
    return _request_xml(
        "GET_LOGININFO",
        _response_code("GET_LOGININFO"),
        [
            f"    <FsuId>{_xml_escape(fsu_id)}</FsuId>",
            f"    <FsuCode>{_xml_escape(fsu_code)}</FsuCode>",
        ],
    )


def build_fsu_service_endpoint(fsu_ip: str) -> str:
    return f"http://{fsu_ip}:8080/services/FSUService"


def build_invoke_soap(xml_data: str, namespace: str = FSU_NAMESPACE) -> str:
    escaped = html.escape(xml_data, quote=False)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<SOAP-ENV:Envelope xmlns:SOAP-ENV="{SOAP_ENV_NS}" '
        f'xmlns:SOAP-ENC="{SOAP_ENC_NS}" xmlns:soapenc="{SOAP_ENC_NS}" '
        f'xmlns:xsi="{XSI_NS}" xmlns:xsd="{XSD_NS}" xmlns:ns1="{namespace}">\n'
        f'  <SOAP-ENV:Body SOAP-ENV:encodingStyle="{SOAP_ENC_NS}">\n'
        "    <ns1:invoke>\n"
        f'      <xmlData xsi:type="soapenc:string">{escaped}</xmlData>\n'
        "    </ns1:invoke>\n"
        "  </SOAP-ENV:Body>\n"
        "</SOAP-ENV:Envelope>\n"
    )


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    if ":" in tag:
        return tag.rsplit(":", 1)[1]
    return tag


def _find_first(root: ET.Element, name: str) -> ET.Element | None:
    for elem in root.iter():
        if _local_name(elem.tag) == name:
            return elem
    return None


def _expected_ack_name(action: str) -> str:
    mapping = {
        "get_data": "GET_DATA_ACK",
        "get_hisdata": "GET_HISDATA_ACK",
        "time_check": "TIME_CHECK_ACK",
        "get_fsuinfo": "GET_FSUINFO_ACK",
        "get_logininfo": "GET_LOGININFO_ACK",
    }
    return mapping.get(action.lower(), "")


def parse_invoke_return(soap_xml: str) -> str:
    try:
        root = ET.fromstring(soap_xml)
    except ET.ParseError as exc:
        raise ValueError(f"invalid SOAP XML: {exc}") from exc
    fault = _find_first(root, "Fault")
    if fault is not None:
        fault_string = _find_first(fault, "faultstring")
        raise ValueError((fault_string.text or "SOAP Fault").strip() if fault_string is not None else "SOAP Fault")
    invoke_return = _find_first(root, "invokeReturn")
    if invoke_return is None:
        invoke_return = _find_first(root, "return")
    if invoke_return is None or not (invoke_return.text or "").strip():
        raise ValueError("SOAP invokeReturn is missing or empty")
    return html.unescape((invoke_return.text or "").strip())


def _result_base(action: str, fsu_id: str, fsu_code: str, endpoint: str, dry_run: bool, request_xml: str, soap_request: str) -> dict:
    return {
        "ok": False,
        "action": action.lower(),
        "fsu_id": fsu_id,
        "fsu_code": fsu_code,
        "endpoint": endpoint,
        "dry_run": dry_run,
        "request_xml_sanitized": sanitize_xml_text(request_xml),
        "soap_request_sanitized": sanitize_xml_text(soap_request),
        "http_status": None,
        "response_text_sanitized": "",
        "invoke_return_sanitized": "",
        "business_name": "",
        "business_code": "",
        "error_type": "unknown_error",
        "error_message": "",
        "elapsed_ms": 0,
        "created_at": _utc_now_text(),
        "request_xml": request_xml,
        "xmlData": request_xml,
        "soap_request": soap_request,
        "invoke_return": "",
    }


def _validate_endpoint(endpoint: str) -> bool:
    parsed = urlparse((endpoint or "").strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _classify_http_error(exc: httpx.HTTPError) -> str:
    if isinstance(exc, httpx.ConnectError):
        return "connection_failed"
    if isinstance(exc, httpx.TimeoutException):
        return "timeout"
    if isinstance(exc, httpx.HTTPStatusError):
        return "http_error"
    if isinstance(exc, httpx.RequestError):
        return "connection_failed"
    return "unknown_error"


def perform_outbound_call(
    *,
    action: str,
    fsu_id: str,
    fsu_code: str,
    endpoint: str,
    xml_data: str,
    dry_run: bool,
    timeout_seconds: float | None = None,
) -> OutboundCallResult:
    soap_request = build_invoke_soap(xml_data)
    base = _result_base(action, fsu_id, fsu_code, endpoint, dry_run, xml_data, soap_request)
    started = perf_counter()
    if not _validate_endpoint(endpoint):
        base.update(
            {
                "error_type": "invalid_endpoint",
                "error_message": "endpoint is missing or invalid",
            }
        )
        base["elapsed_ms"] = int((perf_counter() - started) * 1000)
        return OutboundCallResult(**base)
    if dry_run:
        base.update(
            {
                "ok": True,
                "error_type": "dry_run",
                "error_message": "",
            }
        )
        base["elapsed_ms"] = int((perf_counter() - started) * 1000)
        return OutboundCallResult(**base)

    timeout_value = timeout_seconds if timeout_seconds is not None else settings.b_interface_client_timeout_seconds
    try:
        response = httpx.post(
            endpoint,
            content=soap_request.encode("utf-8"),
            headers={"Content-Type": "text/xml; charset=utf-8", "SOAPAction": '""'},
            timeout=timeout_value,
        )
        base["http_status"] = response.status_code
        response_text = response.text
        base["response_text_sanitized"] = sanitize_xml_text(response_text)
        if response.status_code < 200 or response.status_code >= 300:
            base.update({"error_type": "http_error", "error_message": f"HTTP {response.status_code}"})
            base["elapsed_ms"] = int((perf_counter() - started) * 1000)
            return OutboundCallResult(**base)
        if not response_text.strip():
            base.update({"error_type": "empty_response", "error_message": "HTTP 200 but response body is empty"})
            base["elapsed_ms"] = int((perf_counter() - started) * 1000)
            return OutboundCallResult(**base)
        try:
            root = ET.fromstring(response_text)
        except ET.ParseError as exc:
            base.update({"error_type": "invalid_soap", "error_message": f"invalid SOAP XML: {exc}"})
            base["elapsed_ms"] = int((perf_counter() - started) * 1000)
            return OutboundCallResult(**base)
        fault = _find_first(root, "Fault")
        if fault is not None:
            fault_string = _find_first(fault, "faultstring")
            base.update(
                {
                    "error_type": "soap_fault",
                    "error_message": (fault_string.text or "SOAP Fault").strip() if fault_string is not None else "SOAP Fault",
                }
            )
            base["elapsed_ms"] = int((perf_counter() - started) * 1000)
            return OutboundCallResult(**base)
        invoke_return = _find_first(root, "invokeReturn")
        if invoke_return is None:
            invoke_return = _find_first(root, "return")
        if invoke_return is None or not (invoke_return.text or "").strip():
            base.update({"error_type": "empty_invoke_return", "error_message": "SOAP invokeReturn is missing or empty"})
            base["elapsed_ms"] = int((perf_counter() - started) * 1000)
            return OutboundCallResult(**base)
        business_xml = html.unescape((invoke_return.text or "").strip())
        base["invoke_return"] = business_xml
        base["invoke_return_sanitized"] = sanitize_xml_text(business_xml)
        try:
            business_root = ET.fromstring(business_xml)
        except ET.ParseError as exc:
            base.update({"error_type": "invalid_business_xml", "error_message": f"invalid business XML: {exc}"})
            base["elapsed_ms"] = int((perf_counter() - started) * 1000)
            return OutboundCallResult(**base)
        pk_type = _find_first(business_root, "PK_Type")
        business_name_elem = _find_first(pk_type, "Name") if pk_type is not None else None
        business_code_elem = _find_first(pk_type, "Code") if pk_type is not None else None
        business_name = (business_name_elem.text or "").strip().upper() if business_name_elem is not None and business_name_elem.text else ""
        business_code = (business_code_elem.text or "").strip() if business_code_elem is not None and business_code_elem.text else ""
        base["business_name"] = business_name
        base["business_code"] = business_code
        expected_name = _expected_ack_name(action)
        if expected_name and business_name and business_name != expected_name:
            base.update(
                {
                    "error_type": "unexpected_business_ack",
                    "error_message": f"expected {expected_name}, got {business_name}",
                }
            )
            base["elapsed_ms"] = int((perf_counter() - started) * 1000)
            return OutboundCallResult(**base)
        if not business_name:
            base.update({"error_type": "unsupported_response", "error_message": "business response missing PK_Type/Name"})
            base["elapsed_ms"] = int((perf_counter() - started) * 1000)
            return OutboundCallResult(**base)
        base.update({"ok": True, "error_type": "none", "error_message": ""})
        base["elapsed_ms"] = int((perf_counter() - started) * 1000)
        return OutboundCallResult(**base)
    except httpx.HTTPError as exc:
        base.update({"error_type": _classify_http_error(exc), "error_message": str(exc)})
        base["elapsed_ms"] = int((perf_counter() - started) * 1000)
        return OutboundCallResult(**base)
    except Exception as exc:
        base.update({"error_type": "unknown_error", "error_message": str(exc)})
        base["elapsed_ms"] = int((perf_counter() - started) * 1000)
        return OutboundCallResult(**base)


def call_fsu_invoke(endpoint: str, xml_data: str, timeout_seconds: float | None = None) -> OutboundCallResult:
    return perform_outbound_call(
        action="unknown",
        fsu_id="",
        fsu_code="",
        endpoint=endpoint,
        xml_data=xml_data,
        dry_run=False,
        timeout_seconds=timeout_seconds,
    )
