import argparse
import math
import random
import time
from datetime import datetime, timezone

import requests


def parse_args():
    parser = argparse.ArgumentParser(description="Generate smooth telemetry data for curve display.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="Backend base URL")
    parser.add_argument("--duration-minutes", type=float, default=20.0, help="Run time in minutes; <=0 means run forever")
    parser.add_argument("--interval-seconds", type=float, default=5.0, help="Send interval seconds")
    parser.add_argument("--site-count", type=int, default=2, help="How many demo sites to generate")
    parser.add_argument("--timeout", type=float, default=8.0, help="HTTP timeout in seconds")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    return parser.parse_args()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _wave(
    elapsed_min: float,
    base: float,
    amplitude: float,
    period_min: float,
    phase: float,
    noise: float,
) -> float:
    value = base + amplitude * math.sin((2 * math.pi * elapsed_min / period_min) + phase)
    value += random.uniform(-noise, noise)
    return value


def _build_metrics(elapsed_min: float, site_index: int) -> list[dict]:
    phase = site_index * 0.55

    mains_voltage = _wave(elapsed_min, base=220.0, amplitude=7.0, period_min=18.0, phase=phase, noise=0.8)
    mains_current = _wave(elapsed_min, base=11.5, amplitude=2.2, period_min=10.0, phase=phase, noise=0.3)
    battery_group_voltage = _wave(
        elapsed_min, base=52.4, amplitude=1.3, period_min=16.0, phase=phase + 0.8, noise=0.15
    )
    room_temp = _wave(elapsed_min, base=25.0, amplitude=4.0, period_min=24.0, phase=phase + 1.3, noise=0.25)
    room_humidity = _wave(
        elapsed_min, base=48.0, amplitude=9.0, period_min=20.0, phase=phase + 2.1, noise=0.8
    )
    dc_branch_current = _wave(
        elapsed_min, base=6.2, amplitude=1.1, period_min=12.0, phase=phase + 0.4, noise=0.12
    )
    gen_fuel_level = max(5.0, 85.0 - elapsed_min * 0.05 + random.uniform(-0.2, 0.2))

    # Add a small periodic spike to make curves visually obvious.
    if int(elapsed_min) % 11 == 0 and elapsed_min > 0.5:
        room_temp += 3.5
        mains_voltage += 5.0

    return [
        {"key": "mains_voltage", "name": "Mains Voltage", "value": round(mains_voltage, 2), "unit": "V", "category": "power"},
        {"key": "mains_current", "name": "Mains Current", "value": round(mains_current, 2), "unit": "A", "category": "power"},
        {
            "key": "battery_group_voltage",
            "name": "Battery Group Voltage",
            "value": round(battery_group_voltage, 2),
            "unit": "V",
            "category": "power",
        },
        {
            "key": "dc_branch_current",
            "name": "DC Branch Current",
            "value": round(dc_branch_current, 2),
            "unit": "A",
            "category": "power",
        },
        {"key": "room_temp", "name": "Room Temperature", "value": round(room_temp, 2), "unit": "C", "category": "env"},
        {
            "key": "room_humidity",
            "name": "Room Humidity",
            "value": round(room_humidity, 2),
            "unit": "%",
            "category": "env",
        },
        {"key": "gen_fuel_level", "name": "Generator Fuel Level", "value": round(gen_fuel_level, 2), "unit": "%", "category": "power"},
    ]


def _post_one(base_url: str, payload: dict, timeout: float) -> bool:
    url = f"{base_url.rstrip('/')}/api/v1/ingest/telemetry"
    try:
        resp = requests.post(url, json=payload, timeout=timeout)
        return 200 <= resp.status_code < 300
    except Exception:
        return False


def run(args) -> int:
    random.seed(args.seed)

    start = time.monotonic()
    if args.duration_minutes <= 0:
        end = None
    else:
        end = start + args.duration_minutes * 60.0

    ok_count = 0
    fail_count = 0
    tick = 0

    print("== Curve Data Generator ==")
    print(f"base_url={args.base_url} site_count={args.site_count} interval={args.interval_seconds}s")
    print(f"duration_minutes={args.duration_minutes} (<=0 means forever)")

    while True:
        now = time.monotonic()
        if end is not None and now >= end:
            break

        elapsed_min = (now - start) / 60.0
        ts = _now_iso()

        batch_ok = 0
        for i in range(1, args.site_count + 1):
            payload = {
                "site_code": f"SITE-CURVE-{i:03d}",
                "site_name": f"Curve Demo Site {i:03d}",
                "fsu_code": f"FSU-CURVE-{i:03d}",
                "fsu_name": f"Curve Demo FSU {i:03d}",
                "collected_at": ts,
                "metrics": _build_metrics(elapsed_min, i),
            }
            if _post_one(args.base_url, payload, args.timeout):
                ok_count += 1
                batch_ok += 1
            else:
                fail_count += 1

        tick += 1
        if tick % max(1, int(60 / max(args.interval_seconds, 0.1))) == 0:
            print(
                f"[{datetime.now().strftime('%H:%M:%S')}] elapsed={elapsed_min:.1f}m "
                f"batch_ok={batch_ok}/{args.site_count} total_ok={ok_count} total_fail={fail_count}"
            )

        time.sleep(max(args.interval_seconds, 0.1))

    print("== Done ==")
    print(f"total_ok={ok_count} total_fail={fail_count}")
    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
