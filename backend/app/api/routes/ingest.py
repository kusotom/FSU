import asyncio
import logging
import time
from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import and_, insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.alarm import AlarmActionLog, AlarmConditionState, AlarmEvent
from app.models.device import FSUDevice, MonitorPoint
from app.models.rule import AlarmRule, AlarmRuleTenantPolicy
from app.models.site import Site
from app.models.tenant import TenantSiteBinding
from app.models.telemetry import TelemetryHistory, TelemetryLatest
from app.schemas.telemetry import TelemetryIngestRequest
from app.services.alarm_engine import (
    DEFAULT_THRESHOLDS,
    evaluate_metric,
    is_heartbeat_stale,
    rule_condition_met,
    sustained_for,
)
from app.services.metrics import (
    inc_ingest_queue_worker_failure,
    observe_ingest_request,
    set_ingest_queue_size,
    set_ingest_queue_workers,
)
from app.services.notifier import dispatch_alarm_notifications
from app.services.protocol_adapters import normalize_dtu_payload, normalize_estone_payload
from app.services.access_control import ensure_site_tenant_binding, get_default_sub_tenant
from app.services.rule_resolver import get_effective_metric_rules_by_key
from app.services.ws_manager import ws_manager

router = APIRouter(prefix="/ingest", tags=["ingest"])
logger = logging.getLogger(__name__)

_ingest_queue: asyncio.Queue[TelemetryIngestRequest] | None = None
_ingest_worker_tasks: list[asyncio.Task] = []


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _get_metric_rules_by_key(
    db: Session,
    metric_keys: list[str],
    *,
    tenant_id: int | None,
):
    return get_effective_metric_rules_by_key(db, metric_keys, tenant_id=tenant_id)


async def _dequeue_ingest_batch() -> list[TelemetryIngestRequest]:
    first = await _ingest_queue.get()  # type: ignore[union-attr]
    payloads = [first]
    batch_size = max(settings.ingest_queue_batch_size, 1)
    wait_seconds = max(settings.ingest_queue_batch_wait_ms, 0) / 1000.0
    deadline = asyncio.get_running_loop().time() + wait_seconds

    while len(payloads) < batch_size:
        timeout = deadline - asyncio.get_running_loop().time()
        if timeout <= 0:
            break
        try:
            item = await asyncio.wait_for(_ingest_queue.get(), timeout=timeout)  # type: ignore[union-attr]
        except TimeoutError:
            break
        payloads.append(item)
    return payloads


async def _ingest_queue_worker(worker_index: int):
    while True:
        payloads = await _dequeue_ingest_batch()
        try:
            side_effect_payloads = await run_in_threadpool(_ingest_telemetry_batch_sync, payloads)
            for side_effect_payload in side_effect_payloads:
                await _dispatch_ingest_side_effects(side_effect_payload)
        except asyncio.CancelledError:
            raise
        except Exception:
            inc_ingest_queue_worker_failure(worker_index, "batch")
            logger.exception("ingest queue worker %s failed", worker_index)
            # Fall back to per-item handling so one bad payload does not drop the whole batch.
            for payload in payloads:
                try:
                    _, side_effect_payload = await run_in_threadpool(_ingest_telemetry_sync, payload)
                    await _dispatch_ingest_side_effects(side_effect_payload)
                except Exception:
                    inc_ingest_queue_worker_failure(worker_index, "fallback")
                    logger.exception("ingest queue worker %s fallback failed", worker_index)
        finally:
            for _ in payloads:
                _ingest_queue.task_done()  # type: ignore[union-attr]
            set_ingest_queue_size(ingest_queue_size())


async def start_ingest_queue_workers():
    if settings.ingest_mode != "queue":
        set_ingest_queue_workers(0)
        set_ingest_queue_size(0)
        return
    global _ingest_queue
    if _ingest_queue is None:
        _ingest_queue = asyncio.Queue(maxsize=max(settings.ingest_queue_maxsize, 1000))
    if _ingest_worker_tasks:
        return
    worker_count = max(settings.ingest_queue_workers, 1)
    for idx in range(worker_count):
        _ingest_worker_tasks.append(asyncio.create_task(_ingest_queue_worker(idx)))
    set_ingest_queue_workers(worker_count)
    set_ingest_queue_size(ingest_queue_size())


async def stop_ingest_queue_workers():
    if not _ingest_worker_tasks:
        set_ingest_queue_workers(0)
        return
    for task in _ingest_worker_tasks:
        task.cancel()
    for task in _ingest_worker_tasks:
        try:
            await task
        except asyncio.CancelledError:
            pass
    _ingest_worker_tasks.clear()
    set_ingest_queue_workers(0)
    set_ingest_queue_size(ingest_queue_size())


def ingest_queue_size() -> int:
    if _ingest_queue is None:
        return 0
    return _ingest_queue.qsize()


@router.get("/queue-status")
def queue_status():
    set_ingest_queue_size(ingest_queue_size())
    return {
        "mode": settings.ingest_mode,
        "queue_size": ingest_queue_size(),
        "worker_count": len(_ingest_worker_tasks),
        "maxsize": settings.ingest_queue_maxsize,
        "batch_size": settings.ingest_queue_batch_size,
        "batch_wait_ms": settings.ingest_queue_batch_wait_ms,
    }


def _find_or_create_system_point(db: Session, device: FSUDevice, rule: AlarmRule) -> MonitorPoint:
    point_key = f"system:{rule.rule_key}"
    point = db.scalar(
        select(MonitorPoint).where(
            and_(MonitorPoint.device_id == device.id, MonitorPoint.point_key == point_key)
        )
    )
    if point is None:
        point = MonitorPoint(
            device_id=device.id,
            point_key=point_key,
            point_name=rule.rule_name,
            category="system",
            unit=None,
        )
        db.add(point)
        db.flush()
    return point


def _get_or_create_rule_state(
    db: Session,
    point_id: int,
    rule_id: int,
    state_cache: dict[tuple[int, int], AlarmConditionState] | None = None,
) -> AlarmConditionState:
    cache_key = (point_id, rule_id)
    if state_cache is not None:
        cached = state_cache.get(cache_key)
        if cached is not None:
            return cached

    state = db.scalar(
        select(AlarmConditionState).where(
            and_(AlarmConditionState.point_id == point_id, AlarmConditionState.rule_id == rule_id)
        )
    )
    if state is None:
        state = AlarmConditionState(
            point_id=point_id,
            rule_id=rule_id,
            abnormal_since=None,
            normal_since=None,
            updated_at=_utc_now(),
        )
        db.add(state)
        db.flush()
    if state_cache is not None:
        state_cache[cache_key] = state
    return state


def _create_alarm(
    db: Session,
    *,
    site: Site,
    device: FSUDevice,
    point: MonitorPoint,
    alarm_code: str,
    alarm_name: str,
    alarm_level: int,
    trigger_value: float,
    content: str,
    started_at: datetime,
) -> AlarmEvent:
    alarm = AlarmEvent(
        site_id=site.id,
        device_id=device.id,
        point_id=point.id,
        alarm_code=alarm_code,
        alarm_name=alarm_name,
        alarm_level=alarm_level,
        status="active",
        trigger_value=trigger_value,
        content=content,
        started_at=started_at,
        created_at=_utc_now(),
        updated_at=_utc_now(),
    )
    db.add(alarm)
    db.flush()
    db.add(
        AlarmActionLog(
            alarm_id=alarm.id,
            action="trigger",
            operator_id=None,
            content=content,
        )
    )
    return alarm


def _recover_alarm(db: Session, alarm: AlarmEvent, content: str, recovered_at: datetime):
    alarm.status = "recovered"
    alarm.recovered_at = recovered_at
    alarm.updated_at = _utc_now()
    db.add(
        AlarmActionLog(
            alarm_id=alarm.id,
            action="recover",
            operator_id=None,
            content=content,
        )
    )


def _active_rule_alarm(
    db: Session,
    *,
    point_id: int,
    alarm_code: str,
    active_alarm_cache: dict[tuple[int, str], AlarmEvent | None] | None = None,
) -> AlarmEvent | None:
    cache_key = (point_id, alarm_code)
    if active_alarm_cache is not None and cache_key in active_alarm_cache:
        return active_alarm_cache[cache_key]

    alarm = db.scalar(
        select(AlarmEvent).where(
            and_(
                AlarmEvent.point_id == point_id,
                AlarmEvent.alarm_code == alarm_code,
                AlarmEvent.status.in_(["active", "acknowledged"]),
            )
        )
    )
    if active_alarm_cache is not None:
        active_alarm_cache[cache_key] = alarm
    return alarm


def _handle_rule_condition(
    db: Session,
    *,
    site: Site,
    device: FSUDevice,
    point: MonitorPoint,
    rule: AlarmRule | SimpleNamespace,
    condition_met: bool,
    trigger_value: float,
    event_time: datetime,
    trigger_content: str,
    recover_content: str,
    alarm_pushes: list[dict],
    notify_events: list[tuple[str, int, int, int, int]],
    state_cache: dict[tuple[int, int], AlarmConditionState] | None = None,
    active_alarm_cache: dict[tuple[int, str], AlarmEvent | None] | None = None,
):
    state = _get_or_create_rule_state(db, point.id, rule.id, state_cache=state_cache)
    active_alarm = _active_rule_alarm(
        db,
        point_id=point.id,
        alarm_code=rule.alarm_code,
        active_alarm_cache=active_alarm_cache,
    )
    duration_seconds = max(rule.duration_seconds, 0)
    state.updated_at = _utc_now()

    if condition_met:
        state.normal_since = None
        if active_alarm is not None:
            active_alarm.updated_at = _utc_now()
            active_alarm.trigger_value = trigger_value
            if state.abnormal_since is None:
                state.abnormal_since = event_time
            return

        if state.abnormal_since is None:
            state.abnormal_since = event_time
        if sustained_for(state.abnormal_since, event_time, duration_seconds):
            alarm = _create_alarm(
                db,
                site=site,
                device=device,
                point=point,
                alarm_code=rule.alarm_code,
                alarm_name=rule.rule_name,
                alarm_level=rule.alarm_level,
                trigger_value=trigger_value,
                content=trigger_content,
                started_at=state.abnormal_since,
            )
            if active_alarm_cache is not None:
                active_alarm_cache[(point.id, rule.alarm_code)] = alarm
            alarm_pushes.append(
                {
                    "type": "alarm_triggered",
                    "alarm_id": alarm.id,
                    "site_code": site.code,
                    "device_code": device.code,
                    "point_key": point.point_key,
                    "value": alarm.trigger_value,
                    "content": alarm.content,
                }
            )
            notify_events.append(("trigger", alarm.id, site.id, device.id, point.id))
        return

    state.abnormal_since = None
    if active_alarm is None:
        state.normal_since = None
        return

    if state.normal_since is None:
        state.normal_since = event_time
    if sustained_for(state.normal_since, event_time, duration_seconds):
        _recover_alarm(db, active_alarm, content=recover_content, recovered_at=event_time)
        if active_alarm_cache is not None:
            active_alarm_cache[(point.id, rule.alarm_code)] = None
        state.normal_since = None
        alarm_pushes.append(
            {
                "type": "alarm_recovered",
                "alarm_id": active_alarm.id,
                "site_code": site.code,
                "device_code": device.code,
                "point_key": point.point_key,
            }
        )
        notify_events.append(("recover", active_alarm.id, site.id, device.id, point.id))


def _evaluate_system_rules(
    db: Session,
    *,
    now: datetime,
    alarm_pushes: list[dict],
    notify_events: list[tuple[str, int, int, int, int]],
):
    system_templates = list(
        db.scalars(
            select(AlarmRule).where(
                and_(
                    AlarmRule.category == "system",
                    AlarmRule.comparison == "stale_minutes",
                )
            )
        ).all()
    )
    if not system_templates:
        return

    devices = list(db.scalars(select(FSUDevice).order_by(FSUDevice.id.asc())).all())
    if not devices:
        return

    site_ids = sorted({item.site_id for item in devices})
    sites = list(db.scalars(select(Site).where(Site.id.in_(site_ids))).all()) if site_ids else []
    sites_by_id = {item.id: item for item in sites}
    site_tenant_rows = (
        db.execute(
            select(TenantSiteBinding.site_id, TenantSiteBinding.tenant_id).where(
                TenantSiteBinding.site_id.in_(site_ids)
            )
        ).all()
        if site_ids
        else []
    )
    site_tenant_map = {site_id: tenant_id for site_id, tenant_id in site_tenant_rows}

    template_ids = [item.id for item in system_templates]
    policy_rows = (
        list(
            db.scalars(
                select(AlarmRuleTenantPolicy).where(
                    AlarmRuleTenantPolicy.template_rule_id.in_(template_ids)
                )
            ).all()
        )
        if template_ids
        else []
    )
    policy_map = {(item.template_rule_id, item.tenant_id): item for item in policy_rows}

    device_ids = [item.id for item in devices]
    system_point_keys = [f"system:{item.rule_key}" for item in system_templates]
    existing_points = list(
        db.scalars(
            select(MonitorPoint).where(
                and_(
                    MonitorPoint.device_id.in_(device_ids),
                    MonitorPoint.point_key.in_(system_point_keys),
                )
            )
        ).all()
    )
    points_by_device_key = {(item.device_id, item.point_key): item for item in existing_points}

    rule_state_cache: dict[tuple[int, int], AlarmConditionState] = {}
    active_rule_alarm_cache: dict[tuple[int, str], AlarmEvent | None] = {}
    for template in system_templates:
        point_key = f"system:{template.rule_key}"
        for device in devices:
            site = sites_by_id.get(device.site_id)
            if site is None:
                continue

            tenant_id = site_tenant_map.get(site.id)
            policy = policy_map.get((template.id, tenant_id)) if tenant_id is not None else None
            effective_is_enabled = bool(template.is_enabled) and (
                policy.is_enabled_override if policy and policy.is_enabled_override is not None else True
            )
            if not effective_is_enabled:
                continue

            timeout_minutes = (
                policy.threshold_value_override
                if policy and policy.threshold_value_override is not None
                else template.threshold_value
            )
            timeout_minutes = float(timeout_minutes) if timeout_minutes is not None else 5.0
            effective_duration_seconds = (
                policy.duration_seconds_override
                if policy and policy.duration_seconds_override is not None
                else template.duration_seconds
            )
            effective_alarm_level = (
                policy.alarm_level_override
                if policy and policy.alarm_level_override is not None
                else template.alarm_level
            )

            point = points_by_device_key.get((device.id, point_key))
            if point is None:
                point = MonitorPoint(
                    device_id=device.id,
                    point_key=point_key,
                    point_name=template.rule_name,
                    category="system",
                    unit=None,
                )
                db.add(point)
                db.flush()
                points_by_device_key[(device.id, point_key)] = point
            last_seen = _as_utc(device.last_seen_at) if device.last_seen_at else _as_utc(device.created_at)
            stale_minutes = max((now - last_seen).total_seconds() / 60.0, 0.0)
            stale = is_heartbeat_stale(device.last_seen_at, timeout_minutes, now)
            device.status = "offline" if stale else "online"

            _handle_rule_condition(
                db,
                site=site,
                device=device,
                point=point,
                rule=SimpleNamespace(
                    id=template.id,
                    rule_key=template.rule_key,
                    rule_name=template.rule_name,
                    alarm_code=template.alarm_code,
                    alarm_level=effective_alarm_level,
                    comparison=template.comparison,
                    threshold_value=timeout_minutes,
                    duration_seconds=effective_duration_seconds,
                ),
                condition_met=stale,
                trigger_value=round(stale_minutes, 2),
                event_time=now,
                trigger_content=(
                    f"\u8bbe\u5907\u5fc3\u8df3\u8d85\u65f6\uff1a\u8bbe\u5907={device.code} "
                    f"\u6700\u540e\u5fc3\u8df3={last_seen.isoformat()} \u9608\u503c\u5206\u949f={timeout_minutes}"
                ),
                recover_content=f"\u8bbe\u5907\u5fc3\u8df3\u6062\u590d\uff1a\u8bbe\u5907={device.code}",
                alarm_pushes=alarm_pushes,
                notify_events=notify_events,
                state_cache=rule_state_cache,
                active_alarm_cache=active_rule_alarm_cache,
            )


async def _dispatch_alarm_side_effects(
    db: Session | None,
    *,
    alarm_pushes: list[dict],
    notify_events: list[tuple[str, int, int, int, int]],
):
    for item in alarm_pushes:
        await ws_manager.broadcast("realtime", item)

    if db is None:
        return

    for event_type, alarm_id, site_id, device_id, point_id in notify_events:
        alarm = db.get(AlarmEvent, alarm_id)
        event_site = db.get(Site, site_id)
        event_device = db.get(FSUDevice, device_id)
        point = db.get(MonitorPoint, point_id)
        if alarm is None or event_site is None or event_device is None or point is None:
            continue
        await dispatch_alarm_notifications(
            db=db,
            event_type=event_type,
            alarm=alarm,
            site=event_site,
            device=event_device,
            point=point,
        )


def _ingest_telemetry_sync(
    payload: TelemetryIngestRequest,
    db: Session | None = None,
    *,
    commit: bool = True,
) -> tuple[dict, dict]:
    collected_at = _as_utc(payload.collected_at)
    metrics = list({item.key: item for item in payload.metrics}.values())
    alarm_pushes: list[dict] = []
    notify_events: list[tuple[str, int, int, int, int]] = []
    own_session = db is None
    if db is None:
        db = SessionLocal()
    try:
        site: Site | None = None
        device: FSUDevice | None = None
        site = db.scalar(select(Site).where(Site.code == payload.site_code))
        if site is None:
            site = Site(code=payload.site_code, name=payload.site_name)
            db.add(site)
            db.flush()
            default_tenant = get_default_sub_tenant(db)
            ensure_site_tenant_binding(db, site_id=site.id, tenant_id=default_tenant.id)
        else:
            default_tenant = get_default_sub_tenant(db)
            ensure_site_tenant_binding(db, site_id=site.id, tenant_id=default_tenant.id)
        db.flush()
        site_tenant_id = db.scalar(
            select(TenantSiteBinding.tenant_id).where(TenantSiteBinding.site_id == site.id)
        )
        if site_tenant_id is None:
            default_tenant = get_default_sub_tenant(db)
            ensure_site_tenant_binding(db, site_id=site.id, tenant_id=default_tenant.id)
            db.flush()
            site_tenant_id = default_tenant.id

        device = db.scalar(select(FSUDevice).where(FSUDevice.code == payload.fsu_code))
        if device is None:
            device = FSUDevice(
                site_id=site.id,
                code=payload.fsu_code,
                name=payload.fsu_name,
                status="online",
                last_seen_at=collected_at,
            )
            db.add(device)
            db.flush()
        else:
            device.site_id = site.id
            device.status = "online"
            current_last_seen = _as_utc(device.last_seen_at) if device.last_seen_at else None
            if current_last_seen is None or collected_at >= current_last_seen:
                device.last_seen_at = collected_at

        metric_keys = sorted({item.key for item in metrics})
        rules_by_metric = _get_metric_rules_by_key(db, metric_keys, tenant_id=site_tenant_id)

        existing_points = list(
            db.scalars(
                select(MonitorPoint).where(
                    and_(MonitorPoint.device_id == device.id, MonitorPoint.point_key.in_(metric_keys))
                )
            ).all()
        )
        points_by_key = {item.point_key: item for item in existing_points}
        new_points: list[MonitorPoint] = []
        for metric in metrics:
            point = points_by_key.get(metric.key)
            if point is None:
                point = MonitorPoint(
                    device_id=device.id,
                    point_key=metric.key,
                    point_name=metric.name,
                    category=metric.category,
                    unit=metric.unit,
                )
                db.add(point)
                new_points.append(point)
                points_by_key[metric.key] = point
            else:
                point.point_name = metric.name
                point.category = metric.category
                point.unit = metric.unit
        if new_points:
            db.flush()

        point_ids = sorted({item.id for item in points_by_key.values() if item.id is not None})
        latest_by_point_id: dict[int, TelemetryLatest] = {}
        fresh_point_ids: set[int] = set()
        is_postgresql = bool(db.bind and db.bind.dialect.name == "postgresql")
        upsert_now = _utc_now()
        if point_ids:
            if is_postgresql:
                latest_rows = [
                    {
                        "point_id": points_by_key[item.key].id,
                        "value": item.value,
                        "collected_at": collected_at,
                        "updated_at": upsert_now,
                    }
                    for item in metrics
                ]
                stmt = (
                    pg_insert(TelemetryLatest)
                    .values(latest_rows)
                    .on_conflict_do_update(
                        index_elements=[TelemetryLatest.point_id],
                        set_={
                            "value": pg_insert(TelemetryLatest).excluded.value,
                            "collected_at": pg_insert(TelemetryLatest).excluded.collected_at,
                            "updated_at": pg_insert(TelemetryLatest).excluded.updated_at,
                        },
                        where=TelemetryLatest.collected_at <= pg_insert(TelemetryLatest).excluded.collected_at,
                    )
                    .returning(TelemetryLatest.point_id)
                )
                fresh_point_ids = {row.point_id for row in db.execute(stmt).all()}
            else:
                existing_latest = list(
                    db.scalars(select(TelemetryLatest).where(TelemetryLatest.point_id.in_(point_ids))).all()
                )
                latest_by_point_id = {item.point_id: item for item in existing_latest}

        history_rows: list[dict] = []
        rule_state_cache: dict[tuple[int, int], AlarmConditionState] = {}
        active_rule_alarm_cache: dict[tuple[int, str], AlarmEvent | None] = {}
        point_active_alarm_rows = (
            list(
                db.scalars(
                    select(AlarmEvent).where(
                        and_(
                            AlarmEvent.point_id.in_(point_ids),
                            AlarmEvent.status.in_(["active", "acknowledged"]),
                        )
                    )
                ).all()
            )
            if point_ids
            else []
        )
        active_alarm_by_point_id: dict[int, AlarmEvent] = {}
        for alarm in point_active_alarm_rows:
            active_alarm_by_point_id[alarm.point_id] = alarm
        created_at = _utc_now()
        for metric in metrics:
            point = points_by_key[metric.key]

            if is_postgresql:
                sample_is_fresh = point.id in fresh_point_ids
            else:
                latest = latest_by_point_id.get(point.id)
                sample_is_fresh = True
                if latest is None:
                    latest = TelemetryLatest(
                        point_id=point.id,
                        value=metric.value,
                        collected_at=collected_at,
                        updated_at=_utc_now(),
                    )
                    db.add(latest)
                    latest_by_point_id[point.id] = latest
                else:
                    latest_ts = _as_utc(latest.collected_at)
                    if collected_at >= latest_ts:
                        latest.value = metric.value
                        latest.collected_at = collected_at
                        latest.updated_at = _utc_now()
                    else:
                        sample_is_fresh = False

            history_rows.append(
                {
                    "point_id": point.id,
                    "value": metric.value,
                    "collected_at": collected_at,
                    "created_at": created_at,
                }
            )

            if not sample_is_fresh:
                # Late arrival packets should be retained in history, but must not roll back realtime state.
                continue

            metric_rule_set = rules_by_metric.get(point.point_key, [])
            if metric_rule_set:
                for rule in metric_rule_set:
                    if rule.comparison == "stale_minutes":
                        continue
                    hit = rule_condition_met(rule.comparison, rule.threshold_value, metric.value)
                    _handle_rule_condition(
                        db,
                        site=site,
                        device=device,
                        point=point,
                        rule=rule,
                        condition_met=hit,
                        trigger_value=metric.value,
                        event_time=collected_at,
                        trigger_content=(
                            f"{point.point_name}\u89e6\u53d1\u89c4\u5219={rule.rule_key} "
                            f"\u5f53\u524d\u503c={metric.value} \u6bd4\u8f83\u65b9\u5f0f={rule.comparison} "
                            f"\u9608\u503c={rule.threshold_value}"
                        ),
                        recover_content=(
                            f"{point.point_name}\u6062\u590d\u6b63\u5e38\uff1a\u89c4\u5219={rule.rule_key} "
                            f"\u5f53\u524d\u503c={metric.value}"
                        ),
                        alarm_pushes=alarm_pushes,
                        notify_events=notify_events,
                        state_cache=rule_state_cache,
                        active_alarm_cache=active_rule_alarm_cache,
                    )
                continue

            has_default_threshold = point.point_key in DEFAULT_THRESHOLDS
            has_custom_threshold = point.high_threshold is not None or point.low_threshold is not None
            if not has_default_threshold and not has_custom_threshold:
                continue

            evaluation = evaluate_metric(
                point_key=point.point_key,
                point_name=point.point_name,
                value=metric.value,
                high_threshold=point.high_threshold,
                low_threshold=point.low_threshold,
                rules=None,
            )
            active_alarm = active_alarm_by_point_id.get(point.id)
            if evaluation.is_alarm:
                if active_alarm is None:
                    alarm = _create_alarm(
                        db,
                        site=site,
                        device=device,
                        point=point,
                        alarm_code=evaluation.alarm_code or f"{point.point_key}_abnormal",
                        alarm_name=evaluation.alarm_name or f"{point.point_name}\u5f02\u5e38",
                        alarm_level=evaluation.level,
                        trigger_value=metric.value,
                        content=evaluation.content or f"{point.point_name}\u5f02\u5e38",
                        started_at=collected_at,
                    )
                    active_alarm_by_point_id[point.id] = alarm
                    alarm_pushes.append(
                        {
                            "type": "alarm_triggered",
                            "alarm_id": alarm.id,
                            "site_code": site.code,
                            "device_code": device.code,
                            "point_key": point.point_key,
                            "value": metric.value,
                            "content": alarm.content,
                        }
                    )
                    notify_events.append(("trigger", alarm.id, site.id, device.id, point.id))
                else:
                    active_alarm.updated_at = _utc_now()
                    active_alarm.trigger_value = metric.value
            elif active_alarm is not None:
                _recover_alarm(
                    db,
                    active_alarm,
                    content=f"{point.point_name}\u6062\u590d\u6b63\u5e38",
                    recovered_at=collected_at,
                )
                alarm_pushes.append(
                    {
                        "type": "alarm_recovered",
                        "alarm_id": active_alarm.id,
                        "site_code": site.code,
                        "device_code": device.code,
                        "point_key": point.point_key,
                    }
                )
                notify_events.append(("recover", active_alarm.id, site.id, device.id, point.id))
                active_alarm_by_point_id.pop(point.id, None)

        if history_rows:
            db.execute(insert(TelemetryHistory), history_rows)

        if settings.system_rule_inline_enabled:
            _evaluate_system_rules(
                db,
                now=_utc_now(),
                alarm_pushes=alarm_pushes,
                notify_events=notify_events,
            )
        if commit:
            db.commit()
    except Exception:
        if commit:
            db.rollback()
        raise
    finally:
        if own_session:
            db.close()

    metric_count = len(metrics)
    response = {"ok": True, "ingested": metric_count}
    side_effect_payload = {
        "site_code": payload.site_code,
        "device_code": payload.fsu_code,
        "collected_at": collected_at,
        "metric_count": metric_count,
        "alarm_pushes": alarm_pushes,
        "notify_events": notify_events,
    }
    return response, side_effect_payload


def _ingest_telemetry_batch_sync(payloads: list[TelemetryIngestRequest]) -> list[dict]:
    db = SessionLocal()
    side_effect_payloads: list[dict] = []
    try:
        for payload in payloads:
            _, side_effect_payload = _ingest_telemetry_sync(payload, db=db, commit=False)
            side_effect_payloads.append(side_effect_payload)
        db.commit()
        return side_effect_payloads
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


async def _dispatch_ingest_side_effects(payload: dict):
    await ws_manager.broadcast(
        "realtime",
        {
            "type": "telemetry_ingested",
            "site_code": payload["site_code"],
            "device_code": payload["device_code"],
            "collected_at": payload["collected_at"],
            "metric_count": payload["metric_count"],
        },
    )

    alarm_pushes: list[dict] = payload["alarm_pushes"]
    notify_events: list[tuple[str, int, int, int, int]] = payload["notify_events"]
    if not alarm_pushes and not notify_events:
        return

    if not notify_events:
        await _dispatch_alarm_side_effects(
            None,
            alarm_pushes=alarm_pushes,
            notify_events=notify_events,
        )
        return

    db = SessionLocal()
    try:
        await _dispatch_alarm_side_effects(
            db,
            alarm_pushes=alarm_pushes,
            notify_events=notify_events,
        )
    finally:
        db.close()


async def run_system_rule_sweep_once() -> dict:
    db = SessionLocal()
    alarm_pushes: list[dict] = []
    notify_events: list[tuple[str, int, int, int, int]] = []
    try:
        _evaluate_system_rules(
            db,
            now=_utc_now(),
            alarm_pushes=alarm_pushes,
            notify_events=notify_events,
        )
        db.commit()
        await _dispatch_alarm_side_effects(
            db,
            alarm_pushes=alarm_pushes,
            notify_events=notify_events,
        )
        return {"ok": True, "alarm_pushes": len(alarm_pushes), "notify_events": len(notify_events)}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@router.post("/telemetry")
async def ingest_telemetry(payload: TelemetryIngestRequest, background_tasks: BackgroundTasks):
    started_at = time.perf_counter()
    mode = settings.ingest_mode
    metric_count = len(payload.metrics)
    result_tag = "ok"
    try:
        if mode == "queue":
            if _ingest_queue is None:
                result_tag = "queue_unavailable"
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="\u91c7\u96c6\u961f\u5217\u672a\u521d\u59cb\u5316",
                )
            if settings.ingest_queue_wait_when_full:
                await _ingest_queue.put(payload)
            else:
                try:
                    _ingest_queue.put_nowait(payload)
                except asyncio.QueueFull as exc:
                    result_tag = "queue_full"
                    raise HTTPException(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        detail="\u91c7\u96c6\u961f\u5217\u5df2\u6ee1",
                    ) from exc
            queue_size = ingest_queue_size()
            set_ingest_queue_size(queue_size)
            return {
                "ok": True,
                "accepted": metric_count,
                "queued": True,
                "queue_size": queue_size,
            }

        result, side_effect_payload = await run_in_threadpool(_ingest_telemetry_sync, payload)
        background_tasks.add_task(_dispatch_ingest_side_effects, side_effect_payload)
        return result
    except HTTPException:
        if result_tag == "ok":
            result_tag = "http_error"
        raise
    except Exception:
        result_tag = "error"
        raise
    finally:
        observe_ingest_request(
            endpoint="telemetry",
            mode=mode,
            result=result_tag,
            duration_seconds=time.perf_counter() - started_at,
            metric_count=metric_count,
        )


@router.post("/estone")
async def ingest_estone(payload: dict, background_tasks: BackgroundTasks):
    started_at = time.perf_counter()
    mode = settings.ingest_mode
    metric_count = 0
    result_tag = "ok"
    try:
        normalized = normalize_estone_payload(payload)
    except ValueError as exc:
        result_tag = "bad_payload"
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"\u4e0a\u62a5\u6570\u636e\u683c\u5f0f\u9519\u8bef: {exc}",
        ) from exc

    metric_count = len(normalized.metrics)
    try:
        if mode == "queue":
            if _ingest_queue is None:
                result_tag = "queue_unavailable"
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="\u91c7\u96c6\u961f\u5217\u672a\u521d\u59cb\u5316",
                )
            if settings.ingest_queue_wait_when_full:
                await _ingest_queue.put(normalized)
            else:
                try:
                    _ingest_queue.put_nowait(normalized)
                except asyncio.QueueFull as exc:
                    result_tag = "queue_full"
                    raise HTTPException(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        detail="\u91c7\u96c6\u961f\u5217\u5df2\u6ee1",
                    ) from exc
            queue_size = ingest_queue_size()
            set_ingest_queue_size(queue_size)
            return {
                "ok": True,
                "accepted": metric_count,
                "queued": True,
                "queue_size": queue_size,
            }

        result, side_effect_payload = await run_in_threadpool(_ingest_telemetry_sync, normalized)
        background_tasks.add_task(_dispatch_ingest_side_effects, side_effect_payload)
        return result
    except HTTPException:
        if result_tag == "ok":
            result_tag = "http_error"
        raise
    except Exception:
        result_tag = "error"
        raise
    finally:
        observe_ingest_request(
            endpoint="estone",
            mode=mode,
            result=result_tag,
            duration_seconds=time.perf_counter() - started_at,
            metric_count=metric_count,
        )


@router.post("/dtu")
async def ingest_dtu(payload: dict, background_tasks: BackgroundTasks):
    started_at = time.perf_counter()
    mode = settings.ingest_mode
    metric_count = 0
    result_tag = "ok"
    try:
        normalized = normalize_dtu_payload(payload)
    except ValueError as exc:
        result_tag = "bad_payload"
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"DTU \u4e0a\u62a5\u6570\u636e\u683c\u5f0f\u9519\u8bef: {exc}",
        ) from exc

    metric_count = len(normalized.metrics)
    try:
        if mode == "queue":
            if _ingest_queue is None:
                result_tag = "queue_unavailable"
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="\u91c7\u96c6\u961f\u5217\u672a\u521d\u59cb\u5316",
                )
            if settings.ingest_queue_wait_when_full:
                await _ingest_queue.put(normalized)
            else:
                try:
                    _ingest_queue.put_nowait(normalized)
                except asyncio.QueueFull as exc:
                    result_tag = "queue_full"
                    raise HTTPException(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        detail="\u91c7\u96c6\u961f\u5217\u5df2\u6ee1",
                    ) from exc
            queue_size = ingest_queue_size()
            set_ingest_queue_size(queue_size)
            return {
                "ok": True,
                "accepted": metric_count,
                "queued": True,
                "queue_size": queue_size,
            }

        result, side_effect_payload = await run_in_threadpool(_ingest_telemetry_sync, normalized)
        background_tasks.add_task(_dispatch_ingest_side_effects, side_effect_payload)
        return result
    except HTTPException:
        if result_tag == "ok":
            result_tag = "http_error"
        raise
    except Exception:
        result_tag = "error"
        raise
    finally:
        observe_ingest_request(
            endpoint="dtu",
            mode=mode,
            result=result_tag,
            duration_seconds=time.perf_counter() - started_at,
            metric_count=metric_count,
        )
