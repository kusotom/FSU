import argparse
import math
import random
import time
from datetime import datetime, timezone

import requests

from test_all_metrics import METRICS


def parse_args():
    parser = argparse.ArgumentParser(description="按固定间隔上报动环数据（默认15秒，持续10分钟）")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="后端地址")
    parser.add_argument("--interval-seconds", type=float, default=15.0, help="上报间隔（秒）")
    parser.add_argument("--duration-minutes", type=float, default=10.0, help="持续时长（分钟）")
    parser.add_argument("--site-code", default="SITE-001", help="站点编码")
    parser.add_argument("--site-name", default="示例站点", help="站点名称")
    parser.add_argument("--fsu-code", default="FSU-001", help="FSU编码")
    parser.add_argument("--fsu-name", default="示例FSU主机", help="FSU名称")
    parser.add_argument("--timeout", type=float, default=8.0, help="HTTP超时（秒）")
    parser.add_argument("--seed", type=int, default=2026, help="随机种子")
    return parser.parse_args()


def _metric_name(item) -> str:
    if item.name:
        return item.name
    return item.key


def _metric_value(item, elapsed_min: float, idx: int) -> float:
    # 状态量保持正常值，避免频繁抖动触发无意义告警
    if item.normal in (0.0, 1.0) and item.alarm in (0.0, 1.0) and item.unit is None:
        return float(item.normal)

    baseline = float(item.normal)
    span = abs(float(item.alarm) - baseline)
    if span < 0.01:
        span = max(abs(baseline) * 0.1, 1.0)

    amp = max(span * 0.22, 0.05)
    period = 6.0 + (idx % 7) * 2.3
    phase = idx * 0.37
    noise = amp * 0.08

    value = baseline + amp * math.sin((2 * math.pi * elapsed_min / period) + phase)
    value += random.uniform(-noise, noise)
    return float(value)


def _build_payload(args, elapsed_min: float) -> dict:
    metrics = []
    for idx, item in enumerate(METRICS):
        metrics.append(
            {
                "key": item.key,
                "name": _metric_name(item),
                "value": round(_metric_value(item, elapsed_min, idx), 3),
                "unit": item.unit,
                "category": item.category,
            }
        )
    return {
        "site_code": args.site_code,
        "site_name": args.site_name,
        "fsu_code": args.fsu_code,
        "fsu_name": args.fsu_name,
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "metrics": metrics,
    }


def run(args) -> int:
    if args.interval_seconds <= 0:
        print("[ERR] interval-seconds 必须大于 0")
        return 2
    if args.duration_minutes <= 0:
        print("[ERR] duration-minutes 必须大于 0")
        return 2

    random.seed(args.seed)
    url = f"{args.base_url.rstrip('/')}/api/v1/ingest/telemetry"
    total_seconds = args.duration_minutes * 60.0
    rounds = int(total_seconds // args.interval_seconds)
    if rounds * args.interval_seconds < total_seconds:
        rounds += 1
    rounds = max(rounds, 1)

    ok_count = 0
    fail_count = 0
    start = time.monotonic()

    print("== FSU 定时采集测试 ==")
    print(f"url={url}")
    print(f"duration_minutes={args.duration_minutes} interval_seconds={args.interval_seconds}")
    print(f"rounds={rounds} metrics_per_round={len(METRICS)}")

    for i in range(rounds):
        now = time.monotonic()
        elapsed_min = (now - start) / 60.0
        payload = _build_payload(args, elapsed_min)
        try:
            resp = requests.post(url, json=payload, timeout=args.timeout)
            ok = 200 <= resp.status_code < 300
            if ok:
                ok_count += 1
            else:
                fail_count += 1
            print(
                f"[{i + 1}/{rounds}] t={elapsed_min:.2f}m "
                f"status={resp.status_code} ok={ok} at={payload['collected_at']}"
            )
        except Exception as exc:
            fail_count += 1
            print(f"[{i + 1}/{rounds}] t={elapsed_min:.2f}m status=ERR ok=False err={exc}")

        if i < rounds - 1:
            time.sleep(args.interval_seconds)

    print("== Summary ==")
    print(f"ok={ok_count} fail={fail_count}")
    print(f"result={'PASS' if fail_count == 0 else 'FAIL'}")
    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
