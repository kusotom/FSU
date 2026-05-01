import asyncio
import logging

import anyio.to_thread
from fastapi import FastAPI, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect, select, text
from sqlalchemy.orm import Session

from app.api.router import api_router
from app.api.routes.b_interface_2016 import service_router as b_interface_2016_service_router
from app.api.routes.ingest import start_ingest_queue_workers, stop_ingest_queue_workers
from app.core.config import settings
from app.core.security import decode_access_token
from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.models import *  # noqa: F401,F403
from app.models.user import User
from app.modules.fsu_gateway import get_fsu_gateway
from app.modules.fsu_gateway.routes import health_router as fsu_gateway_health_router
from app.modules.fsu_gateway.routes import soap_router as fsu_gateway_soap_router
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
app.include_router(fsu_gateway_health_router)
if settings.fsu_gateway_enabled:
    app.include_router(fsu_gateway_soap_router)
app.include_router(b_interface_2016_service_router)
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


def _ensure_notify_schema():
    if settings.database_url.startswith("sqlite"):
        return
    ddl_list = [
        "ALTER TABLE notify_policy ADD COLUMN IF NOT EXISTS channel_ids VARCHAR(255)",
        """
        UPDATE notify_policy
        SET channel_ids = channel_id::text
        WHERE (channel_ids IS NULL OR channel_ids = '') AND channel_id IS NOT NULL
        """,
    ]
    try:
        with engine.begin() as conn:
            for ddl in ddl_list:
                conn.execute(text(ddl))
    except Exception:
        logger.exception("notify schema ensure failed")


def _ensure_sms_auth_schema():
    ddl_list = [
        "ALTER TABLE sys_user ADD COLUMN phone_country_code VARCHAR(8) DEFAULT '+86'",
        "ALTER TABLE sys_user ADD COLUMN phone VARCHAR(20)",
        "ALTER TABLE sys_user ADD COLUMN status VARCHAR(16) DEFAULT 'PENDING'",
        "ALTER TABLE sys_user ADD COLUMN phone_verified_at TIMESTAMP",
        "ALTER TABLE sys_user ADD COLUMN activated_at TIMESTAMP",
        "ALTER TABLE sys_user ADD COLUMN last_login_at TIMESTAMP",
        "ALTER TABLE sys_user ADD COLUMN locked_until TIMESTAMP",
        "ALTER TABLE sys_user ADD COLUMN login_fail_count INTEGER DEFAULT 0",
        "ALTER TABLE sys_user ADD COLUMN phone_login_enabled BOOLEAN DEFAULT TRUE",
        """
        CREATE TABLE IF NOT EXISTS sms_code_log (
          id INTEGER PRIMARY KEY,
          request_id VARCHAR(64) NOT NULL UNIQUE,
          scene VARCHAR(16) NOT NULL,
          phone_country_code VARCHAR(8) NOT NULL,
          phone VARCHAR(20) NOT NULL,
          user_id INTEGER NULL,
          tenant_id INTEGER NULL,
          code_hash VARCHAR(255) NOT NULL,
          expires_at TIMESTAMP NOT NULL,
          send_status VARCHAR(16) NOT NULL DEFAULT 'SUCCESS',
          verify_status VARCHAR(16) NOT NULL DEFAULT 'PENDING',
          attempt_count INTEGER NOT NULL DEFAULT 0,
          client_ip VARCHAR(64),
          client_device_id VARCHAR(128),
          sms_vendor VARCHAR(32),
          vendor_message_id VARCHAR(128),
          created_at TIMESTAMP NOT NULL,
          sent_at TIMESTAMP,
          verified_at TIMESTAMP
        )
        """,
        "UPDATE sys_user SET phone_country_code = '+86' WHERE phone_country_code IS NULL",
        "UPDATE sys_user SET status = 'ACTIVE' WHERE status IS NULL",
        "UPDATE sys_user SET login_fail_count = 0 WHERE login_fail_count IS NULL",
        "UPDATE sys_user SET phone_login_enabled = TRUE WHERE phone_login_enabled IS NULL",
        "CREATE INDEX IF NOT EXISTS ix_sys_user_phone ON sys_user (phone)",
        "CREATE INDEX IF NOT EXISTS ix_sys_user_status ON sys_user (status)",
        "CREATE UNIQUE INDEX IF NOT EXISTS uk_sys_user_phone_country_phone ON sys_user (phone_country_code, phone) WHERE phone IS NOT NULL",
        "CREATE INDEX IF NOT EXISTS ix_sms_code_log_phone ON sms_code_log (phone)",
        "CREATE INDEX IF NOT EXISTS ix_sms_code_log_scene ON sms_code_log (scene)",
        "CREATE INDEX IF NOT EXISTS ix_sms_code_log_verify_status ON sms_code_log (verify_status)",
    ]
    try:
        with engine.begin() as conn:
            existing_columns = {item["name"] for item in inspect(conn).get_columns("sys_user")}
            for ddl in ddl_list:
                ddl_normalized = " ".join(ddl.strip().split()).lower()
                if "add column phone_country_code" in ddl_normalized and "phone_country_code" in existing_columns:
                    continue
                if "add column phone " in ddl_normalized and "phone" in existing_columns:
                    continue
                if "add column status " in ddl_normalized and "status" in existing_columns:
                    continue
                if "add column phone_verified_at" in ddl_normalized and "phone_verified_at" in existing_columns:
                    continue
                if "add column activated_at" in ddl_normalized and "activated_at" in existing_columns:
                    continue
                if "add column last_login_at" in ddl_normalized and "last_login_at" in existing_columns:
                    continue
                if "add column locked_until" in ddl_normalized and "locked_until" in existing_columns:
                    continue
                if "add column login_fail_count" in ddl_normalized and "login_fail_count" in existing_columns:
                    continue
                if "add column phone_login_enabled" in ddl_normalized and "phone_login_enabled" in existing_columns:
                    continue
                conn.execute(text(ddl))
    except Exception:
        logger.exception("sms auth schema ensure failed")


def _ensure_timescaledb_defaults():
    if settings.database_url.startswith("sqlite"):
        return
    if not settings.timescaledb_auto_enable:
        return

    ddl_list = [
        "CREATE EXTENSION IF NOT EXISTS timescaledb;",
        """
        DO $$
        DECLARE
          pk_columns TEXT;
        BEGIN
          SELECT string_agg(a.attname, ',' ORDER BY ord.idx)
          INTO pk_columns
          FROM pg_constraint c
          JOIN LATERAL unnest(c.conkey) WITH ORDINALITY ord(attnum, idx) ON TRUE
          JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ord.attnum
          WHERE c.conrelid = 'telemetry_history'::regclass
            AND c.contype = 'p';

          IF pk_columns IS NULL THEN
            ALTER TABLE telemetry_history ADD CONSTRAINT telemetry_history_pkey PRIMARY KEY (id, collected_at);
          ELSIF pk_columns <> 'id,collected_at' THEN
            ALTER TABLE telemetry_history DROP CONSTRAINT telemetry_history_pkey;
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
        _ensure_notify_schema()
        _ensure_sms_auth_schema()
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
    await get_fsu_gateway().start()

    global system_rule_task
    if settings.system_rule_eval_enabled and not settings.system_rule_inline_enabled:
        system_rule_task = asyncio.create_task(system_rule_worker_loop())


@app.on_event("shutdown")
async def shutdown():
    await get_fsu_gateway().stop()
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
