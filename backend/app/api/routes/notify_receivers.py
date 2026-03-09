from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.deps_authz import permission_required
from app.db.session import get_db
from app.models.notify_admin import NotifyReceiver
from app.models.user import User
from app.schemas.notify_admin import NotifyReceiverCreate, NotifyReceiverResponse
from app.services.notify_guard import ensure_tenant_allowed, get_tenant_by_code_or_404
from app.services.operation_log import write_operation_log

router = APIRouter(prefix="/notify-receivers", tags=["notify-receivers"])


def _to_response(item: NotifyReceiver, tenant_code: str) -> NotifyReceiverResponse:
    return NotifyReceiverResponse(
        id=item.id,
        tenant_code=tenant_code,
        user_id=item.user_id,
        receiver_type=item.receiver_type,
        name=item.name,
        mobile=item.mobile,
        wechat_openid=item.wechat_openid,
        email=item.email,
        pushplus_token=item.pushplus_token,
        is_enabled=item.is_enabled,
        created_at=item.created_at,
    )


@router.get("", response_model=list[NotifyReceiverResponse])
def list_receivers(
    tenant_code: str,
    db: Session = Depends(get_db),
    access=Depends(permission_required("notify.receiver.view")),
):
    tenant = get_tenant_by_code_or_404(db, tenant_code)
    ensure_tenant_allowed(access, tenant.id)
    rows = list(
        db.scalars(
            select(NotifyReceiver)
            .where(NotifyReceiver.tenant_id == tenant.id)
            .order_by(NotifyReceiver.id.desc())
        ).all()
    )
    return [_to_response(item, tenant.code) for item in rows]


@router.post("", response_model=NotifyReceiverResponse)
def create_receiver(
    tenant_code: str,
    payload: NotifyReceiverCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    access=Depends(permission_required("notify.receiver.manage")),
):
    tenant = get_tenant_by_code_or_404(db, tenant_code)
    ensure_tenant_allowed(access, tenant.id)

    item = NotifyReceiver(
        tenant_id=tenant.id,
        user_id=payload.user_id,
        receiver_type=payload.receiver_type,
        name=payload.name,
        mobile=(payload.mobile or "").strip() or None,
        wechat_openid=(payload.wechat_openid or "").strip() or None,
        email=(payload.email or "").strip() or None,
        pushplus_token=(payload.pushplus_token or "").strip() or None,
        is_enabled=payload.is_enabled,
        created_by=current_user.id,
    )
    db.add(item)
    db.flush()
    write_operation_log(
        db,
        operator_id=current_user.id,
        tenant_id=tenant.id,
        action="notify_receiver.create",
        target_type="notify_receiver",
        target_id=str(item.id),
        content=f"创建接收人 {item.name}，类型={item.receiver_type}",
    )
    db.commit()
    db.refresh(item)
    return _to_response(item, tenant.code)


@router.put("/{receiver_id}", response_model=NotifyReceiverResponse)
def update_receiver(
    receiver_id: int,
    tenant_code: str,
    payload: NotifyReceiverCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    access=Depends(permission_required("notify.receiver.manage")),
):
    tenant = get_tenant_by_code_or_404(db, tenant_code)
    item = db.get(NotifyReceiver, receiver_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="接收人不存在")
    ensure_tenant_allowed(access, tenant.id)
    if item.tenant_id != tenant.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="禁止跨租户修改接收人")

    item.user_id = payload.user_id
    item.receiver_type = payload.receiver_type
    item.name = payload.name
    item.mobile = (payload.mobile or "").strip() or None
    item.wechat_openid = (payload.wechat_openid or "").strip() or None
    item.email = (payload.email or "").strip() or None
    item.pushplus_token = (payload.pushplus_token or "").strip() or None
    item.is_enabled = payload.is_enabled
    write_operation_log(
        db,
        operator_id=current_user.id,
        tenant_id=tenant.id,
        action="notify_receiver.update",
        target_type="notify_receiver",
        target_id=str(item.id),
        content=f"更新接收人 {item.name}，类型={item.receiver_type}，状态={'启用' if item.is_enabled else '停用'}",
    )
    db.commit()
    db.refresh(item)
    return _to_response(item, tenant.code)


@router.delete("/{receiver_id}")
def delete_receiver(
    receiver_id: int,
    tenant_code: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    access=Depends(permission_required("notify.receiver.manage")),
):
    tenant = get_tenant_by_code_or_404(db, tenant_code)
    item = db.get(NotifyReceiver, receiver_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="接收人不存在")
    ensure_tenant_allowed(access, tenant.id)
    if item.tenant_id != tenant.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="禁止跨租户删除接收人")

    write_operation_log(
        db,
        operator_id=current_user.id,
        tenant_id=tenant.id,
        action="notify_receiver.delete",
        target_type="notify_receiver",
        target_id=str(item.id),
        content=f"删除接收人 {item.name}",
    )
    db.delete(item)
    db.commit()
    return {"ok": True}
