from __future__ import annotations

from typing import Callable

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.b_interface_outbound_call import BInterfaceOutboundCall
from app.modules.b_interface.client import OutboundCallResult


SessionFactory = Callable[[], Session]
_session_factory: SessionFactory = SessionLocal


def set_session_factory(factory: SessionFactory) -> None:
    global _session_factory
    _session_factory = factory


def reset_session_factory() -> None:
    global _session_factory
    _session_factory = SessionLocal


def _to_dict(row: BInterfaceOutboundCall) -> dict:
    return {
        "call_id": row.call_id,
        "ok": row.ok,
        "action": row.action,
        "fsu_id": row.fsu_id,
        "fsu_code": row.fsu_code,
        "endpoint": row.endpoint,
        "dry_run": row.dry_run,
        "request_xml_sanitized": row.request_xml_sanitized,
        "soap_request_sanitized": row.soap_request_sanitized,
        "http_status": row.http_status,
        "response_text_sanitized": row.response_text_sanitized or "",
        "invoke_return_sanitized": row.invoke_return_sanitized or "",
        "business_name": row.business_name or "",
        "business_code": row.business_code or "",
        "error_type": row.error_type,
        "error_message": row.error_message or "",
        "elapsed_ms": row.elapsed_ms,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def record_outbound_call(result: OutboundCallResult) -> dict:
    session = _session_factory()
    try:
        row = BInterfaceOutboundCall(
            ok=result.ok,
            action=result.action,
            fsu_id=result.fsu_id or None,
            fsu_code=result.fsu_code or None,
            endpoint=result.endpoint or None,
            dry_run=result.dry_run,
            request_xml_sanitized=result.request_xml_sanitized,
            soap_request_sanitized=result.soap_request_sanitized,
            http_status=result.http_status,
            response_text_sanitized=result.response_text_sanitized or None,
            invoke_return_sanitized=result.invoke_return_sanitized or None,
            business_name=result.business_name or None,
            business_code=result.business_code or None,
            error_type=result.error_type,
            error_message=result.error_message or None,
            elapsed_ms=result.elapsed_ms,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return _to_dict(row)
    finally:
        session.close()


def list_outbound_calls(limit: int = 50, fsu_id: str | None = None, action: str | None = None, error_type: str | None = None) -> list[dict]:
    session = _session_factory()
    try:
        stmt = select(BInterfaceOutboundCall)
        if fsu_id:
            stmt = stmt.where(BInterfaceOutboundCall.fsu_id == fsu_id)
        if action:
            stmt = stmt.where(BInterfaceOutboundCall.action == action.lower())
        if error_type:
            stmt = stmt.where(BInterfaceOutboundCall.error_type == error_type)
        rows = session.scalars(stmt.order_by(desc(BInterfaceOutboundCall.created_at), desc(BInterfaceOutboundCall.id)).limit(limit)).all()
        return [_to_dict(row) for row in rows]
    finally:
        session.close()


def get_outbound_call(call_id: str) -> dict | None:
    session = _session_factory()
    try:
        row = session.scalar(select(BInterfaceOutboundCall).where(BInterfaceOutboundCall.call_id == call_id))
        return _to_dict(row) if row is not None else None
    finally:
        session.close()
