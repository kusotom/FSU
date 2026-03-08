from datetime import datetime, timedelta, timezone
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, case, false, func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import get_access_context, get_current_user
from app.api.deps_authz import permission_required
from app.db.session import get_db
from app.models.device import FSUDevice, MonitorPoint
from app.models.rule import AlarmRule
from app.models.site import Site
from app.models.tenant import TenantSiteBinding
from app.models.telemetry import TelemetryHistory, TelemetryLatest
from app.schemas.telemetry import (
    ImportantPointKeysUpdate,
    TelemetryHistoryItem,
    TelemetryLatestItem,
    TelemetrySiteOverviewItem,
)
from app.services.alarm_engine import DEFAULT_THRESHOLDS, evaluate_metric
from app.services.access_control import AccessContext, get_accessible_site_ids
from app.services.realtime_preferences import get_important_point_keys, update_important_point_keys
from app.services.rule_resolver import get_effective_metric_rules_by_key

router = APIRouter(prefix="/telemetry", tags=["telemetry"])


@router.get("/important-point-keys", response_model=list[str])
def list_important_point_keys(
    db: Session = Depends(get_db),
    _=Depends(permission_required("realtime.view")),
):
    return get_important_point_keys(db)


@router.put("/important-point-keys", response_model=list[str])
def save_important_point_keys(
    payload: ImportantPointKeysUpdate,
    db: Session = Depends(get_db),
    _=Depends(permission_required("realtime.important.manage")),
):
    try:
        return update_important_point_keys(db, payload.point_keys)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


def _get_scoped_site_ids_or_all(db: Session, access: AccessContext) -> set[int] | None:
    return get_accessible_site_ids(db, access)


def _ensure_site_visible(db: Session, access: AccessContext, site_code: str) -> int:
    site_id = db.scalar(select(Site.id).where(Site.code == site_code))
    if site_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="\u7ad9\u70b9\u4e0d\u5b58\u5728")
    scoped_ids = _get_scoped_site_ids_or_all(db, access)
    if scoped_ids is not None and site_id not in scoped_ids:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="\u65e0\u6743\u8bbf\u95ee\u8be5\u7ad9\u70b9")
    return site_id


@router.get("/latest", response_model=list[TelemetryLatestItem])
def latest(
    site_code: str | None = None,
    db: Session = Depends(get_db),
    access: AccessContext = Depends(permission_required("realtime.view")),
):
    scoped_ids = _get_scoped_site_ids_or_all(db, access)
    if scoped_ids is not None and not scoped_ids:
        return []

    stmt = (
        select(TelemetryLatest, MonitorPoint, FSUDevice, Site)
        .join(MonitorPoint, TelemetryLatest.point_id == MonitorPoint.id)
        .join(FSUDevice, MonitorPoint.device_id == FSUDevice.id)
        .join(Site, FSUDevice.site_id == Site.id)
    )
    if scoped_ids is not None:
        stmt = stmt.where(Site.id.in_(scoped_ids))
    if site_code:
        stmt = stmt.where(Site.code == site_code).order_by(MonitorPoint.id.asc())
    else:
        stmt = stmt.order_by(Site.code.asc(), MonitorPoint.id.asc())

    rows = db.execute(stmt).all()
    return [
        TelemetryLatestItem(
            site_code=site.code,
            site_name=site.name,
            device_code=device.code,
            device_name=device.name,
            point_key=point.point_key,
            point_name=point.point_name,
            category=point.category,
            value=latest.value,
            unit=point.unit,
            collected_at=latest.collected_at,
        )
        for latest, point, device, site in rows
    ]


@router.get("/history", response_model=list[TelemetryHistoryItem])
def history(
    point_key: str,
    site_code: str,
    start: datetime = Query(...),
    end: datetime = Query(...),
    db: Session = Depends(get_db),
    access: AccessContext = Depends(permission_required("history.view")),
):
    _ensure_site_visible(db, access, site_code)

    point_id_stmt = (
        select(MonitorPoint.id, MonitorPoint.point_name, MonitorPoint.unit)
        .join(FSUDevice, MonitorPoint.device_id == FSUDevice.id)
        .join(Site, FSUDevice.site_id == Site.id)
        .where(and_(MonitorPoint.point_key == point_key, Site.code == site_code))
    )
    point_rows = db.execute(point_id_stmt).all()
    point_ids = [point_id for point_id, _point_name, _unit in point_rows]
    if not point_ids:
        return []
    point_name = next((name for _point_id, name, _unit in point_rows if name), point_key)
    point_unit = next((unit for _point_id, _name, unit in point_rows if unit), None)

    stmt = (
        select(TelemetryHistory.value, TelemetryHistory.collected_at)
        .where(
            and_(
                TelemetryHistory.point_id.in_(point_ids),
                TelemetryHistory.collected_at >= start,
                TelemetryHistory.collected_at <= end,
            )
        )
        .order_by(TelemetryHistory.collected_at.asc())
        .limit(5000)
    )
    rows = db.execute(stmt).all()
    return [
        TelemetryHistoryItem(
            point_key=point_key,
            point_name=point_name,
            unit=point_unit,
            value=value,
            collected_at=collected_at,
        )
        for value, collected_at in rows
    ]


@router.get("/history-batch", response_model=list[TelemetryHistoryItem])
def history_batch(
    point_keys: str,
    site_code: str,
    start: datetime = Query(...),
    end: datetime = Query(...),
    bucket_minutes: int = Query(1, ge=1, le=60),
    db: Session = Depends(get_db),
    access: AccessContext = Depends(permission_required("history.view")),
):
    keys = [item.strip() for item in point_keys.split(",") if item.strip()]
    if not keys:
        return []
    _ensure_site_visible(db, access, site_code)

    dialect = db.bind.dialect.name if db.bind is not None else ""
    if dialect == "sqlite":
        raw_stmt = (
            select(
                MonitorPoint.point_key,
                MonitorPoint.point_name,
                MonitorPoint.unit,
                TelemetryHistory.value,
                TelemetryHistory.collected_at,
            )
            .join(MonitorPoint, TelemetryHistory.point_id == MonitorPoint.id)
            .join(FSUDevice, MonitorPoint.device_id == FSUDevice.id)
            .join(Site, FSUDevice.site_id == Site.id)
            .where(
                and_(
                    Site.code == site_code,
                    MonitorPoint.point_key.in_(keys),
                    TelemetryHistory.collected_at >= start,
                    TelemetryHistory.collected_at <= end,
                )
            )
            .order_by(MonitorPoint.point_key.asc(), TelemetryHistory.collected_at.asc())
            .limit(50000)
        )
        rows = db.execute(raw_stmt).all()
        bucket_seconds = max(bucket_minutes, 1) * 60
        bucket_map: dict[tuple[str, int], dict[str, float | datetime]] = {}
        point_meta_map: dict[str, dict[str, str | None]] = {}
        for point_key, point_name, unit, value, collected_at in rows:
            if collected_at is None:
                continue
            if point_key not in point_meta_map:
                point_meta_map[point_key] = {
                    "point_name": point_name,
                    "unit": unit,
                }
            ts = int(collected_at.timestamp())
            bucket = (ts // bucket_seconds) * bucket_seconds
            map_key = (point_key, bucket)
            if map_key not in bucket_map:
                bucket_map[map_key] = {
                    "sum": float(value),
                    "count": 1.0,
                    "ts": datetime.fromtimestamp(bucket, tz=timezone.utc),
                }
            else:
                bucket_map[map_key]["sum"] = float(bucket_map[map_key]["sum"]) + float(value)
                bucket_map[map_key]["count"] = float(bucket_map[map_key]["count"]) + 1.0

        result: list[TelemetryHistoryItem] = []
        for (point_key, bucket), item in sorted(bucket_map.items(), key=lambda entry: (entry[0][0], entry[0][1])):
            meta = point_meta_map.get(point_key, {})
            result.append(
                TelemetryHistoryItem(
                    point_key=point_key,
                    point_name=meta.get("point_name"),
                    unit=meta.get("unit"),
                    value=float(item["sum"]) / max(float(item["count"]), 1.0),
                    collected_at=item["ts"],
                )
            )
        return result

    bucket_seconds = max(bucket_minutes, 1) * 60
    bucket_epoch = (
        func.floor(func.extract("epoch", TelemetryHistory.collected_at) / bucket_seconds) * bucket_seconds
    )
    bucket_ts = func.to_timestamp(bucket_epoch).label("bucket_ts")

    stmt = (
        select(
            MonitorPoint.point_key,
            MonitorPoint.point_name,
            MonitorPoint.unit,
            func.avg(TelemetryHistory.value).label("value"),
            bucket_ts,
        )
        .join(MonitorPoint, TelemetryHistory.point_id == MonitorPoint.id)
        .join(FSUDevice, MonitorPoint.device_id == FSUDevice.id)
        .join(Site, FSUDevice.site_id == Site.id)
        .where(
            and_(
                Site.code == site_code,
                MonitorPoint.point_key.in_(keys),
                TelemetryHistory.collected_at >= start,
                TelemetryHistory.collected_at <= end,
            )
        )
        .group_by(MonitorPoint.point_key, MonitorPoint.point_name, MonitorPoint.unit, bucket_ts)
        .order_by(MonitorPoint.point_key.asc(), bucket_ts.asc())
        .limit(50000)
    )
    rows = db.execute(stmt).all()
    return [
        TelemetryHistoryItem(
            point_key=point_key,
            point_name=point_name,
            unit=unit,
            value=float(value),
            collected_at=collected_at,
        )
        for point_key, point_name, unit, value, collected_at in rows
    ]


@router.get("/site-overview", response_model=list[TelemetrySiteOverviewItem])
def site_overview(
    db: Session = Depends(get_db),
    access: AccessContext = Depends(permission_required("dashboard.view")),
):
    scoped_ids = _get_scoped_site_ids_or_all(db, access)
    if scoped_ids is not None and not scoped_ids:
        return []

    mains_keys = {"mains_voltage"}
    dc_voltage_keys = {"rectifier_output_voltage", "battery_group_voltage"}
    dc_current_keys = {"rectifier_output_current", "dc_branch_current"}
    all_keys = mains_keys | dc_voltage_keys | dc_current_keys

    stmt = (
        select(
            Site.code,
            Site.name,
            MonitorPoint.point_key,
            TelemetryLatest.value,
            TelemetryLatest.collected_at,
        )
        .join(FSUDevice, FSUDevice.site_id == Site.id)
        .join(MonitorPoint, MonitorPoint.device_id == FSUDevice.id)
        .join(TelemetryLatest, TelemetryLatest.point_id == MonitorPoint.id)
        .where(MonitorPoint.point_key.in_(all_keys))
        .order_by(Site.code.asc(), TelemetryLatest.collected_at.desc())
    )
    if scoped_ids is not None:
        stmt = stmt.where(Site.id.in_(scoped_ids))
    rows = db.execute(stmt).all()

    template_metric_keys = set(
        db.scalars(select(AlarmRule.metric_key).where(AlarmRule.metric_key.is_not(None))).all()
    )
    evaluate_keys = set(DEFAULT_THRESHOLDS.keys()) | template_metric_keys
    latest_stmt = (
        select(
            Site.id,
            Site.code,
            MonitorPoint.point_key,
            MonitorPoint.point_name,
            MonitorPoint.high_threshold,
            MonitorPoint.low_threshold,
            TelemetryLatest.value,
            TelemetryLatest.collected_at,
        )
        .join(FSUDevice, FSUDevice.site_id == Site.id)
        .join(MonitorPoint, MonitorPoint.device_id == FSUDevice.id)
        .join(TelemetryLatest, TelemetryLatest.point_id == MonitorPoint.id)
        .where(
            or_(
                MonitorPoint.point_key.in_(evaluate_keys) if evaluate_keys else false(),
                MonitorPoint.high_threshold.is_not(None),
                MonitorPoint.low_threshold.is_not(None),
            )
        )
        .order_by(Site.code.asc(), MonitorPoint.point_key.asc(), TelemetryLatest.collected_at.desc())
    )
    if scoped_ids is not None:
        latest_stmt = latest_stmt.where(Site.id.in_(scoped_ids))
    latest_rows = db.execute(latest_stmt).all()
    site_ids_for_eval = sorted({site_id for site_id, *_ in latest_rows})
    site_tenant_rows = (
        db.execute(
            select(TenantSiteBinding.site_id, TenantSiteBinding.tenant_id).where(
                TenantSiteBinding.site_id.in_(site_ids_for_eval)
            )
        ).all()
        if site_ids_for_eval
        else []
    )
    site_tenant_map = {site_id: tenant_id for site_id, tenant_id in site_tenant_rows}
    tenant_rule_cache: dict[int | None, dict[str, list]] = {}

    current_alarm_count_map: dict[str, int] = defaultdict(int)
    seen_site_point: set[tuple[int, str]] = set()
    for (
        site_id,
        site_code,
        point_key,
        point_name,
        high_threshold,
        low_threshold,
        value,
        _collected_at,
    ) in latest_rows:
        dedupe_key = (site_id, point_key)
        if dedupe_key in seen_site_point:
            continue
        seen_site_point.add(dedupe_key)
        try:
            numeric_value = float(value)
        except (TypeError, ValueError):
            continue
        tenant_id = site_tenant_map.get(site_id)
        if tenant_id not in tenant_rule_cache:
            tenant_rule_cache[tenant_id] = get_effective_metric_rules_by_key(
                db,
                list(evaluate_keys),
                tenant_id=tenant_id,
            )
        rules_by_key = tenant_rule_cache[tenant_id]
        evaluation = evaluate_metric(
            point_key=point_key,
            point_name=point_name or point_key,
            value=numeric_value,
            high_threshold=high_threshold,
            low_threshold=low_threshold,
            rules=rules_by_key.get(point_key),
        )
        if evaluation.is_alarm:
            current_alarm_count_map[site_code] += 1

    device_stmt = (
        select(
            Site.code,
            Site.name,
            func.max(FSUDevice.last_seen_at).label("last_seen_at"),
            func.max(case((FSUDevice.status == "online", 1), else_=0)).label("has_online"),
        )
        .join(FSUDevice, FSUDevice.site_id == Site.id)
        .group_by(Site.code, Site.name)
    )
    if scoped_ids is not None:
        device_stmt = device_stmt.where(Site.id.in_(scoped_ids))
    device_rows = db.execute(device_stmt).all()

    offline_cutoff = datetime.now(timezone.utc) - timedelta(minutes=5)
    site_status_map: dict[str, str] = {}
    site_name_map: dict[str, str] = {}
    for site_code, site_name, last_seen_at, has_online in device_rows:
        site_name_map[site_code] = site_name
        if int(has_online or 0) <= 0:
            if last_seen_at is None or last_seen_at < offline_cutoff:
                site_status_map[site_code] = "offline"
                continue
        if current_alarm_count_map.get(site_code, 0) > 0:
            site_status_map[site_code] = "alarm"
        else:
            site_status_map[site_code] = "normal"

    grouped: dict[str, dict] = {}
    field_ts: dict[str, dict[str, datetime | None]] = {}
    for site_code, site_name, point_key, value, collected_at in rows:
        if site_code not in grouped:
            grouped[site_code] = {
                "site_code": site_code,
                "site_name": site_name,
                "site_status": site_status_map.get(site_code, "normal"),
                "active_alarm_count": int(current_alarm_count_map.get(site_code, 0)),
                "mains_voltage": None,
                "dc_voltage": None,
                "dc_current": None,
                "collected_at": None,
            }
            field_ts[site_code] = {
                "mains_voltage": None,
                "dc_voltage": None,
                "dc_current": None,
            }

        item = grouped[site_code]
        ts_map = field_ts[site_code]
        selected_field = None
        if point_key in mains_keys:
            selected_field = "mains_voltage"
        elif point_key in dc_voltage_keys:
            selected_field = "dc_voltage"
        elif point_key in dc_current_keys:
            selected_field = "dc_current"

        if selected_field:
            prev_ts = ts_map[selected_field]
            if prev_ts is None or collected_at >= prev_ts:
                item[selected_field] = value
                ts_map[selected_field] = collected_at

        if item["collected_at"] is None or collected_at >= item["collected_at"]:
            item["collected_at"] = collected_at

    for site_code, status in site_status_map.items():
        if site_code in grouped:
            grouped[site_code]["site_status"] = status
            grouped[site_code]["active_alarm_count"] = int(current_alarm_count_map.get(site_code, 0))
            continue
        grouped[site_code] = {
            "site_code": site_code,
            "site_name": site_name_map.get(site_code, site_code),
            "site_status": status,
            "active_alarm_count": int(current_alarm_count_map.get(site_code, 0)),
            "mains_voltage": None,
            "dc_voltage": None,
            "dc_current": None,
            "collected_at": None,
        }

    return [TelemetrySiteOverviewItem(**grouped[code]) for code in sorted(grouped.keys())]
