import argparse
import asyncio
import random
import time
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
    retries: int,
) -> bool:
    payload = make_payload(device_no)
    async with sem:
        attempts = max(retries, 0) + 1
        for attempt in range(attempts):
            try:
                resp = await client.post(endpoint, json=payload)
                if 200 <= resp.status_code < 300:
                    return True
                if resp.status_code >= 500 and attempt + 1 < attempts:
                    await asyncio.sleep(0.05 * (attempt + 1))
                    continue
                return False
            except Exception:
                if attempt + 1 < attempts:
                    await asyncio.sleep(0.05 * (attempt + 1))
                    continue
                return False


async def run_test(
    base_url: str,
    devices: int,
    rounds: int,
    concurrency: int,
    max_connections: int,
    retries: int,
):
    endpoint = f"{base_url.rstrip('/')}/api/v1/ingest/telemetry"
    sem = asyncio.Semaphore(concurrency)
    timeout = httpx.Timeout(connect=8.0, read=30.0, write=30.0, pool=30.0)
    limits = httpx.Limits(
        max_connections=max(max_connections, concurrency),
        max_keepalive_connections=max(max_connections // 2, 100),
    )

    async with httpx.AsyncClient(timeout=timeout, limits=limits) as client:
        total_success = 0
        total_fail = 0
        total_requests = devices * rounds
        start_all = time.perf_counter()

        for n in range(1, rounds + 1):
            round_start = time.perf_counter()
            tasks = [ingest_once(client, sem, endpoint, i + 1, retries) for i in range(devices)]
            results = await asyncio.gather(*tasks)
            succ = sum(1 for x in results if x)
            fail = len(results) - succ
            total_success += succ
            total_fail += fail
            elapsed = time.perf_counter() - round_start
            rps = succ / elapsed if elapsed > 0 else 0
            print(
                f"[Round {n}] success={succ} fail={fail} elapsed={elapsed:.2f}s "
                f"throughput={rps:.2f} req/s"
            )

        elapsed_all = time.perf_counter() - start_all
        avg_rps = total_success / elapsed_all if elapsed_all > 0 else 0
        print("-" * 60)
        print(f"Total requests: {total_requests}")
        print(f"Success: {total_success}")
        print(f"Fail: {total_fail}")
        print(f"Total elapsed: {elapsed_all:.2f}s")
        print(f"Average throughput: {avg_rps:.2f} req/s")


def parse_args():
    parser = argparse.ArgumentParser(description="FSU 2000-device ingest load test")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="Backend base URL")
    parser.add_argument("--devices", type=int, default=2000, help="Device count per round")
    parser.add_argument("--rounds", type=int, default=3, help="How many rounds to run")
    parser.add_argument("--concurrency", type=int, default=200, help="Concurrent requests")
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
            concurrency=args.concurrency,
            max_connections=args.max_connections,
            retries=args.retries,
        )
    )
