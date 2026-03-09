from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_current_user
from app.api.deps_authz import permission_required
from app.db.session import get_db
from app.models.notify_admin import OncallSchedule, OncallScheduleMember, NotifyReceiver
from app.models.user import User
from app.schemas.notify_admin import OncallScheduleCreate, OncallScheduleResponse
from app.services.notify_guard import (
    ensure_scope_allowed,
    ensure_tenant_allowed,
    get_tenant_by_code_or_404,
    validate_custom_scope_belongs_tenant,
    validate_device_group_belongs_tenant,
    validate_project_belongs_tenant,
    validate_site_belongs_tenant,
)
from app.services.operation_log import write_operation_log

router = APIRouter(prefix="/notify-oncall", tags=["notify-oncall"])


def _load_schedule(db: Session, schedule_id: int) -> OncallSchedule | None:
    return db.scalar(
        select(OncallSchedule)
        .where(OncallSchedule.id == schedule_id)
        .options(selectinload(OncallSchedule.members).selectinload(OncallScheduleMember.receiver))
    )


def _validate_scope_binding(db: Session, tenant_id: int, payload: OncallScheduleCreate) -> None:
    if payload.scope_type == "PROJECT" and payload.project_id:
        validate_project_belongs_tenant(db, tenant_id, payload.project_id)
    elif payload.scope_type == "SITE" and payload.site_id:
        validate_site_belongs_tenant(db, tenant_id, payload.site_id)
    elif payload.scope_type == "DEVICE_GROUP" and payload.device_group_id:
        validate_device_group_belongs_tenant(db, tenant_id, payload.device_group_id)
    elif payload.scope_type == "CUSTOM" and payload.custom_scope_set_id:
        validate_custom_scope_belongs_tenant(db, tenant_id, payload.custom_scope_set_id)


def _validate_member_ids(db: Session, tenant_id: int, member_ids: list[int]) -> None:
    if not member_ids:
        return
    rows = list(db.scalars(select(NotifyReceiver).where(NotifyReceiver.id.in_(member_ids))).all())
    row_map = {item.id: item for item in rows}
    missing = [item for item in member_ids if item not in row_map]
    if missing:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="存在无效接收人")
    invalid = [item.id for item in rows if item.tenant_id != tenant_id]
    if invalid:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="接收人不属于当前公司")


def _to_response(item: OncallSchedule, tenant_code: str) -> OncallScheduleResponse:
    member_ids = [row.receiver_id for row in item.members]
    member_names = [row.receiver.name for row in item.members if row.receiver]
    return OncallScheduleResponse(
        id=item.id,
        tenant_code=tenant_code,
        name=item.name,
        description=item.description,
        timezone_name=item.timezone_name,
        scope_type=item.scope_type,
        project_id=item.project_id,
        site_id=item.site_id,
        device_group_id=item.device_group_id,
        custom_scope_set_id=item.custom_scope_set_id,
        member_ids=member_ids,
        member_names=member_names,
        member_count=len(member_ids),
        is_enabled=item.is_enabled,
        created_at=item.created_at,
    )


@router.get("", response_model=list[OncallScheduleResponse])
def list_schedules(
    tenant_code: str,
    db: Session = Depends(get_db),
    access=Depends(permission_required("notify.oncall.view")),
):
    tenant = get_tenant_by_code_or_404(db, tenant_code)
    ensure_tenant_allowed(access, tenant.id)
    rows = list(
        db.scalars(
            select(OncallSchedule)
            .where(OncallSchedule.tenant_id == tenant.id)
            .options(selectinload(OncallSchedule.members).selectinload(OncallScheduleMember.receiver))
            .order_by(OncallSchedule.id.desc())
        ).all()
    )
    return [_to_response(item, tenant.code) for item in rows]


@router.post("", response_model=OncallScheduleResponse)
def create_schedule(
    tenant_code: str,
    payload: OncallScheduleCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    access=Depends(permission_required("notify.oncall.manage")),
):
    tenant = get_tenant_by_code_or_404(db, tenant_code)
    ensure_scope_allowed(
        db,
        access,
        tenant_id=tenant.id,
        project_id=payload.project_id,
        site_id=payload.site_id,
        device_group_id=payload.device_group_id,
        custom_scope_set_id=payload.custom_scope_set_id,
    )
    _validate_scope_binding(db, tenant.id, payload)
    _validate_member_ids(db, tenant.id, payload.member_ids)

    exists = db.scalar(
        select(OncallSchedule.id).where(OncallSchedule.tenant_id == tenant.id, OncallSchedule.name == payload.name)
    )
    if exists is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="值班表名称已存在")

    item = OncallSchedule(
        tenant_id=tenant.id,
        scope_type=payload.scope_type,
        project_id=payload.project_id,
        site_id=payload.site_id,
        device_group_id=payload.device_group_id,
        custom_scope_set_id=payload.custom_scope_set_id,
        name=payload.name,
        description=(payload.description or "").strip() or None,
        timezone_name=(payload.timezone_name or "Asia/Shanghai").strip() or "Asia/Shanghai",
        is_enabled=payload.is_enabled,
        created_by=current_user.id,
    )
    db.add(item)
    db.flush()
    for index, receiver_id in enumerate(sorted(set(payload.member_ids)), start=1):
        db.add(
            OncallScheduleMember(
                tenant_id=tenant.id,
                schedule_id=item.id,
                receiver_id=receiver_id,
                duty_order=index,
                shift_label=f"值班顺位{index}",
            )
        )
    write_operation_log(
        db,
        operator_id=current_user.id,
        tenant_id=tenant.id,
        action="notify_oncall.create",
        target_type="oncall_schedule",
        target_id=str(item.id),
        content=f"创建值班表 {item.name}，成员数={len(set(payload.member_ids))}",
    )
    db.commit()
    item = _load_schedule(db, item.id)
    return _to_response(item, tenant.code)


@router.put("/{schedule_id}", response_model=OncallScheduleResponse)
def update_schedule(
    schedule_id: int,
    tenant_code: str,
    payload: OncallScheduleCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    access=Depends(permission_required("notify.oncall.manage")),
):
    tenant = get_tenant_by_code_or_404(db, tenant_code)
    item = _load_schedule(db, schedule_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="值班表不存在")
    ensure_tenant_allowed(access, tenant.id)
    if item.tenant_id != tenant.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="禁止跨租户修改值班表")
    ensure_scope_allowed(
        db,
        access,
        tenant_id=tenant.id,
        project_id=payload.project_id,
        site_id=payload.site_id,
        device_group_id=payload.device_group_id,
        custom_scope_set_id=payload.custom_scope_set_id,
    )
    _validate_scope_binding(db, tenant.id, payload)
    _validate_member_ids(db, tenant.id, payload.member_ids)

    exists = db.scalar(
        select(OncallSchedule.id).where(
            OncallSchedule.tenant_id == tenant.id,
            OncallSchedule.name == payload.name,
            OncallSchedule.id != item.id,
        )
    )
    if exists is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="值班表名称已存在")

    item.name = payload.name
    item.description = (payload.description or "").strip() or None
    item.timezone_name = (payload.timezone_name or "Asia/Shanghai").strip() or "Asia/Shanghai"
    item.scope_type = payload.scope_type
    item.project_id = payload.project_id
    item.site_id = payload.site_id
    item.device_group_id = payload.device_group_id
    item.custom_scope_set_id = payload.custom_scope_set_id
    item.is_enabled = payload.is_enabled
    for row in list(item.members):
        db.delete(row)
    db.flush()
    for index, receiver_id in enumerate(sorted(set(payload.member_ids)), start=1):
        db.add(
            OncallScheduleMember(
                tenant_id=tenant.id,
                schedule_id=item.id,
                receiver_id=receiver_id,
                duty_order=index,
                shift_label=f"值班顺位{index}",
            )
        )
    write_operation_log(
        db,
        operator_id=current_user.id,
        tenant_id=tenant.id,
        action="notify_oncall.update",
        target_type="oncall_schedule",
        target_id=str(item.id),
        content=f"更新值班表 {item.name}，成员数={len(set(payload.member_ids))}，状态={'启用' if item.is_enabled else '停用'}",
    )
    db.commit()
    item = _load_schedule(db, item.id)
    return _to_response(item, tenant.code)


@router.delete("/{schedule_id}")
def delete_schedule(
    schedule_id: int,
    tenant_code: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    access=Depends(permission_required("notify.oncall.manage")),
):
    tenant = get_tenant_by_code_or_404(db, tenant_code)
    item = db.get(OncallSchedule, schedule_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="值班表不存在")
    ensure_tenant_allowed(access, tenant.id)
    if item.tenant_id != tenant.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="禁止跨租户删除值班表")

    write_operation_log(
        db,
        operator_id=current_user.id,
        tenant_id=tenant.id,
        action="notify_oncall.delete",
        target_type="oncall_schedule",
        target_id=str(item.id),
        content=f"删除值班表 {item.name}",
    )
    db.delete(item)
    db.commit()
    return {"ok": True}
