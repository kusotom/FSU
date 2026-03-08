import csv
import io
from datetime import datetime, time, timedelta
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps_authz import permission_required
from app.db.session import get_db
from app.models.operation_log import OperationLog
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.operation_log import OperationLogResponse
from app.services.access_control import AccessContext

router = APIRouter(prefix="/operation-logs", tags=["operation-logs"])


def _parse_datetime(value: str | None, *, end_of_day: bool = False) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    normalized = raw.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        try:
            date_part = datetime.strptime(raw, "%Y-%m-%d").date()
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="时间参数格式错误") from exc
        return datetime.combine(date_part, time.max if end_of_day else time.min)

    if len(raw) == 10 and raw[4] == "-" and raw[7] == "-":
        return datetime.combine(dt.date(), time.max if end_of_day else time.min, tzinfo=dt.tzinfo)
    if end_of_day and "T" not in raw and " " not in raw:
        return dt + timedelta(days=1) - timedelta(microseconds=1)
    return dt


def _assert_tenant_allowed(access: AccessContext, tenant_id: int):
    if access.can_global_read:
        return
    if tenant_id not in access.tenant_ids:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="只能查看本公司操作记录")


def _resolve_tenant(db: Session, tenant_code: str) -> Tenant:
    tenant = db.scalar(select(Tenant).where(Tenant.code == tenant_code))
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="公司不存在")
    return tenant


def _build_filtered_stmt(
    *,
    tenant_id: int,
    action: str | None,
    operator_keyword: str | None,
    date_from: str | None,
    date_to: str | None,
):
    stmt = (
        select(OperationLog, User.username.label("operator_name"))
        .outerjoin(User, User.id == OperationLog.operator_id)
        .where(OperationLog.tenant_id == tenant_id)
    )
    if action:
        stmt = stmt.where(OperationLog.action == action.strip())
    if operator_keyword:
        keyword = f"%{operator_keyword.strip().lower()}%"
        stmt = stmt.where(func.lower(func.coalesce(User.username, "")).like(keyword))

    start_dt = _parse_datetime(date_from, end_of_day=False)
    end_dt = _parse_datetime(date_to, end_of_day=True)
    if start_dt:
        stmt = stmt.where(OperationLog.created_at >= start_dt)
    if end_dt:
        stmt = stmt.where(OperationLog.created_at <= end_dt)
    return stmt


def _to_response_items(rows, tenant_code: str) -> list[OperationLogResponse]:
    return [
        OperationLogResponse(
            id=log.id,
            operator_id=log.operator_id,
            operator_name=operator_name,
            tenant_code=tenant_code,
            action=log.action,
            target_type=log.target_type,
            target_id=log.target_id,
            content=log.content,
            created_at=log.created_at,
        )
        for log, operator_name in rows
    ]


@router.get("", response_model=list[OperationLogResponse])
def list_operation_logs(
    tenant_code: str,
    limit: int = 50,
    action: str | None = None,
    operator_keyword: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    db: Session = Depends(get_db),
    access: AccessContext = Depends(permission_required("audit.view")),
):
    tenant = _resolve_tenant(db, tenant_code)
    _assert_tenant_allowed(access, tenant.id)

    safe_limit = max(1, min(int(limit or 50), 500))
    stmt = _build_filtered_stmt(
        tenant_id=tenant.id,
        action=action,
        operator_keyword=operator_keyword,
        date_from=date_from,
        date_to=date_to,
    )
    rows = db.execute(stmt.order_by(OperationLog.id.desc()).limit(safe_limit)).all()
    return _to_response_items(rows, tenant.code)


@router.get("/export")
def export_operation_logs(
    tenant_code: str,
    action: str | None = None,
    operator_keyword: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    db: Session = Depends(get_db),
    access: AccessContext = Depends(permission_required("audit.view")),
):
    tenant = _resolve_tenant(db, tenant_code)
    _assert_tenant_allowed(access, tenant.id)

    stmt = _build_filtered_stmt(
        tenant_id=tenant.id,
        action=action,
        operator_keyword=operator_keyword,
        date_from=date_from,
        date_to=date_to,
    )
    rows = db.execute(stmt.order_by(OperationLog.id.desc()).limit(2000)).all()

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["时间", "操作人", "动作", "对象类型", "对象ID", "内容"])
    for log, operator_name in rows:
        writer.writerow(
            [
                log.created_at.isoformat(),
                operator_name or "",
                log.action,
                log.target_type,
                log.target_id or "",
                log.content,
            ]
        )

    filename = quote(f"{tenant.code}_operation_logs.csv")
    headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"}
    return Response(content=buffer.getvalue(), media_type="text/csv; charset=utf-8", headers=headers)
