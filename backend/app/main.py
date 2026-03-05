import asyncio
import logging

import anyio.to_thread
from fastapi import FastAPI, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.api.router import api_router
from app.api.routes.ingest import start_ingest_queue_workers, stop_ingest_queue_workers
from app.core.config import settings
from app.core.security import decode_access_token
from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.models import *  # noqa: F401,F403
from app.models.user import User
from app.services.init_data import seed_alarm_rules, seed_demo_site_data, seed_roles_and_admin
from app.services.metrics import render_prometheus
from app.services.system_rule_worker import system_rule_worker_loop
from app.services.ws_manager import ws_manager

logger = logging.getLogger(__name__)
app = FastAPI(title=settings.app_name, version=settings.app_version)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router, prefix=settings.api_v1_prefix)
system_rule_task: asyncio.Task | None = None


def _ensure_runtime_indexes():
    if settings.database_url.startswith("sqlite"):
        return

    ddl_list = [
        "CREATE INDEX IF NOT EXISTS ix_telemetry_history_point_collected_at ON telemetry_history (point_id, collected_at DESC)",
        "CREATE INDEX IF NOT EXISTS ix_telemetry_latest_collected_at ON telemetry_latest (collected_at DESC)",
        "CREATE INDEX IF NOT EXISTS ix_monitor_point_point_key_device_id ON monitor_point (point_key, device_id)",
    ]
    try:
        with engine.begin() as conn:
            for ddl in ddl_list:
                conn.execute(text(ddl))
    except Exception:
        logger.exception("runtime index ensure failed")


def _ensure_timescaledb_defaults():
    if settings.database_url.startswith("sqlite"):
        return
    if not settings.timescaledb_auto_enable:
        return

    ddl_list = [
        "CREATE EXTENSION IF NOT EXISTS timescaledb;",
        """
        DO $$
        BEGIN
          IF EXISTS (
            SELECT 1
            FROM pg_constraint
            WHERE conname = 'telemetry_history_pkey'
              AND conrelid = 'telemetry_history'::regclass
          ) THEN
            ALTER TABLE telemetry_history DROP CONSTRAINT telemetry_history_pkey;
          END IF;
        END
        $$;
        """,
        """
        DO $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1
            FROM pg_constraint
            WHERE conname = 'telemetry_history_pkey'
              AND conrelid = 'telemetry_history'::regclass
          ) THEN
            ALTER TABLE telemetry_history ADD CONSTRAINT telemetry_history_pkey PRIMARY KEY (id, collected_at);
          END IF;
        END
        $$;
        """,
        """
        SELECT create_hypertable(
          'telemetry_history',
          'collected_at',
          if_not_exists => TRUE,
          migrate_data => TRUE,
          chunk_time_interval => INTERVAL '1 day'
        );
        """,
        """
        ALTER TABLE telemetry_history SET (
          timescaledb.compress,
          timescaledb.compress_segmentby = 'point_id',
          timescaledb.compress_orderby = 'collected_at DESC'
        );
        """,
        "SELECT add_compression_policy('telemetry_history', INTERVAL '7 days', if_not_exists => TRUE);",
        "SELECT add_retention_policy('telemetry_history', INTERVAL '90 days', if_not_exists => TRUE);",
    ]
    try:
        with engine.begin() as conn:
            for ddl in ddl_list:
                conn.execute(text(ddl))
    except Exception:
        logger.exception("timescaledb auto enable failed")


@app.on_event("startup")
async def startup():
    if settings.auto_create_schema:
        Base.metadata.create_all(bind=engine)
        _ensure_timescaledb_defaults()
        _ensure_runtime_indexes()
    db: Session = SessionLocal()
    try:
        seed_roles_and_admin(db)
        seed_alarm_rules(db)
        seed_demo_site_data(db)
        db.commit()
    finally:
        db.close()

    thread_limiter = anyio.to_thread.current_default_thread_limiter()
    thread_limiter.total_tokens = max(settings.ingest_thread_tokens, 40)

    await start_ingest_queue_workers()

    global system_rule_task
    if settings.system_rule_eval_enabled and not settings.system_rule_inline_enabled:
        system_rule_task = asyncio.create_task(system_rule_worker_loop())


@app.on_event("shutdown")
async def shutdown():
    await stop_ingest_queue_workers()

    global system_rule_task
    if system_rule_task is None:
        return
    system_rule_task.cancel()
    try:
        await system_rule_task
    except asyncio.CancelledError:
        pass
    finally:
        system_rule_task = None


@app.get("/health")
def health():
    return {"ok": True, "service": settings.app_name, "version": settings.app_version}


@app.get("/metrics", include_in_schema=False)
def metrics():
    body, content_type = render_prometheus()
    return Response(content=body, media_type=content_type)


@app.websocket("/ws/realtime")
async def realtime_ws(websocket: WebSocket):
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=4401)
        return

    payload = decode_access_token(token)
    if not payload or "sub" not in payload:
        await websocket.close(code=4401)
        return

    db = SessionLocal()
    user = db.scalar(select(User).where(User.username == payload["sub"]))
    db.close()
    if user is None or not user.is_active:
        await websocket.close(code=4401)
        return

    try:
        await ws_manager.connect(websocket, "realtime")
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket, "realtime")
    except Exception:
        ws_manager.disconnect(websocket, "realtime")
        await websocket.close()
