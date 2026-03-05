import argparse
import asyncio
import random
import time
from collections import Counter
from datetime import datetime, timezone

import httpx


def make_payload(device_no: int) -> dict:
    site_no = (device_no % 200) + 1
    return {
        "site_code": f"SITE-{site_no:03d}",
        "site_name": f"\u7ad9\u70b9-{site_no:03d}",
        "fsu_code": f"FSU-{device_no:04d}",
        "fsu_name": f"FSU\u4e3b\u673a-{device_no:04d}",
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "metrics": [
            {
                "key": "mains_voltage",
                "name": "\u5e02\u7535\u7535\u538b",
                "value": round(175 + random.random() * 100, 2),
                "unit": "V",
                "category": "power",
            },
            {
                "key": "room_temp",
                "name": "\u673a\u623f\u6e29\u5ea6",
                "value": round(8 + random.random() * 40, 2),
                "unit": "C",
                "category": "env",
            },
            {
                "key": "room_humidity",
                "name": "\u673a\u623f\u6e7f\u5ea6",
                "value": round(15 + random.random() * 80, 2),
                "unit": "%",
                "category": "env",
            },
        ],
    }


async def ingest_once(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    endpoint: str,
    device_no: int,
    delay_seconds: float,
    retries: int,
) -> tuple[bool, float, str | None]:
    await asyncio.sleep(max(delay_seconds, 0.0))
    payload = make_payload(device_no)
    async with sem:
        started = time.perf_counter()
        attempts = max(retries, 0) + 1
        last_error = "unknown"
        for attempt in range(attempts):
            try:
                resp = await client.post(endpoint, json=payload)
                elapsed = time.perf_counter() - started
                ok = 200 <= resp.status_code < 300
                if ok:
                    return True, elapsed, None
                code = f"http_{resp.status_code}"
                if resp.status_code >= 500 and attempt + 1 < attempts:
                    await asyncio.sleep(0.05 * (attempt + 1))
                    last_error = code
                    continue
                return False, elapsed, code
            except Exception as exc:
                last_error = exc.__class__.__name__
                if attempt + 1 < attempts:
                    await asyncio.sleep(0.05 * (attempt + 1))
                    continue
                elapsed = time.perf_counter() - started
                return False, elapsed, last_error
        elapsed = time.perf_counter() - started
        return False, elapsed, last_error


async def run_test(
    *,
    base_url: str,
    devices: int,
    rounds: int,
    cycle_seconds: float,
    concurrency: int,
    max_connections: int,
    retries: int,
):
    endpoint = f"{base_url.rstrip('/')}/api/v1/ingest/telemetry"
    sem = asyncio.Semaphore(concurrency)
    timeout = httpx.Timeout(connect=8.0, read=60.0, write=60.0, pool=60.0)
    limits = httpx.Limits(
        max_connections=max(max_connections, concurrency),
        max_keepalive_connections=max(max_connections // 2, 100),
    )

    async with httpx.AsyncClient(timeout=timeout, limits=limits) as client:
        total_success = 0
        total_fail = 0
        total_errors: Counter[str] = Counter()
        all_started = time.perf_counter()
        for round_no in range(1, rounds + 1):
            round_started = time.perf_counter()
            tasks = []
            for i in range(devices):
                delay = (i / max(devices, 1)) * cycle_seconds
                tasks.append(ingest_once(client, sem, endpoint, i + 1, delay, retries))
            results = await asyncio.gather(*tasks)
            success = sum(1 for ok, _, _ in results if ok)
            fail = devices - success
            latencies = [lat for ok, lat, _ in results if ok]
            round_errors = Counter(tag for ok, _, tag in results if (not ok and tag))
            total_errors.update(round_errors)
            round_elapsed = time.perf_counter() - round_started
            avg_latency = (sum(latencies) / len(latencies)) if latencies else 0.0
            p95_latency = sorted(latencies)[int(len(latencies) * 0.95)] if latencies else 0.0
            total_success += success
            total_fail += fail
            top_errors = ", ".join(f"{k}:{v}" for k, v in round_errors.most_common(3)) or "-"
            print(
                f"[Round {round_no}] success={success} fail={fail} "
                f"elapsed={round_elapsed:.2f}s avg_latency={avg_latency:.3f}s p95_latency={p95_latency:.3f}s "
                f"throughput={success / round_elapsed if round_elapsed > 0 else 0:.2f} req/s "
                f"errors={top_errors}"
            )

        all_elapsed = time.perf_counter() - all_started
        print("-" * 60)
        print(f"Total requests: {devices * rounds}")
        print(f"Success: {total_success}")
        print(f"Fail: {total_fail}")
        print(f"Total elapsed: {all_elapsed:.2f}s")
        print(f"Average throughput: {total_success / all_elapsed if all_elapsed > 0 else 0:.2f} req/s")
        if total_errors:
            print("Fail reasons:", ", ".join(f"{k}:{v}" for k, v in total_errors.most_common()))


def parse_args():
    parser = argparse.ArgumentParser(description="FSU realtime load test with paced send window")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="Backend base URL")
    parser.add_argument("--devices", type=int, default=2000, help="Devices per round")
    parser.add_argument("--rounds", type=int, default=1, help="How many rounds to run")
    parser.add_argument(
        "--cycle-seconds",
        type=float,
        default=15.0,
        help="Spread one round's device requests across this many seconds",
    )
    parser.add_argument("--concurrency", type=int, default=300, help="Max concurrent requests")
    parser.add_argument(
        "--max-connections",
        type=int,
        default=1200,
        help="HTTP connection pool size for the load client",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=1,
        help="Retry count for transient transport/5xx failures",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    asyncio.run(
        run_test(
            base_url=args.base_url,
            devices=args.devices,
            rounds=args.rounds,
            cycle_seconds=args.cycle_seconds,
            concurrency=args.concurrency,
            max_connections=args.max_connections,
            retries=args.retries,
        )
    )
