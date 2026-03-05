from datetime import datetime, timezone
from random import random

import requests

BASE_URL = "http://127.0.0.1:8000/api/v1"


def main():
    payload = {
        "site_code": "SITE-001",
        "site_name": "示例站点",
        "fsu_code": "FSU-001",
        "fsu_name": "示例FSU主机",
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "metrics": [
            {
                "key": "mains_voltage",
                "name": "市电电压",
                "value": round(180 + random() * 90, 2),
                "unit": "V",
                "category": "power",
            },
            {
                "key": "room_temp",
                "name": "机房温度",
                "value": round(10 + random() * 35, 2),
                "unit": "C",
                "category": "env",
            },
            {
                "key": "room_humidity",
                "name": "机房湿度",
                "value": round(20 + random() * 70, 2),
                "unit": "%",
                "category": "env",
            },
        ],
    }
    res = requests.post(f"{BASE_URL}/ingest/telemetry", json=payload, timeout=10)
    print(res.status_code, res.text)


if __name__ == "__main__":
    main()

