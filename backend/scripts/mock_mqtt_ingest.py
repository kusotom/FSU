from __future__ import annotations

import argparse
import json
import random
import time
from datetime import datetime, timezone

try:
    import paho.mqtt.client as mqtt
except ImportError as exc:  # pragma: no cover - runtime dependency check
    raise SystemExit("paho-mqtt is required. Install dependencies from requirements.txt first.") from exc


def _build_payload(seq: int) -> dict:
    return {
        "site_code": "S001",
        "site_name": "示例站点",
        "fsu_code": "FSU-001",
        "fsu_name": "动环主机-001",
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "metrics": [
            {
                "key": "temp_room",
                "name": "机房温度",
                "value": round(22 + random.uniform(-2, 2), 2),
                "unit": "°C",
                "category": "env",
            },
            {
                "key": "hum_room",
                "name": "机房湿度",
                "value": round(45 + random.uniform(-5, 5), 2),
                "unit": "%",
                "category": "env",
            },
            {
                "key": "voltage_a",
                "name": "A相电压",
                "value": round(220 + random.uniform(-6, 6), 2),
                "unit": "V",
                "category": "power",
            },
            {
                "key": "gen_fault",
                "name": "油机故障状态",
                "value": 1.0 if seq % 40 == 0 else 0.0,
                "unit": None,
                "category": "status",
            },
        ],
    }


def main():
    parser = argparse.ArgumentParser(description="Publish mock telemetry to MQTT.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--topic", default="fsu/telemetry/S001/FSU-001")
    parser.add_argument("--count", type=int, default=20)
    parser.add_argument("--interval", type=float, default=1.0)
    args = parser.parse_args()

    client = mqtt.Client()
    client.connect(args.host, args.port, keepalive=60)
    client.loop_start()
    try:
        for idx in range(args.count):
            payload = _build_payload(idx + 1)
            client.publish(args.topic, payload=json.dumps(payload, ensure_ascii=False), qos=1)
            print(f"published {idx + 1}/{args.count} to {args.topic}")
            time.sleep(max(args.interval, 0.05))
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
