from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import Response

from app.core.config import settings
from app.modules.fsu_gateway.service import SOAP_RESPONSE, get_fsu_gateway

health_router = APIRouter(tags=["FSU gateway"])
soap_router = APIRouter(tags=["FSU gateway"])


@health_router.get("/fsu-gateway/health")
def health():
    return get_fsu_gateway().health()


@soap_router.post("/services/SCService")
async def sc_service(request: Request):
    body = await request.body()
    request_url = str(request.url)
    local_port = request.url.port or settings.fsu_soap_port
    get_fsu_gateway().record_soap_request(
        method=request.method,
        url=request_url,
        headers=dict(request.headers),
        body=body,
        remote_ip=request.client.host if request.client else None,
        local_port=local_port,
        request_path=request.url.path,
    )
    return Response(content=SOAP_RESPONSE.encode("utf-8"), media_type="text/xml; charset=utf-8")
