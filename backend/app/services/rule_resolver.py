import time
from collections import defaultdict
from threading import Lock
from types import SimpleNamespace

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.models.rule import AlarmRule, AlarmRuleTenantPolicy

_effective_metric_rule_cache: dict[str, dict[str, object]] = {}
_effective_metric_rule_cache_lock = Lock()
_effective_metric_rule_cache_ttl_seconds = 10.0


def invalidate_effective_metric_rule_cache():
    with _effective_metric_rule_cache_lock:
        _effective_metric_rule_cache.clear()


def _cache_key_for_tenant(tenant_id: int | None) -> str:
    return f"tenant:{tenant_id or 0}"


def _resolve_effective_values(
    *,
    template_is_enabled: bool,
    template_threshold_value: float | None,
    template_duration_seconds: int,
    template_alarm_level: int,
    is_enabled_override: bool | None,
    threshold_value_override: float | None,
    duration_seconds_override: int | None,
    alarm_level_override: int | None,
) -> tuple[bool, float | None, int, int]:
    effective_is_enabled = bool(template_is_enabled) and (
        is_enabled_override if is_enabled_override is not None else True
    )
    effective_threshold_value = (
        threshold_value_override
        if threshold_value_override is not None
        else template_threshold_value
    )
    effective_duration_seconds = (
        int(duration_seconds_override)
        if duration_seconds_override is not None
        else int(template_duration_seconds)
    )
    effective_alarm_level = (
        int(alarm_level_override)
        if alarm_level_override is not None
        else int(template_alarm_level)
    )
    return (
        effective_is_enabled,
        effective_threshold_value,
        effective_duration_seconds,
        effective_alarm_level,
    )


def _load_metric_rules_for_tenant(
    db: Session,
    tenant_id: int | None,
) -> list[SimpleNamespace]:
    if tenant_id is None:
        rows = db.execute(
            select(
                AlarmRule.id.label("template_rule_id"),
                AlarmRule.metric_key,
                AlarmRule.rule_key,
                AlarmRule.rule_name,
                AlarmRule.alarm_code,
                AlarmRule.alarm_level.label("template_alarm_level"),
                AlarmRule.comparison,
                AlarmRule.threshold_value.label("template_threshold_value"),
                AlarmRule.duration_seconds.label("template_duration_seconds"),
                AlarmRule.is_enabled.label("template_is_enabled"),
            ).where(AlarmRule.metric_key.is_not(None))
        ).all()
        payloads = []
        for row in rows:
            (
                effective_is_enabled,
                effective_threshold_value,
                effective_duration_seconds,
                effective_alarm_level,
            ) = _resolve_effective_values(
                template_is_enabled=row.template_is_enabled,
                template_threshold_value=row.template_threshold_value,
                template_duration_seconds=row.template_duration_seconds,
                template_alarm_level=row.template_alarm_level,
                is_enabled_override=None,
                threshold_value_override=None,
                duration_seconds_override=None,
                alarm_level_override=None,
            )
            if not effective_is_enabled:
                continue
            payloads.append(
                SimpleNamespace(
                    id=row.template_rule_id,
                    metric_key=row.metric_key,
                    rule_key=row.rule_key,
                    rule_name=row.rule_name,
                    alarm_code=row.alarm_code,
                    alarm_level=effective_alarm_level,
                    comparison=row.comparison,
                    threshold_value=effective_threshold_value,
                    duration_seconds=effective_duration_seconds,
                )
            )
        return payloads

    rows = db.execute(
        select(
            AlarmRule.id.label("template_rule_id"),
            AlarmRule.metric_key,
            AlarmRule.rule_key,
            AlarmRule.rule_name,
            AlarmRule.alarm_code,
            AlarmRule.alarm_level.label("template_alarm_level"),
            AlarmRule.comparison,
            AlarmRule.threshold_value.label("template_threshold_value"),
            AlarmRule.duration_seconds.label("template_duration_seconds"),
            AlarmRule.is_enabled.label("template_is_enabled"),
            AlarmRuleTenantPolicy.is_enabled_override,
            AlarmRuleTenantPolicy.threshold_value_override,
            AlarmRuleTenantPolicy.duration_seconds_override,
            AlarmRuleTenantPolicy.alarm_level_override,
        )
        .outerjoin(
            AlarmRuleTenantPolicy,
            and_(
                AlarmRuleTenantPolicy.template_rule_id == AlarmRule.id,
                AlarmRuleTenantPolicy.tenant_id == tenant_id,
            ),
        )
        .where(AlarmRule.metric_key.is_not(None))
    ).all()
    payloads = []
    for row in rows:
        (
            effective_is_enabled,
            effective_threshold_value,
            effective_duration_seconds,
            effective_alarm_level,
        ) = _resolve_effective_values(
            template_is_enabled=row.template_is_enabled,
            template_threshold_value=row.template_threshold_value,
            template_duration_seconds=row.template_duration_seconds,
            template_alarm_level=row.template_alarm_level,
            is_enabled_override=row.is_enabled_override,
            threshold_value_override=row.threshold_value_override,
            duration_seconds_override=row.duration_seconds_override,
            alarm_level_override=row.alarm_level_override,
        )
        if not effective_is_enabled:
            continue
        payloads.append(
            SimpleNamespace(
                id=row.template_rule_id,
                metric_key=row.metric_key,
                rule_key=row.rule_key,
                rule_name=row.rule_name,
                alarm_code=row.alarm_code,
                alarm_level=effective_alarm_level,
                comparison=row.comparison,
                threshold_value=effective_threshold_value,
                duration_seconds=effective_duration_seconds,
            )
        )
    return payloads


def get_effective_metric_rules_by_key(
    db: Session,
    metric_keys: list[str],
    *,
    tenant_id: int | None,
) -> dict[str, list[SimpleNamespace]]:
    if not metric_keys:
        return {}

    now = time.time()
    cache_key = _cache_key_for_tenant(tenant_id)
    cached_rows: list[SimpleNamespace] | None = None
    with _effective_metric_rule_cache_lock:
        bucket = _effective_metric_rule_cache.get(cache_key)
        if bucket:
            loaded_at = float(bucket.get("loaded_at", 0.0) or 0.0)
            rows = bucket.get("rows", [])
            if rows and now - loaded_at <= _effective_metric_rule_cache_ttl_seconds:
                cached_rows = list(rows)

    if cached_rows is None:
        fresh_rows = _load_metric_rules_for_tenant(db, tenant_id=tenant_id)
        with _effective_metric_rule_cache_lock:
            _effective_metric_rule_cache[cache_key] = {"loaded_at": now, "rows": fresh_rows}
        cached_rows = fresh_rows

    wanted = set(metric_keys)
    grouped: dict[str, list[SimpleNamespace]] = defaultdict(list)
    for rule in cached_rows:
        key = rule.metric_key
        if key and key in wanted:
            grouped[key].append(rule)
    return grouped


def list_tenant_policy_rules(db: Session, *, tenant_id: int) -> list[SimpleNamespace]:
    rows = db.execute(
        select(
            AlarmRule.id.label("template_rule_id"),
            AlarmRule.rule_key,
            AlarmRule.rule_name,
            AlarmRule.category,
            AlarmRule.metric_key,
            AlarmRule.alarm_code,
            AlarmRule.comparison,
            AlarmRule.is_enabled.label("template_is_enabled"),
            AlarmRule.threshold_value.label("template_threshold_value"),
            AlarmRule.duration_seconds.label("template_duration_seconds"),
            AlarmRule.alarm_level.label("template_alarm_level"),
            AlarmRuleTenantPolicy.is_enabled_override,
            AlarmRuleTenantPolicy.threshold_value_override,
            AlarmRuleTenantPolicy.duration_seconds_override,
            AlarmRuleTenantPolicy.alarm_level_override,
        )
        .outerjoin(
            AlarmRuleTenantPolicy,
            and_(
                AlarmRuleTenantPolicy.template_rule_id == AlarmRule.id,
                AlarmRuleTenantPolicy.tenant_id == tenant_id,
            ),
        )
        .order_by(AlarmRule.id.desc())
    ).all()

    result: list[SimpleNamespace] = []
    for row in rows:
        (
            effective_is_enabled,
            effective_threshold_value,
            effective_duration_seconds,
            effective_alarm_level,
        ) = _resolve_effective_values(
            template_is_enabled=row.template_is_enabled,
            template_threshold_value=row.template_threshold_value,
            template_duration_seconds=row.template_duration_seconds,
            template_alarm_level=row.template_alarm_level,
            is_enabled_override=row.is_enabled_override,
            threshold_value_override=row.threshold_value_override,
            duration_seconds_override=row.duration_seconds_override,
            alarm_level_override=row.alarm_level_override,
        )
        result.append(
            SimpleNamespace(
                template_rule_id=row.template_rule_id,
                rule_key=row.rule_key,
                rule_name=row.rule_name,
                category=row.category,
                metric_key=row.metric_key,
                alarm_code=row.alarm_code,
                comparison=row.comparison,
                template_is_enabled=row.template_is_enabled,
                template_threshold_value=row.template_threshold_value,
                template_duration_seconds=row.template_duration_seconds,
                template_alarm_level=row.template_alarm_level,
                is_enabled_override=row.is_enabled_override,
                threshold_value_override=row.threshold_value_override,
                duration_seconds_override=row.duration_seconds_override,
                alarm_level_override=row.alarm_level_override,
                effective_is_enabled=effective_is_enabled,
                effective_threshold_value=effective_threshold_value,
                effective_duration_seconds=effective_duration_seconds,
                effective_alarm_level=effective_alarm_level,
            )
        )
    return result
