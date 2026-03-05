import argparse
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import requests


@dataclass(frozen=True)
class MetricDef:
    key: str
    name: str | None
    unit: str | None
    category: str
    normal: float
    alarm: float
    recover: float


METRICS: list[MetricDef] = [
    MetricDef("mains_voltage", "Mains Voltage", "V", "power", 220.0, 275.0, 220.0),
    MetricDef("mains_current", "Mains Current", "A", "power", 12.5, 18.0, 11.8),
    MetricDef("mains_frequency", "Mains Frequency", "Hz", "power", 50.0, 52.5, 49.9),
    MetricDef("mains_power_state", None, None, "power", 1.0, 0.0, 1.0),
    MetricDef("rectifier_module_status", None, None, "power", 1.0, 0.0, 1.0),
    MetricDef("rectifier_output_voltage", None, "V", "power", 53.5, 58.0, 53.2),
    MetricDef("rectifier_output_current", None, "A", "power", 35.0, 60.0, 34.8),
    MetricDef("rectifier_load_rate", None, "%", "power", 55.0, 92.0, 50.0),
    MetricDef("rectifier_fault_status", None, None, "power", 0.0, 1.0, 0.0),
    MetricDef("battery_group_voltage", None, "V", "power", 51.2, 57.0, 51.0),
    MetricDef("battery_cell_voltage_min", None, "V", "power", 2.10, 1.75, 2.08),
    MetricDef("battery_cell_voltage_max", None, "V", "power", 2.20, 2.45, 2.18),
    MetricDef("battery_temp", "Battery Temperature", "C", "power", 26.0, 58.0, 27.0),
    MetricDef("battery_fault_status", None, None, "power", 0.0, 1.0, 0.0),
    MetricDef("battery_fuse_status", None, None, "power", 0.0, 1.0, 0.0),
    MetricDef("gen_running_status", None, None, "power", 0.0, 1.0, 0.0),
    MetricDef("gen_start_failed", None, None, "power", 0.0, 1.0, 0.0),
    MetricDef("gen_fault_status", None, None, "power", 0.0, 1.0, 0.0),
    MetricDef("gen_fuel_level", None, "%", "power", 80.0, 10.0, 78.0),
    MetricDef("dc_branch_current", None, "A", "power", 6.5, 15.0, 6.0),
    MetricDef("dc_breaker_status", None, None, "power", 1.0, 0.0, 1.0),
    MetricDef("dc_overcurrent", None, None, "power", 0.0, 1.0, 0.0),
    MetricDef("spd_failure", None, None, "power", 0.0, 1.0, 0.0),
    MetricDef("room_temp", "Room Temperature", "C", "env", 24.0, 42.0, 24.0),
    MetricDef("room_humidity", "Room Humidity", "%", "env", 45.0, 5.0, 45.0),
    MetricDef("water_leak_status", None, None, "env", 0.0, 1.0, 0.0),
    MetricDef("smoke_status", None, None, "env", 0.0, 1.0, 0.0),
    MetricDef("ac_running_status", None, None, "env", 1.0, 0.0, 1.0),
    MetricDef("ac_fault_status", None, None, "env", 0.0, 1.0, 0.0),
    MetricDef("ac_high_pressure", None, None, "env", 0.0, 1.0, 0.0),
    MetricDef("ac_low_pressure", None, None, "env", 0.0, 1.0, 0.0),
    MetricDef("ac_comm_status", None, None, "env", 1.0, 0.0, 1.0),
    MetricDef("fresh_air_running_status", None, None, "env", 1.0, 0.0, 1.0),
    MetricDef("fresh_air_fault_status", None, None, "env", 0.0, 1.0, 0.0),
    MetricDef("door_access_status", None, None, "smart", 1.0, 0.0, 1.0),
    MetricDef("camera_online_status", None, None, "smart", 1.0, 0.0, 1.0),
    MetricDef("ups_bypass_status", None, None, "smart", 0.0, 1.0, 0.0),
]

EXPECTED_ALARM_CODES = {"mains_voltage_high", "room_temp_high", "room_humidity_low"}


def _metric_name(item: MetricDef) -> str:
    if item.name:
        return item.name
    return item.key


def _metric_payload(phase: str) -> list[dict]:
    rows: list[dict] = []
    for item in METRICS:
        if phase == "normal":
            value = item.normal
        elif phase == "alarm":
            value = item.alarm
        elif phase == "recover":
            value = item.recover
        else:
            raise ValueError(f"Unknown phase: {phase}")
        rows.append(
            {
                "key": item.key,
                "name": _metric_name(item),
                "value": float(value),
                "unit": item.unit,
                "category": item.category,
            }
        )
    return rows


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _post_ingest(
    base_url: str,
    site_code: str,
    site_name: str,
    fsu_code: str,
    fsu_name: str,
    phase: str,
    timeout: float,
) -> bool:
    payload = {
        "site_code": site_code,
        "site_name": site_name,
        "fsu_code": fsu_code,
        "fsu_name": fsu_name,
        "collected_at": _iso_now(),
        "metrics": _metric_payload(phase),
    }
    url = f"{base_url.rstrip('/')}/api/v1/ingest/telemetry"
    resp = requests.post(url, json=payload, timeout=timeout)
    ok = 200 <= resp.status_code < 300
    print(f"[INGEST:{phase}] status={resp.status_code} ok={ok}")
    if not ok:
        print(resp.text[:400])
    return ok


def _login(base_url: str, username: str, password: str, timeout: float) -> str:
    url = f"{base_url.rstrip('/')}/api/v1/auth/login"
    resp = requests.post(
        url,
        json={"username": username, "password": password},
        timeout=timeout,
    )
    resp.raise_for_status()
    token = resp.json()["access_token"]
    return token


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _load_rule_hold_seconds(base_url: str, token: str, timeout: float) -> int:
    target_keys = {"mains_voltage", "room_temp", "room_humidity"}
    url = f"{base_url.rstrip('/')}/api/v1/alarm-rules"
    try:
        resp = requests.get(url, headers=_headers(token), timeout=timeout)
        resp.raise_for_status()
    except Exception as exc:
        print(f"[WARN] load alarm-rules failed: {exc}")
        return 10

    hold = 0
    for row in resp.json():
        if not row.get("is_enabled", False):
            continue
        metric_key = row.get("metric_key")
        if metric_key in target_keys:
            hold = max(hold, int(row.get("duration_seconds", 0) or 0))
    return hold


def _list_alarms(base_url: str, token: str, timeout: float) -> list[dict]:
    url = f"{base_url.rstrip('/')}/api/v1/alarms"
    resp = requests.get(url, headers=_headers(token), timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def _list_latest(base_url: str, token: str, site_code: str, timeout: float) -> list[dict]:
    url = f"{base_url.rstrip('/')}/api/v1/telemetry/latest"
    resp = requests.get(
        url,
        headers=_headers(token),
        params={"site_code": site_code},
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()


def _history_count(
    base_url: str,
    token: str,
    site_code: str,
    point_key: str,
    start: datetime,
    end: datetime,
    timeout: float,
) -> int:
    url = f"{base_url.rstrip('/')}/api/v1/telemetry/history"
    resp = requests.get(
        url,
        headers=_headers(token),
        params={
            "site_code": site_code,
            "point_key": point_key,
            "start": start.isoformat(),
            "end": end.isoformat(),
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    return len(resp.json())


def _phase_loop(
    base_url: str,
    site_code: str,
    site_name: str,
    fsu_code: str,
    fsu_name: str,
    phase: str,
    hold_seconds: int,
    interval_seconds: int,
    timeout: float,
) -> bool:
    rounds = max(1, int(hold_seconds / max(interval_seconds, 1)))
    ok = True
    for i in range(rounds):
        state = _post_ingest(
            base_url=base_url,
            site_code=site_code,
            site_name=site_name,
            fsu_code=fsu_code,
            fsu_name=fsu_name,
            phase=phase,
            timeout=timeout,
        )
        ok = ok and state
        if i < rounds - 1:
            time.sleep(interval_seconds)
    return ok


def run(args) -> int:
    now_tag = datetime.now().strftime("%Y%m%d%H%M%S")
    site_code = args.site_code or f"SITE-TEST-{now_tag}"
    fsu_code = args.fsu_code or f"FSU-TEST-{now_tag}"
    site_name = args.site_name or f"FSU Test Site {now_tag}"
    fsu_name = args.fsu_name or f"FSU Test Host {now_tag}"
    start_time = datetime.now(timezone.utc)

    print("== FSU Full Metrics Test ==")
    print(f"base_url={args.base_url}")
    print(f"site={site_code} fsu={fsu_code} metric_count={len(METRICS)}")

    token = _login(args.base_url, args.username, args.password, args.timeout)
    print("[AUTH] login success")

    alarms_before = _list_alarms(args.base_url, token, args.timeout)
    max_alarm_id_before = max((item["id"] for item in alarms_before), default=0)
    print(f"[BASELINE] alarms_before={len(alarms_before)} max_id={max_alarm_id_before}")

    rule_hold = _load_rule_hold_seconds(args.base_url, token, args.timeout)
    hold_seconds = max(args.hold_seconds, rule_hold + args.hold_margin)
    print(f"[RULE] detected_duration={rule_hold}s test_hold={hold_seconds}s")

    ok_normal = _post_ingest(
        base_url=args.base_url,
        site_code=site_code,
        site_name=site_name,
        fsu_code=fsu_code,
        fsu_name=fsu_name,
        phase="normal",
        timeout=args.timeout,
    )

    ok_alarm = _phase_loop(
        base_url=args.base_url,
        site_code=site_code,
        site_name=site_name,
        fsu_code=fsu_code,
        fsu_name=fsu_name,
        phase="alarm",
        hold_seconds=hold_seconds,
        interval_seconds=args.interval_seconds,
        timeout=args.timeout,
    )

    ok_recover = _phase_loop(
        base_url=args.base_url,
        site_code=site_code,
        site_name=site_name,
        fsu_code=fsu_code,
        fsu_name=fsu_name,
        phase="recover",
        hold_seconds=hold_seconds,
        interval_seconds=args.interval_seconds,
        timeout=args.timeout,
    )

    latest = _list_latest(args.base_url, token, site_code, args.timeout)
    latest_keys = {
        item["point_key"]
        for item in latest
        if item.get("device_code") == fsu_code and item.get("site_code") == site_code
    }
    required_keys = {item.key for item in METRICS}
    missing_keys = sorted(required_keys - latest_keys)

    end_time = datetime.now(timezone.utc) + timedelta(seconds=5)
    history_room_temp = _history_count(
        args.base_url, token, site_code, "room_temp", start_time, end_time, args.timeout
    )
    history_room_humidity = _history_count(
        args.base_url, token, site_code, "room_humidity", start_time, end_time, args.timeout
    )
    history_mains_voltage = _history_count(
        args.base_url, token, site_code, "mains_voltage", start_time, end_time, args.timeout
    )

    alarms_after = _list_alarms(args.base_url, token, args.timeout)
    new_alarms = [item for item in alarms_after if int(item["id"]) > max_alarm_id_before]
    new_alarm_codes = sorted({item.get("alarm_code") for item in new_alarms})
    matched_expected_codes = sorted(EXPECTED_ALARM_CODES.intersection(set(new_alarm_codes)))

    print("\n== Test Summary ==")
    print(f"ingest_normal={ok_normal} ingest_alarm={ok_alarm} ingest_recover={ok_recover}")
    print(f"latest_rows={len(latest)} latest_device_keys={len(latest_keys)}")
    print(f"missing_keys={len(missing_keys)}")
    if missing_keys:
        print("missing_key_list=" + ",".join(missing_keys))
    print(
        f"history_counts room_temp={history_room_temp} "
        f"room_humidity={history_room_humidity} mains_voltage={history_mains_voltage}"
    )
    print(f"new_alarm_count={len(new_alarms)} new_alarm_codes={new_alarm_codes}")
    print(f"expected_alarm_codes_hit={matched_expected_codes}")

    passed = all(
        [
            ok_normal,
            ok_alarm,
            ok_recover,
            len(missing_keys) == 0,
            history_room_temp > 0,
            history_room_humidity > 0,
            history_mains_voltage > 0,
            len(matched_expected_codes) > 0,
        ]
    )
    print(f"result={'PASS' if passed else 'FAIL'}")
    return 0 if passed else 1


def parse_args():
    parser = argparse.ArgumentParser(description="FSU full telemetry and alarm test script")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="Backend base URL")
    parser.add_argument("--username", default="admin", help="Login username")
    parser.add_argument("--password", default="admin123", help="Login password")
    parser.add_argument("--site-code", default="", help="Optional fixed test site code")
    parser.add_argument("--site-name", default="", help="Optional fixed test site name")
    parser.add_argument("--fsu-code", default="", help="Optional fixed test fsu code")
    parser.add_argument("--fsu-name", default="", help="Optional fixed test fsu name")
    parser.add_argument("--hold-seconds", type=int, default=10, help="Minimum hold time per alarm/recover phase")
    parser.add_argument("--hold-margin", type=int, default=5, help="Extra hold seconds over rule duration")
    parser.add_argument("--interval-seconds", type=int, default=5, help="Interval between repeated reports")
    parser.add_argument("--timeout", type=float, default=8.0, help="HTTP timeout seconds")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    sys.exit(run(args))
