import argparse
import sys
import time
from datetime import datetime, timezone

from test_all_metrics import (
    EXPECTED_ALARM_CODES,
    METRICS,
    _list_alarms,
    _list_latest,
    _load_rule_hold_seconds,
    _login,
    _post_ingest,
)


def parse_args():
    parser = argparse.ArgumentParser(description="FSU 持续稳定性测试脚本（默认20分钟）")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="后端地址")
    parser.add_argument("--username", default="admin", help="登录用户名")
    parser.add_argument("--password", default="admin123", help="登录密码")
    parser.add_argument("--duration-minutes", type=int, default=20, help="测试时长（分钟）")
    parser.add_argument("--interval-seconds", type=int, default=5, help="上报间隔（秒）")
    parser.add_argument("--check-interval-seconds", type=int, default=30, help="结果校验间隔（秒）")
    parser.add_argument("--phase-seconds", type=int, default=20, help="每个阶段时长（正常/告警/恢复）")
    parser.add_argument("--hold-margin", type=int, default=5, help="规则持续时间补偿（秒）")
    parser.add_argument("--timeout", type=float, default=8.0, help="HTTP超时（秒）")
    parser.add_argument("--site-code", default="", help="固定站点编码（可选）")
    parser.add_argument("--site-name", default="", help="固定站点名称（可选）")
    parser.add_argument("--fsu-code", default="", help="固定FSU编码（可选）")
    parser.add_argument("--fsu-name", default="", help="固定FSU名称（可选）")
    return parser.parse_args()


def _pick_phase(elapsed_seconds: float, phase_seconds: int) -> str:
    cycle = phase_seconds * 3
    pos = int(elapsed_seconds) % cycle
    block = pos // phase_seconds
    if block == 0:
        return "normal"
    if block == 1:
        return "alarm"
    return "recover"


def run(args) -> int:
    now_tag = datetime.now().strftime("%Y%m%d%H%M%S")
    site_code = args.site_code or f"SITE-SOAK-{now_tag}"
    fsu_code = args.fsu_code or f"FSU-SOAK-{now_tag}"
    site_name = args.site_name or f"Soak Test Site {now_tag}"
    fsu_name = args.fsu_name or f"Soak Test Host {now_tag}"

    if args.duration_minutes <= 0:
        print("[ERR] --duration-minutes 必须大于 0")
        return 2
    if args.interval_seconds <= 0 or args.check_interval_seconds <= 0:
        print("[ERR] 间隔参数必须大于 0")
        return 2

    print("== FSU 持续稳定性测试 ==")
    print(f"base_url={args.base_url}")
    print(f"duration_minutes={args.duration_minutes} interval_seconds={args.interval_seconds}")
    print(f"site={site_code} fsu={fsu_code} metric_count={len(METRICS)}")

    token = _login(args.base_url, args.username, args.password, args.timeout)
    print("[AUTH] 登录成功")

    alarms_before = _list_alarms(args.base_url, token, args.timeout)
    max_alarm_id_before = max((int(item.get("id", 0)) for item in alarms_before), default=0)
    print(f"[BASELINE] alarms_before={len(alarms_before)} max_id={max_alarm_id_before}")

    rule_hold = _load_rule_hold_seconds(args.base_url, token, args.timeout)
    phase_seconds = max(args.phase_seconds, rule_hold + args.hold_margin)
    print(f"[RULE] detected_hold={rule_hold}s using_phase_seconds={phase_seconds}s")

    start_mono = time.monotonic()
    end_mono = start_mono + args.duration_minutes * 60
    next_check = start_mono
    expected_keys = {item.key for item in METRICS}

    stats = {
        "ingest_ok": 0,
        "ingest_fail": 0,
        "check_ok": 0,
        "check_fail": 0,
        "max_missing_latest": 0,
        "new_alarm_count": 0,
    }
    seen_alarm_codes: set[str] = set()
    last_phase = None

    while True:
        now_mono = time.monotonic()
        if now_mono >= end_mono:
            break

        elapsed = now_mono - start_mono
        phase = _pick_phase(elapsed, phase_seconds)
        if phase != last_phase:
            print(f"[PHASE] t={elapsed:.0f}s -> {phase}")
            last_phase = phase

        ok = _post_ingest(
            base_url=args.base_url,
            site_code=site_code,
            site_name=site_name,
            fsu_code=fsu_code,
            fsu_name=fsu_name,
            phase=phase,
            timeout=args.timeout,
        )
        if ok:
            stats["ingest_ok"] += 1
        else:
            stats["ingest_fail"] += 1

        now_mono = time.monotonic()
        if now_mono >= next_check:
            try:
                latest = _list_latest(args.base_url, token, site_code, args.timeout)
                latest_keys = {
                    item.get("point_key")
                    for item in latest
                    if item.get("site_code") == site_code and item.get("device_code") == fsu_code
                }
                missing = sorted(expected_keys - latest_keys)
                stats["max_missing_latest"] = max(stats["max_missing_latest"], len(missing))

                alarms = _list_alarms(args.base_url, token, args.timeout)
                new_alarms = [item for item in alarms if int(item.get("id", 0)) > max_alarm_id_before]
                stats["new_alarm_count"] = max(stats["new_alarm_count"], len(new_alarms))
                for alarm in new_alarms:
                    code = alarm.get("alarm_code")
                    if code in EXPECTED_ALARM_CODES:
                        seen_alarm_codes.add(code)

                stats["check_ok"] += 1
                print(
                    f"[CHECK] elapsed={elapsed/60:.1f}m latest_keys={len(latest_keys)} "
                    f"missing={len(missing)} new_alarm={len(new_alarms)} "
                    f"seen_expected_alarm={len(seen_alarm_codes)}"
                )
            except Exception as exc:
                stats["check_fail"] += 1
                print(f"[CHECK][ERR] {exc}")
            next_check = now_mono + args.check_interval_seconds

        sleep_seconds = min(args.interval_seconds, max(0.0, end_mono - time.monotonic()))
        if sleep_seconds > 0:
            time.sleep(sleep_seconds)

    print("\n== Soak Summary ==")
    print(f"ingest_ok={stats['ingest_ok']} ingest_fail={stats['ingest_fail']}")
    print(f"check_ok={stats['check_ok']} check_fail={stats['check_fail']}")
    print(f"max_missing_latest={stats['max_missing_latest']}")
    print(f"new_alarm_count={stats['new_alarm_count']}")
    print(f"seen_expected_alarm_codes={sorted(seen_alarm_codes)}")

    passed = (
        stats["ingest_fail"] == 0
        and stats["check_fail"] == 0
        and stats["max_missing_latest"] == 0
        and len(seen_alarm_codes) > 0
    )
    print(f"result={'PASS' if passed else 'FAIL'}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(run(parse_args()))
