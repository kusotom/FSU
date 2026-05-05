from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse, Response

from app.modules.b_interface.alarm_store import process_send_alarm
from app.modules.b_interface.config_loader import load_b_interface_config
from app.modules.b_interface.logging_utils import BInterfaceInvokeLogger, InvokeLogRecord, sanitize_xml_text, utc_now_text
from app.modules.b_interface.soap import SoapParseError, make_invoke_response, make_soap_fault, parse_soap_request
from app.modules.b_interface.status_store import upsert_login_status
from app.modules.b_interface.wsdl import FSU_NAMESPACE, SC_NAMESPACE, fsu_service_wsdl, sc_service_wsdl
from app.modules.b_interface.xml_protocol import BInterfaceXmlError, build_business_response, parse_b_interface_xml


service_router = APIRouter(tags=["B interface SOAP"])
invoke_logger = BInterfaceInvokeLogger()
logger = logging.getLogger(__name__)


def _xml_response(content: str, status_code: int = 200) -> Response:
    return Response(content=content.encode("utf-8"), media_type="text/xml; charset=utf-8", status_code=status_code)


def _plain_service_message(service_name: str) -> PlainTextResponse:
    return PlainTextResponse(f"{service_name} SOAP 1.1 endpoint. Use ?wsdl or POST invoke(xmlData).")


def _wsdl_requested(request: Request) -> bool:
    query = request.url.query.lower()
    return query == "wsdl" or "wsdl=" in query


def _request_endpoint(request: Request) -> str:
    return str(request.url.replace(query=""))


def _service_name_from_path(path: str) -> str:
    lowered = path.lower()
    if lowered.endswith("/scservice"):
        return "SCService"
    if lowered.endswith("/fsuservice"):
        return "FSUService"
    return "UnknownService"


@service_router.get("/services/SCService")
def get_sc_service(request: Request):
    if _wsdl_requested(request):
        return _xml_response(sc_service_wsdl(_request_endpoint(request)))
    return _plain_service_message("SCService")


@service_router.get("/services/FSUService")
def get_fsu_service(request: Request):
    if _wsdl_requested(request):
        return _xml_response(fsu_service_wsdl(_request_endpoint(request)))
    return _plain_service_message("FSUService")


async def _handle_invoke(request: Request, namespace: str) -> Response:
    remote_addr = request.client.host if request.client else ""
    soap_action = request.headers.get("SOAPAction", "")
    service_name = _service_name_from_path(request.url.path)
    raw_body = await request.body()
    raw_soap_request_sanitized = sanitize_xml_text(raw_body.decode("utf-8", errors="replace"))
    try:
        soap_request = parse_soap_request(
            raw_body,
            request.headers.get("content-type"),
            soap_action,
        )
        parsed = parse_b_interface_xml(soap_request.xml_data)
        config = load_b_interface_config()
        if parsed.message_name == "LOGIN":
            try:
                upsert_login_status(parsed, remote_addr)
            except Exception:
                logger.exception("b-interface login status upsert failed")
        if parsed.message_name == "SEND_ALARM":
            try:
                process_send_alarm(parsed)
            except Exception:
                logger.exception("b-interface alarm persistence failed")
        business_response = build_business_response(parsed, config)
        response_xml = business_response.response_xml
        control_result = business_response.control_result
        timestamp = utc_now_text()
        invoke_logger.write(
            InvokeLogRecord(
                timestamp=timestamp,
                remote_addr=remote_addr,
                service_name=service_name,
                soap_action=soap_request.soap_action,
                message_name=parsed.message_name,
                message_code=parsed.message_code,
                fsu_id=parsed.fsu_id,
                fsu_code=parsed.fsu_code,
                alarm_count=len(parsed.alarms),
                raw_soap_request_sanitized=raw_soap_request_sanitized,
                extracted_xmlData_sanitized=parsed.sanitized_xml,
                response_xml=response_xml,
                parse_ok=True,
                direction=control_result.direction if control_result is not None else "",
                command_name=control_result.command if control_result is not None else "",
                policy_allowed=control_result.policy_allowed if control_result is not None else None,
                blocked=control_result.blocked if control_result is not None else None,
                dry_run=control_result.dry_run if control_result is not None else None,
                executed=control_result.executed if control_result is not None else None,
                reason=control_result.reason if control_result is not None else None,
                correlation_id=f"{service_name}-{timestamp}",
                error=None,
            )
        )
        invoke_logger.save_sample(
            timestamp=timestamp,
            message_name=parsed.message_name,
            xml_text=parsed.sanitized_xml,
        )
        return _xml_response(make_invoke_response(namespace, response_xml))
    except (SoapParseError, BInterfaceXmlError) as exc:
        fault_xml = make_soap_fault(str(exc))
        invoke_logger.write(
            InvokeLogRecord(
                timestamp=utc_now_text(),
                remote_addr=remote_addr,
                service_name=service_name,
                soap_action=soap_action.strip(),
                message_name="",
                message_code="",
                fsu_id="",
                fsu_code="",
                alarm_count=0,
                raw_soap_request_sanitized=raw_soap_request_sanitized,
                extracted_xmlData_sanitized="",
                response_xml=fault_xml,
                parse_ok=False,
                direction="SC_TO_FSU" if "SET_" in raw_soap_request_sanitized or "UPGRADE" in raw_soap_request_sanitized else "",
                command_name="UNKNOWN_CONTROL_COMMAND" if "SET_" in raw_soap_request_sanitized or "UPGRADE" in raw_soap_request_sanitized else "",
                policy_allowed=False if "SET_" in raw_soap_request_sanitized or "UPGRADE" in raw_soap_request_sanitized else None,
                blocked=True if "SET_" in raw_soap_request_sanitized or "UPGRADE" in raw_soap_request_sanitized else None,
                dry_run=True if "SET_" in raw_soap_request_sanitized or "UPGRADE" in raw_soap_request_sanitized else None,
                executed=False if "SET_" in raw_soap_request_sanitized or "UPGRADE" in raw_soap_request_sanitized else None,
                reason="parse_error" if "SET_" in raw_soap_request_sanitized or "UPGRADE" in raw_soap_request_sanitized else None,
                correlation_id=f"{service_name}-{utc_now_text()}",
                error=str(exc),
            )
        )
        return _xml_response(fault_xml, status_code=400)


@service_router.post("/services/SCService")
async def post_sc_service(request: Request):
    return await _handle_invoke(request, SC_NAMESPACE)


@service_router.post("/services/FSUService")
async def post_fsu_service(request: Request):
    return await _handle_invoke(request, FSU_NAMESPACE)
