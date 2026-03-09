from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_current_user
from app.api.deps_authz import permission_required
from app.db.session import get_db
from app.models.notify_admin import NotifyGroup, NotifyGroupMember, NotifyReceiver, NotifyRule
from app.models.user import User
from app.schemas.notify_admin import NotifyGroupCreate, NotifyGroupResponse
from app.services.notify_guard import ensure_tenant_allowed, get_tenant_by_code_or_404
from app.services.operation_log import write_operation_log

router = APIRouter(prefix="/notify-groups", tags=["notify-groups"])


def _load_group(db: Session, group_id: int) -> NotifyGroup | None:
    return db.scalar(
        select(NotifyGroup)
        .where(NotifyGroup.id == group_id)
        .options(selectinload(NotifyGroup.members).selectinload(NotifyGroupMember.receiver))
    )


def _to_response(item: NotifyGroup, tenant_code: str) -> NotifyGroupResponse:
    member_ids = [row.receiver_id for row in item.members]
    member_names = [row.receiver.name for row in item.members if row.receiver]
    return NotifyGroupResponse(
        id=item.id,
        tenant_code=tenant_code,
        name=item.name,
        description=item.description,
        member_ids=member_ids,
        member_names=member_names,
        member_count=len(member_ids),
        is_enabled=item.is_enabled,
        created_at=item.created_at,
    )


def _validate_member_ids(db: Session, tenant_id: int, member_ids: list[int]) -> None:
    if not member_ids:
        return
    receivers = list(db.scalars(select(NotifyReceiver).where(NotifyReceiver.id.in_(member_ids))).all())
    receiver_map = {item.id: item for item in receivers}
    missing = [item for item in member_ids if item not in receiver_map]
    if missing:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="存在无效接收人")
    invalid = [item.id for item in receivers if item.tenant_id != tenant_id]
    if invalid:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="接收人不属于当前公司")


@router.get("", response_model=list[NotifyGroupResponse])
def list_groups(
    tenant_code: str,
    db: Session = Depends(get_db),
    access=Depends(permission_required("notify.group.view")),
):
    tenant = get_tenant_by_code_or_404(db, tenant_code)
    ensure_tenant_allowed(access, tenant.id)
    rows = list(
        db.scalars(
            select(NotifyGroup)
            .where(NotifyGroup.tenant_id == tenant.id)
            .options(selectinload(NotifyGroup.members).selectinload(NotifyGroupMember.receiver))
            .order_by(NotifyGroup.id.desc())
        ).all()
    )
    return [_to_response(item, tenant.code) for item in rows]


@router.post("", response_model=NotifyGroupResponse)
def create_group(
    tenant_code: str,
    payload: NotifyGroupCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    access=Depends(permission_required("notify.group.manage")),
):
    tenant = get_tenant_by_code_or_404(db, tenant_code)
    ensure_tenant_allowed(access, tenant.id)
    _validate_member_ids(db, tenant.id, payload.member_ids)

    exists = db.scalar(
        select(NotifyGroup.id).where(
            NotifyGroup.tenant_id == tenant.id,
            NotifyGroup.name == payload.name,
        )
    )
    if exists is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="通知组名称已存在")

    item = NotifyGroup(
        tenant_id=tenant.id,
        name=payload.name,
        description=(payload.description or "").strip() or None,
        is_enabled=payload.is_enabled,
        created_by=current_user.id,
    )
    db.add(item)
    db.flush()
    for receiver_id in sorted(set(payload.member_ids)):
        db.add(
            NotifyGroupMember(
                tenant_id=tenant.id,
                notify_group_id=item.id,
                receiver_id=receiver_id,
            )
        )
    write_operation_log(
        db,
        operator_id=current_user.id,
        tenant_id=tenant.id,
        action="notify_group.create",
        target_type="notify_group",
        target_id=str(item.id),
        content=f"创建通知组 {item.name}，成员数={len(set(payload.member_ids))}",
    )
    db.commit()
    item = _load_group(db, item.id)
    return _to_response(item, tenant.code)


@router.put("/{group_id}", response_model=NotifyGroupResponse)
def update_group(
    group_id: int,
    tenant_code: str,
    payload: NotifyGroupCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    access=Depends(permission_required("notify.group.manage")),
):
    tenant = get_tenant_by_code_or_404(db, tenant_code)
    item = _load_group(db, group_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="通知组不存在")
    ensure_tenant_allowed(access, tenant.id)
    if item.tenant_id != tenant.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="禁止跨租户修改通知组")
    _validate_member_ids(db, tenant.id, payload.member_ids)

    exists = db.scalar(
        select(NotifyGroup.id).where(
            NotifyGroup.tenant_id == tenant.id,
            NotifyGroup.name == payload.name,
            NotifyGroup.id != item.id,
        )
    )
    if exists is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="通知组名称已存在")

    item.name = payload.name
    item.description = (payload.description or "").strip() or None
    item.is_enabled = payload.is_enabled
    for row in list(item.members):
        db.delete(row)
    db.flush()
    for receiver_id in sorted(set(payload.member_ids)):
        db.add(
            NotifyGroupMember(
                tenant_id=tenant.id,
                notify_group_id=item.id,
                receiver_id=receiver_id,
            )
        )
    write_operation_log(
        db,
        operator_id=current_user.id,
        tenant_id=tenant.id,
        action="notify_group.update",
        target_type="notify_group",
        target_id=str(item.id),
        content=f"更新通知组 {item.name}，成员数={len(set(payload.member_ids))}，状态={'启用' if item.is_enabled else '停用'}",
    )
    db.commit()
    item = _load_group(db, item.id)
    return _to_response(item, tenant.code)


@router.delete("/{group_id}")
def delete_group(
    group_id: int,
    tenant_code: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    access=Depends(permission_required("notify.group.manage")),
):
    tenant = get_tenant_by_code_or_404(db, tenant_code)
    item = db.get(NotifyGroup, group_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="通知组不存在")
    ensure_tenant_allowed(access, tenant.id)
    if item.tenant_id != tenant.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="禁止跨租户删除通知组")

    in_use = db.scalar(select(NotifyRule.id).where(NotifyRule.notify_group_id == item.id).limit(1))
    if in_use is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="通知组已被推送规则引用，不能删除")

    write_operation_log(
        db,
        operator_id=current_user.id,
        tenant_id=tenant.id,
        action="notify_group.delete",
        target_type="notify_group",
        target_id=str(item.id),
        content=f"删除通知组 {item.name}",
    )
    db.delete(item)
    db.commit()
    return {"ok": True}
