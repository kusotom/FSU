from __future__ import annotations

import json

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.b_device import BDevice, BDeviceConfig
from app.services.b_interface_2016 import (
    B2016_NS,
    FSU_SERVICE_NS,
    extract_host_ip,
    maybe_wrap_response,
    parse_packet,
    process_packet,
    request_xml,
    soap_request,
    vertiv_get_data_xml,
    vertiv_get_fsuinfo_xml,
    wsdl_response,
    xml_response,
)


router = APIRouter(prefix="/b-interface/2016", tags=["B interface 2016"])
service_router = APIRouter(tags=["B interface 2016 service"])


class B2016PollRequest(BaseModel):
    target_url: str = Field(..., description="FSU service URL, for example http://10.10.10.2:8080/services/FSUService")
    command: str = Field(default="GET_DATA", description="B interface command name")
    code: str | None = Field(default=None, description="B interface command code")
    fsu_code: str | None = Field(default=None, description="FsuCode/FsuId to include in Info")
    raw_xml: str | None = Field(default=None, description="Use this raw B-interface XML instead of generated XML")
    soap: bool = Field(default=True, description="Wrap the request in gSOAP invoke/xmlData")
    soap_namespace: str | None = Field(default=None, description="SOAP invoke namespace override")
    soap_action: str = Field(default='""', description="SOAPAction header value")
    timeout_seconds: float = Field(default=10.0, ge=1.0, le=60.0)


class VertivPollRequest(BaseModel):
    command: str = Field(default="GET_DATA", description="GET_DATA or GET_FSUINFO")
    port: int = Field(default=8080, ge=1, le=65535)
    path: str = Field(default="/")
    soap: bool = Field(default=True)
    timeout_seconds: float = Field(default=10.0, ge=1.0, le=60.0)


DEFAULT_COMMAND_CODES = {
    "GET_FSUINFO": "101",
    "GET_DATA": "401",
    "GET_HISDATA": "403",
    "TIME_CHECK": "1301",
    "GET_LOGININFO": "1501",
    "GET_FTP": "1601",
    "GET_THRESHOLD": "1901",
}


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def xml_http_response(content: str) -> Response:
    return Response(content=content.encode("utf-8"), media_type="text/xml; charset=utf-8")


def vertiv_device_codes(db: Session, device: BDevice) -> list[str]:
    config = db.scalar(
        select(BDeviceConfig).where(
            BDeviceConfig.device_id == device.id,
            BDeviceConfig.config_key == "DeviceList",
        )
    )
    if config is None or not config.config_value:
        return []
    try:
        parsed = json.loads(config.config_value)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(value) for value in parsed if value]


async def handle_b2016_request(request: Request, db: Session) -> Response:
    raw = await request.body()
    if not raw:
        raise HTTPException(status_code=400, detail="empty B interface payload")
    try:
        packet = parse_packet(raw)
        result = process_packet(raw, db, sc_ip=extract_host_ip(request.headers.get("host")))
        response_xml = maybe_wrap_response(packet, result.response_xml)
        return xml_http_response(response_xml)
    except ValueError as exc:
        response_xml = xml_response("ERROR_ACK", "500", [("Result", "0"), ("Error", str(exc))])
        return xml_http_response(response_xml)


@router.post("/invoke")
async def invoke_2016(request: Request, db: Session = Depends(get_db)):
    return await handle_b2016_request(request, db)


@router.get("/health")
def health():
    return {"status": "ok", "service": "B interface 2016"}


@router.post("/poll")
async def poll_fsu(data: B2016PollRequest, request: Request, db: Session = Depends(get_db)):
    command = data.command.strip().upper()
    code = data.code or DEFAULT_COMMAND_CODES.get(command, "401")
    if data.raw_xml:
        inner_xml = data.raw_xml
    else:
        info_items: list[tuple[str, str]] = []
        if data.fsu_code:
            info_items.extend([("FsuId", data.fsu_code), ("FsuCode", data.fsu_code)])
        inner_xml = request_xml(command, code, info_items)

    outbound_body = soap_request(inner_xml, namespace=data.soap_namespace or B2016_NS) if data.soap else inner_xml
    try:
        async with httpx.AsyncClient(timeout=data.timeout_seconds) as client:
            upstream = await client.post(
                data.target_url,
                content=outbound_body.encode("utf-8"),
                headers={
                    "Content-Type": "text/xml; charset=utf-8",
                    "SOAPAction": data.soap_action if data.soap else "",
                },
            )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"B interface poll failed: {exc}") from exc

    response_text = upstream.text
    result: dict[str, object] = {
        "target_url": data.target_url,
        "request_command": command,
        "request_code": code,
        "upstream_status": upstream.status_code,
        "processed": False,
        "response_preview": response_text[:2000],
    }
    if not upstream.content:
        return result

    try:
        packet = parse_packet(upstream.content)
        processed = process_packet(
            upstream.content,
            db,
            sc_ip=extract_host_ip(request.headers.get("host")),
        )
    except ValueError as exc:
        result["error"] = str(exc)
        return result

    result.update(
        {
            "processed": True,
            "response_packet": packet.packet_name,
            "response_code": packet.packet_code,
            "ingested_metrics": processed.ingested_metrics,
            "ingested_alarms": processed.ingested_alarms,
            "updated_devices": processed.updated_devices,
            "ack": processed.response_xml,
        }
    )
    return result


@router.post("/vertiv/{fsu_code}/poll")
async def poll_vertiv_fsu(fsu_code: str, data: VertivPollRequest, request: Request, db: Session = Depends(get_db)):
    device = db.scalar(select(BDevice).where(BDevice.device_code == fsu_code))
    if device is None:
        raise HTTPException(status_code=404, detail="FSU has not logged in through B interface 2016")
    if not device.ip_address:
        raise HTTPException(status_code=409, detail="FSU login did not include FsuIP")

    command = data.command.strip().upper()
    if command == "GET_FSUINFO":
        inner_xml = vertiv_get_fsuinfo_xml(fsu_code)
    elif command == "GET_DATA":
        inner_xml = vertiv_get_data_xml(fsu_code, vertiv_device_codes(db, device))
    else:
        raise HTTPException(status_code=400, detail="Vertiv poll command must be GET_DATA or GET_FSUINFO")

    path = data.path if data.path.startswith("/") else f"/{data.path}"
    target_url = f"http://{device.ip_address}:{data.port}{path}"
    return await poll_fsu(
        B2016PollRequest(
            target_url=target_url,
            command=command,
            code=DEFAULT_COMMAND_CODES[command],
            fsu_code=fsu_code,
            raw_xml=inner_xml,
            soap=data.soap,
            soap_namespace=FSU_SERVICE_NS,
            soap_action='""',
            timeout_seconds=data.timeout_seconds,
        ),
        request,
        db,
    )


@service_router.get("/services/SCService")
@service_router.get("/services/FSUService")
def service_wsdl(request: Request):
    query = request.url.query.lower()
    if query == "wsdl" or request.url.path.lower().endswith(".wsdl"):
        return xml_http_response(wsdl_response())
    return {"status": "ok", "service": "B interface 2016 SCService"}


@service_router.post("/services/SCService")
@service_router.post("/services/FSUService")
async def service_invoke(request: Request, db: Session = Depends(get_db)):
    return await handle_b2016_request(request, db)


@service_router.post("/services")
async def service_invoke_short(request: Request, db: Session = Depends(get_db)):
    return await handle_b2016_request(request, db)
