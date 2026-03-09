from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.deps_authz import permission_required
from app.db.session import get_db
from app.models.notify_admin import NotifyGroup, NotifyRule
from app.models.user import User
from app.schemas.notify_admin import NotifyRuleCreate, NotifyRuleResponse
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

router = APIRouter(prefix="/notify-rules", tags=["notify-rules"])


def _validate_scope_binding(db: Session, tenant_id: int, payload: NotifyRuleCreate) -> None:
    if payload.scope_type == "PROJECT" and payload.project_id:
        validate_project_belongs_tenant(db, tenant_id, payload.project_id)
    elif payload.scope_type == "SITE" and payload.site_id:
        validate_site_belongs_tenant(db, tenant_id, payload.site_id)
    elif payload.scope_type == "DEVICE_GROUP" and payload.device_group_id:
        validate_device_group_belongs_tenant(db, tenant_id, payload.device_group_id)
    elif payload.scope_type == "CUSTOM" and payload.custom_scope_set_id:
        validate_custom_scope_belongs_tenant(db, tenant_id, payload.custom_scope_set_id)


def _to_response(item: NotifyRule, tenant_code: str) -> NotifyRuleResponse:
    return NotifyRuleResponse(
        id=item.id,
        tenant_code=tenant_code,
        name=item.name,
        alarm_level_min=item.alarm_level_min,
        event_types=[token for token in str(item.event_types or "").split(",") if token],
        channel_types=[token for token in str(item.channel_types or "").split(",") if token],
        notify_group_id=item.notify_group_id,
        scope_type=item.scope_type,
        project_id=item.project_id,
        site_id=item.site_id,
        device_group_id=item.device_group_id,
        custom_scope_set_id=item.custom_scope_set_id,
        content_template=item.content_template,
        is_enabled=item.is_enabled,
        created_at=item.created_at,
    )


@router.get("", response_model=list[NotifyRuleResponse])
def list_rules(
    tenant_code: str,
    db: Session = Depends(get_db),
    access=Depends(permission_required("notify.rule.view")),
):
    tenant = get_tenant_by_code_or_404(db, tenant_code)
    ensure_tenant_allowed(access, tenant.id)
    rows = list(
        db.scalars(
            select(NotifyRule)
            .where(NotifyRule.tenant_id == tenant.id)
            .order_by(NotifyRule.id.desc())
        ).all()
    )
    return [_to_response(item, tenant.code) for item in rows]


@router.post("", response_model=NotifyRuleResponse)
def create_rule(
    tenant_code: str,
    payload: NotifyRuleCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    access=Depends(permission_required("notify.rule.manage")),
):
    tenant = get_tenant_by_code_or_404(db, tenant_code)
    _validate_scope_binding(db, tenant.id, payload)
    ensure_scope_allowed(
        db,
        access,
        tenant_id=tenant.id,
        project_id=payload.project_id,
        site_id=payload.site_id,
        device_group_id=payload.device_group_id,
        custom_scope_set_id=payload.custom_scope_set_id,
    )

    if payload.notify_group_id:
        group = db.get(NotifyGroup, payload.notify_group_id)
        if group is None or group.tenant_id != tenant.id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="通知组不属于当前公司")

    item = NotifyRule(
        tenant_id=tenant.id,
        scope_type=payload.scope_type,
        project_id=payload.project_id,
        site_id=payload.site_id,
        device_group_id=payload.device_group_id,
        custom_scope_set_id=payload.custom_scope_set_id,
        name=payload.name,
        alarm_level_min=payload.alarm_level_min,
        event_types=",".join(payload.event_types),
        channel_types=",".join(payload.channel_types),
        notify_group_id=payload.notify_group_id,
        content_template=(payload.content_template or "").strip() or None,
        is_enabled=payload.is_enabled,
        created_by=current_user.id,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    write_operation_log(
        db,
        operator_id=current_user.id,
        tenant_id=tenant.id,
        action="notify_rule.create",
        target_type="notify_rule",
        target_id=str(item.id),
        content=f"创建推送规则 {item.name}，范围={item.scope_type}",
    )
    db.commit()
    return _to_response(item, tenant.code)


@router.put("/{rule_id}", response_model=NotifyRuleResponse)
def update_rule(
    rule_id: int,
    tenant_code: str,
    payload: NotifyRuleCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    access=Depends(permission_required("notify.rule.manage")),
):
    tenant = get_tenant_by_code_or_404(db, tenant_code)
    item = db.get(NotifyRule, rule_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="推送规则不存在")
    if item.tenant_id != tenant.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="禁止跨租户修改推送规则")

    _validate_scope_binding(db, tenant.id, payload)
    ensure_scope_allowed(
        db,
        access,
        tenant_id=tenant.id,
        project_id=payload.project_id,
        site_id=payload.site_id,
        device_group_id=payload.device_group_id,
        custom_scope_set_id=payload.custom_scope_set_id,
    )

    if payload.notify_group_id:
        group = db.get(NotifyGroup, payload.notify_group_id)
        if group is None or group.tenant_id != tenant.id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="通知组不属于当前公司")

    item.scope_type = payload.scope_type
    item.project_id = payload.project_id
    item.site_id = payload.site_id
    item.device_group_id = payload.device_group_id
    item.custom_scope_set_id = payload.custom_scope_set_id
    item.name = payload.name
    item.alarm_level_min = payload.alarm_level_min
    item.event_types = ",".join(payload.event_types)
    item.channel_types = ",".join(payload.channel_types)
    item.notify_group_id = payload.notify_group_id
    item.content_template = (payload.content_template or "").strip() or None
    item.is_enabled = payload.is_enabled
    item.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(item)
    write_operation_log(
        db,
        operator_id=current_user.id,
        tenant_id=tenant.id,
        action="notify_rule.update",
        target_type="notify_rule",
        target_id=str(item.id),
        content=f"更新推送规则 {item.name}，范围={item.scope_type}，状态={'启用' if item.is_enabled else '停用'}",
    )
    db.commit()
    return _to_response(item, tenant.code)


@router.delete("/{rule_id}")
def delete_rule(
    rule_id: int,
    tenant_code: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    access=Depends(permission_required("notify.rule.manage")),
):
    tenant = get_tenant_by_code_or_404(db, tenant_code)
    item = db.get(NotifyRule, rule_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="推送规则不存在")
    ensure_tenant_allowed(access, tenant.id)
    if item.tenant_id != tenant.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="禁止跨租户删除推送规则")

    write_operation_log(
        db,
        operator_id=current_user.id,
        tenant_id=tenant.id,
        action="notify_rule.delete",
        target_type="notify_rule",
        target_id=str(item.id),
        content=f"删除推送规则 {item.name}",
    )
    db.delete(item)
    db.commit()
    return {"ok": True}
