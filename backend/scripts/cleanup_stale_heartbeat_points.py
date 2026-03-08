from __future__ import annotations

import argparse

from sqlalchemy import delete, select

from app.db.session import SessionLocal
from app.models.alarm import AlarmConditionState, AlarmEvent
from app.models.device import FSUDevice, MonitorPoint
from app.models.site import Site
from app.models.telemetry import TelemetryHistory, TelemetryLatest


TARGET_POINT_KEY = "system:fsu_heartbeat_timeout"


def collect_candidates():
    with SessionLocal() as db:
        rows = (
            db.execute(
                select(
                    MonitorPoint.id,
                    MonitorPoint.device_id,
                    FSUDevice.code.label("device_code"),
                    Site.code.label("site_code"),
                    Site.name.label("site_name"),
                )
                .join(FSUDevice, FSUDevice.id == MonitorPoint.device_id)
                .join(Site, Site.id == FSUDevice.site_id)
                .where(MonitorPoint.point_key == TARGET_POINT_KEY)
                .order_by(MonitorPoint.id.asc())
            )
            .all()
        )

        results = []
        for row in rows:
            point_id = row.id
            has_latest = db.scalar(select(TelemetryLatest.id).where(TelemetryLatest.point_id == point_id).limit(1)) is not None
            has_history = db.scalar(select(TelemetryHistory.id).where(TelemetryHistory.point_id == point_id).limit(1)) is not None
            has_alarm_event = db.scalar(select(AlarmEvent.id).where(AlarmEvent.point_id == point_id).limit(1)) is not None
            alarm_state_count = db.query(AlarmConditionState).filter(AlarmConditionState.point_id == point_id).count()
            deletable = (not has_latest) and (not has_history) and (not has_alarm_event)
            results.append(
                {
                    "point_id": point_id,
                    "device_id": row.device_id,
                    "device_code": row.device_code,
                    "site_code": row.site_code,
                    "site_name": row.site_name,
                    "has_latest": has_latest,
                    "has_history": has_history,
                    "has_alarm_event": has_alarm_event,
                    "alarm_state_count": alarm_state_count,
                    "deletable": deletable,
                }
            )
        return results


def apply_cleanup(items: list[dict]) -> tuple[int, int]:
    target_ids = [item["point_id"] for item in items if item["deletable"]]
    if not target_ids:
        return 0, 0

    with SessionLocal() as db:
        deleted_states = db.execute(
            delete(AlarmConditionState).where(AlarmConditionState.point_id.in_(target_ids))
        ).rowcount or 0
        deleted_points = db.execute(delete(MonitorPoint).where(MonitorPoint.id.in_(target_ids))).rowcount or 0
        db.commit()
        return int(deleted_states), int(deleted_points)


def main():
    parser = argparse.ArgumentParser(description="清理未使用的 FSU 心跳超时监控点。")
    parser.add_argument("--apply", action="store_true", help="真正执行删除；默认仅预览。")
    args = parser.parse_args()

    items = collect_candidates()
    print(f"target_point_key={TARGET_POINT_KEY}")
    print(f"found={len(items)}")
    for item in items:
        print(
            "point_id={point_id} site={site_code} device={device_code} latest={has_latest} "
            "history={has_history} alarm_event={has_alarm_event} alarm_state_count={alarm_state_count} "
            "deletable={deletable}".format(**item)
        )

    deletable = [item for item in items if item["deletable"]]
    print(f"deletable_count={len(deletable)}")

    if not args.apply:
        print("preview_only=true")
        return

    deleted_states, deleted_points = apply_cleanup(items)
    print(f"deleted_alarm_states={deleted_states}")
    print(f"deleted_monitor_points={deleted_points}")


if __name__ == "__main__":
    main()
