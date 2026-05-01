from __future__ import annotations

from fastapi import FastAPI

from app.core.config import settings
from app.modules.fsu_gateway import get_fsu_gateway
from app.modules.fsu_gateway.routes import health_router, soap_router

app = FastAPI(title="FSU Gateway Probe", version=settings.app_version)
app.include_router(health_router)
if settings.fsu_gateway_enabled:
    app.include_router(soap_router)


@app.on_event("startup")
async def startup() -> None:
    await get_fsu_gateway().start()


@app.on_event("shutdown")
async def shutdown() -> None:
    await get_fsu_gateway().stop()
