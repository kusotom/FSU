from __future__ import annotations

import json
import logging
import os
import queue
import signal
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.schemas.telemetry import TelemetryIngestRequest

try:
    import paho.mqtt.client as mqtt
except ImportError as exc:  # pragma: no cover - runtime dependency check
    raise SystemExit("paho-mqtt is required. Install dependencies from requirements.txt first.") from exc

try:
    from prometheus_client import Counter, Gauge, start_http_server  # type: ignore[import-untyped]
except Exception:  # pragma: no cover - optional fallback
    Counter = None  # type: ignore[assignment]
    Gauge = None  # type: ignore[assignment]
    start_http_server = None  # type: ignore[assignment]


logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s [mqtt-bridge] %(message)s",
)
logger = logging.getLogger("mqtt-bridge")


@dataclass(frozen=True)
class BridgeConfig:
    broker_host: str = os.getenv("MQTT_BROKER_HOST", "127.0.0.1")
    broker_port: int = int(os.getenv("MQTT_BROKER_PORT", "1883"))
    topic: str = os.getenv("MQTT_TOPIC", "fsu/telemetry/#")
    client_id: str = os.getenv("MQTT_CLIENT_ID", "fsu-mqtt-bridge")
    username: str = os.getenv("MQTT_USERNAME", "")
    password: str = os.getenv("MQTT_PASSWORD", "")
    qos: int = int(os.getenv("MQTT_QOS", "1"))
    backend_ingest_url: str = os.getenv(
        "BACKEND_INGEST_URL",
        "http://127.0.0.1:8000/api/v1/ingest/telemetry",
    )
    backend_timeout_seconds: float = float(os.getenv("BACKEND_TIMEOUT_SECONDS", "5"))
    backend_retry_times: int = int(os.getenv("BACKEND_RETRY_TIMES", "2"))
    bridge_queue_maxsize: int = int(os.getenv("BRIDGE_QUEUE_MAXSIZE", "50000"))
    bridge_worker_count: int = int(os.getenv("BRIDGE_WORKER_COUNT", "4"))
    metrics_port: int = int(os.getenv("BRIDGE_METRICS_PORT", "9108"))


CONFIG = BridgeConfig()
STOP_EVENT = threading.Event()
MESSAGE_QUEUE: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=max(CONFIG.bridge_queue_maxsize, 1000))
HTTP_SESSION = requests.Session()


if Counter is not None and Gauge is not None:
    mqtt_messages_total = Counter(
        "fsu_mqtt_bridge_messages_total",
        "MQTT bridge message count",
        labelnames=("result",),
    )
    mqtt_forward_seconds = Counter(
        "fsu_mqtt_bridge_forward_seconds_total",
        "Total seconds spent forwarding payloads to backend",
    )
    mqtt_queue_size = Gauge(
        "fsu_mqtt_bridge_queue_size",
        "MQTT bridge queue size",
    )
else:
    mqtt_messages_total = None
    mqtt_forward_seconds = None
    mqtt_queue_size = None


def _inc_message(result: str):
    if mqtt_messages_total is not None:
        mqtt_messages_total.labels(result=result).inc()


def _observe_forward_duration(duration_seconds: float):
    if mqtt_forward_seconds is not None:
        mqtt_forward_seconds.inc(max(duration_seconds, 0.0))


def _set_queue_size():
    if mqtt_queue_size is not None:
        mqtt_queue_size.set(MESSAGE_QUEUE.qsize())


def _normalize_payload(raw_payload: dict[str, Any]) -> dict[str, Any]:
    validated = TelemetryIngestRequest.model_validate(raw_payload)
    return validated.model_dump(mode="json")


def _forward_to_backend(payload: dict[str, Any]) -> bool:
    started_at = time.perf_counter()
    retries = max(CONFIG.backend_retry_times, 0)
    for attempt in range(retries + 1):
        try:
            response = HTTP_SESSION.post(
                CONFIG.backend_ingest_url,
                json=payload,
                timeout=CONFIG.backend_timeout_seconds,
            )
            if 200 <= response.status_code < 300:
                _inc_message("forwarded")
                _observe_forward_duration(time.perf_counter() - started_at)
                return True
            logger.warning(
                "backend rejected payload: status=%s body=%s attempt=%s",
                response.status_code,
                response.text[:200],
                attempt + 1,
            )
        except Exception as exc:
            logger.warning("forward failed: attempt=%s error=%s", attempt + 1, exc)
        time.sleep(min(0.2 * (attempt + 1), 1.0))
    _inc_message("forward_failed")
    _observe_forward_duration(time.perf_counter() - started_at)
    return False


def _worker_loop(worker_index: int):
    logger.info("worker started: %s", worker_index)
    while not STOP_EVENT.is_set():
        try:
            payload = MESSAGE_QUEUE.get(timeout=0.5)
        except queue.Empty:
            continue
        try:
            _forward_to_backend(payload)
        finally:
            MESSAGE_QUEUE.task_done()
            _set_queue_size()
    logger.info("worker stopped: %s", worker_index)


def _on_connect(client: mqtt.Client, _userdata, _flags, reason_code, _properties=None):
    reason_value = getattr(reason_code, "value", reason_code)
    if reason_value == 0:
        client.subscribe(CONFIG.topic, qos=CONFIG.qos)
        logger.info("connected and subscribed: topic=%s qos=%s", CONFIG.topic, CONFIG.qos)
        _inc_message("connected")
        return
    logger.error("mqtt connect failed: reason=%s", reason_code)
    _inc_message("connect_failed")


def _on_message(_client: mqtt.Client, _userdata, message: mqtt.MQTTMessage):
    try:
        payload_text = message.payload.decode("utf-8")
        payload_data = json.loads(payload_text)
        if not isinstance(payload_data, dict):
            raise ValueError("payload must be a JSON object")
        normalized = _normalize_payload(payload_data)
    except Exception as exc:
        logger.warning("invalid message: topic=%s error=%s", message.topic, exc)
        _inc_message("invalid")
        return

    try:
        MESSAGE_QUEUE.put_nowait(normalized)
        _inc_message("accepted")
        _set_queue_size()
    except queue.Full:
        logger.error("bridge queue full, dropping message: topic=%s", message.topic)
        _inc_message("queue_full")


def _build_mqtt_client() -> mqtt.Client:
    try:
        client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,  # type: ignore[attr-defined]
            client_id=CONFIG.client_id,
        )
    except Exception:
        client = mqtt.Client(client_id=CONFIG.client_id)

    if CONFIG.username:
        client.username_pw_set(CONFIG.username, CONFIG.password)

    client.on_connect = _on_connect
    client.on_message = _on_message
    return client


def _signal_handler(_signum, _frame):
    STOP_EVENT.set()


def main() -> int:
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    if start_http_server is not None and CONFIG.metrics_port > 0:
        start_http_server(CONFIG.metrics_port)
        logger.info("bridge metrics exposed: port=%s", CONFIG.metrics_port)

    workers: list[threading.Thread] = []
    for idx in range(max(CONFIG.bridge_worker_count, 1)):
        thread = threading.Thread(target=_worker_loop, args=(idx,), daemon=True)
        thread.start()
        workers.append(thread)

    client = _build_mqtt_client()
    logger.info(
        "mqtt bridge starting: broker=%s:%s topic=%s backend=%s",
        CONFIG.broker_host,
        CONFIG.broker_port,
        CONFIG.topic,
        CONFIG.backend_ingest_url,
    )

    try:
        client.connect(CONFIG.broker_host, CONFIG.broker_port, keepalive=60)
    except Exception as exc:
        logger.error("unable to connect mqtt broker: %s", exc)
        return 1

    client.loop_start()
    try:
        while not STOP_EVENT.is_set():
            time.sleep(0.5)
    finally:
        logger.info("stopping mqtt bridge")
        client.loop_stop()
        client.disconnect()
        STOP_EVENT.set()
        for thread in workers:
            thread.join(timeout=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
