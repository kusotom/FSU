from __future__ import annotations

import argparse
from collections import Counter

from sqlalchemy import text

from app.db.session import SessionLocal


SQL = text(
    """
    with point_usage as (
      select
        mp.id,
        mp.point_key,
        coalesce(mp.point_name, '') as point_name,
        d.code as device_code,
        s.code as site_code,
        s.name as site_name,
        max(tl.collected_at) as latest_at,
        count(th.id) as history_count
      from monitor_point mp
      join fsu_device d on d.id = mp.device_id
      join site s on s.id = d.site_id
      left join telemetry_latest tl on tl.point_id = mp.id
      left join telemetry_history th on th.point_id = mp.id
      group by mp.id, mp.point_key, coalesce(mp.point_name, ''), d.code, s.code, s.name
    )
    select *
    from point_usage
    order by point_key asc, id asc
    """
)


KNOWN_CHINESE_KEYS = {
    "room_temp",
    "temp_room",
    "room_humidity",
    "hum_room",
    "mains_voltage",
    "mains_current",
    "mains_frequency",
    "mains_power_state",
    "rectifier_module_status",
    "rectifier_output_voltage",
    "rectifier_output_current",
    "rectifier_load_rate",
    "rectifier_fault_status",
    "battery_group_voltage",
    "battery_group_current",
    "battery_cell_voltage_min",
    "battery_cell_voltage_max",
    "battery_temp",
    "battery_fault_status",
    "battery_fuse_status",
    "dc_bus_voltage",
    "dc_branch_current",
    "dc_breaker_status",
    "dc_overcurrent",
    "spd_failure",
    "aircon_status",
    "aircon_fault",
    "ac_running_status",
    "ac_fault_status",
    "ac_high_pressure",
    "ac_low_pressure",
    "ac_comm_status",
    "fresh_air_running_status",
    "fresh_air_fault_status",
    "water_leak_status",
    "smoke_status",
    "access_status",
    "door_access_status",
    "camera_online_status",
    "gen_running_status",
    "gen_start_failed",
    "gen_fault_status",
    "gen_fault",
    "gen_fuel_level",
    "ups_bypass_status",
    "voltage_a",
    "system:fsu_heartbeat_timeout",
}


def has_chinese(value: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in value)


def main():
    parser = argparse.ArgumentParser(description="巡检未命名监控项，区分在用项和未使用项。")
    parser.add_argument("--show-all", action="store_true", help="输出所有未命名项明细。")
    args = parser.parse_args()

    with SessionLocal() as db:
        rows = db.execute(SQL).all()

    unknown_rows = []
    for row in rows:
        point_key = row.point_key
        point_name = row.point_name or ""
        if point_key in KNOWN_CHINESE_KEYS:
            continue
        if has_chinese(point_name):
            continue
        unknown_rows.append(
            {
                "id": row.id,
                "point_key": point_key,
                "point_name": point_name,
                "site_code": row.site_code,
                "site_name": row.site_name,
                "device_code": row.device_code,
                "used": bool(row.latest_at or row.history_count > 0),
                "history_count": int(row.history_count or 0),
                "latest_at": row.latest_at,
            }
        )

    used_rows = [item for item in unknown_rows if item["used"]]
    unused_rows = [item for item in unknown_rows if not item["used"]]

    print(f"unknown_count={len(unknown_rows)}")
    print(f"used_count={len(used_rows)}")
    print(f"unused_count={len(unused_rows)}")

    key_counter = Counter(item["point_key"] for item in unknown_rows)
    print("top_unknown_keys=")
    for key, count in key_counter.most_common(20):
        print(f"  {key}: {count}")

    if args.show_all:
        print("details=")
        for item in unknown_rows:
            print(
                f"{item['point_key']}\t{item['point_name']}\tused={int(item['used'])}\t"
                f"site={item['site_code']}\tdevice={item['device_code']}\thistory={item['history_count']}"
            )


if __name__ == "__main__":
    main()
