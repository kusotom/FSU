from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.api.deps import (
    get_access_context,
    require_strategy_manager,
    require_strategy_viewer,
    require_template_manager,
)
from app.db.session import get_db
from app.models.rule import AlarmRule, AlarmRuleTenantPolicy
from app.models.tenant import Tenant
from app.schemas.rule import (
    AlarmRuleCreate,
    AlarmRuleResponse,
    AlarmRuleTenantPolicyResponse,
    AlarmRuleTenantPolicyUpdate,
    AlarmRuleUpdate,
)
from app.services.access_control import AccessContext, DEFAULT_SUB_TENANT_CODE
from app.services.rule_resolver import (
    invalidate_effective_metric_rule_cache,
    list_tenant_policy_rules,
)

router = APIRouter(prefix="/alarm-rules", tags=["alarm-rules"])


def _resolve_strategy_tenant(
    db: Session,
    *,
    access: AccessContext,
    tenant_code: str | None,
    require_explicit_for_global: bool,
) -> Tenant:
    tenant: Tenant | None = None
    if tenant_code:
        tenant = db.scalar(select(Tenant).where(Tenant.code == tenant_code.strip()))
        if tenant is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="租户不存在")

    if access.can_global_read:
        if tenant is None:
            if require_explicit_for_global:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请指定 tenant_code")
            tenant = db.scalar(select(Tenant).where(Tenant.code == DEFAULT_SUB_TENANT_CODE))
            if tenant is None:
                tenant = db.scalar(select(Tenant).order_by(Tenant.id.asc()))
        if tenant is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="未找到可用租户")
        return tenant

    if not access.tenant_ids:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无可用租户范围")
    if tenant is None:
        if len(access.tenant_ids) != 1:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请指定 tenant_code")
        tenant = db.get(Tenant, next(iter(access.tenant_ids)))
    if tenant is None or tenant.id not in access.tenant_ids:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权操作该租户策略")
    return tenant


def _build_policy_response(
    *,
    tenant: Tenant,
    row,
) -> AlarmRuleTenantPolicyResponse:
    return AlarmRuleTenantPolicyResponse(
        template_rule_id=row.template_rule_id,
        rule_key=row.rule_key,
        rule_name=row.rule_name,
        category=row.category,
        metric_key=row.metric_key,
        alarm_code=row.alarm_code,
        comparison=row.comparison,
        tenant_code=tenant.code,
        tenant_name=tenant.name,
        template_is_enabled=row.template_is_enabled,
        template_threshold_value=row.template_threshold_value,
        template_duration_seconds=row.template_duration_seconds,
        template_alarm_level=row.template_alarm_level,
        is_enabled_override=row.is_enabled_override,
        threshold_value_override=row.threshold_value_override,
        duration_seconds_override=row.duration_seconds_override,
        alarm_level_override=row.alarm_level_override,
        effective_is_enabled=row.effective_is_enabled,
        effective_threshold_value=row.effective_threshold_value,
        effective_duration_seconds=row.effective_duration_seconds,
        effective_alarm_level=row.effective_alarm_level,
    )


@router.get("", response_model=list[AlarmRuleResponse])
def list_alarm_rules(db: Session = Depends(get_db), _=Depends(require_template_manager)):
    stmt = select(AlarmRule).order_by(AlarmRule.id.desc())
    return list(db.scalars(stmt).all())


@router.post("", response_model=AlarmRuleResponse)
def create_alarm_rule(
    payload: AlarmRuleCreate,
    db: Session = Depends(get_db),
    _=Depends(require_template_manager),
):
    exists = db.scalar(select(AlarmRule).where(AlarmRule.rule_key == payload.rule_key))
    if exists:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="\u89c4\u5219\u6807\u8bc6\u5df2\u5b58\u5728",
        )
    item = AlarmRule(**payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    invalidate_effective_metric_rule_cache()
    return item


@router.put("/{rule_id}", response_model=AlarmRuleResponse)
def update_alarm_rule(
    rule_id: int,
    payload: AlarmRuleUpdate,
    db: Session = Depends(get_db),
    _=Depends(require_template_manager),
):
    item = db.get(AlarmRule, rule_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="\u89c4\u5219\u4e0d\u5b58\u5728")

    data = payload.model_dump()
    for field, value in data.items():
        setattr(item, field, value)
    item.updated_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(item)
    invalidate_effective_metric_rule_cache()
    return item


@router.get("/tenant-policies", response_model=list[AlarmRuleTenantPolicyResponse])
def list_tenant_policies(
    tenant_code: str | None = Query(default=None),
    db: Session = Depends(get_db),
    _=Depends(require_strategy_viewer),
    access: AccessContext = Depends(get_access_context),
):
    tenant = _resolve_strategy_tenant(
        db,
        access=access,
        tenant_code=tenant_code,
        require_explicit_for_global=access.can_global_read,
    )
    rows = list_tenant_policy_rules(db, tenant_id=tenant.id)
    return [_build_policy_response(tenant=tenant, row=row) for row in rows]


@router.put("/tenant-policies/{rule_id}", response_model=AlarmRuleTenantPolicyResponse)
def update_tenant_policy(
    rule_id: int,
    payload: AlarmRuleTenantPolicyUpdate,
    db: Session = Depends(get_db),
    _=Depends(require_strategy_manager),
    access: AccessContext = Depends(get_access_context),
):
    rule = db.get(AlarmRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="模板规则不存在")

    tenant = _resolve_strategy_tenant(
        db,
        access=access,
        tenant_code=payload.tenant_code,
        require_explicit_for_global=access.can_global_read,
    )
    item = db.scalar(
        select(AlarmRuleTenantPolicy).where(
            and_(
                AlarmRuleTenantPolicy.template_rule_id == rule_id,
                AlarmRuleTenantPolicy.tenant_id == tenant.id,
            )
        )
    )
    if item is None:
        item = AlarmRuleTenantPolicy(
            template_rule_id=rule_id,
            tenant_id=tenant.id,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db.add(item)

    payload_fields = payload.model_fields_set
    if "is_enabled_override" in payload_fields:
        item.is_enabled_override = payload.is_enabled_override
    if "threshold_value_override" in payload_fields:
        item.threshold_value_override = payload.threshold_value_override
    if "duration_seconds_override" in payload_fields:
        item.duration_seconds_override = payload.duration_seconds_override
    if "alarm_level_override" in payload_fields:
        item.alarm_level_override = payload.alarm_level_override
    item.updated_at = datetime.now(timezone.utc)

    db.commit()
    invalidate_effective_metric_rule_cache()

    rows = list_tenant_policy_rules(db, tenant_id=tenant.id)
    hit = next((row for row in rows if row.template_rule_id == rule_id), None)
    if hit is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="策略读取失败")
    return _build_policy_response(tenant=tenant, row=hit)
