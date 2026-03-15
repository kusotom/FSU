from __future__ import annotations

import json
import logging
import os
import signal
import socket
import socketserver
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import requests

CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.protocol_adapters import get_dtu_payload_adapter_names


def _decode_delimiter(value: str) -> bytes:
    return value.encode("utf-8").decode("unicode_escape").encode("utf-8")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s [dtu-gateway] %(message)s",
)
logger = logging.getLogger("dtu-gateway")


@dataclass(frozen=True)
class GatewayConfig:
    host: str = os.getenv("DTU_GATEWAY_HOST", "0.0.0.0")
    port: int = int(os.getenv("DTU_GATEWAY_PORT", "9001"))
    protocol: str = os.getenv("DTU_GATEWAY_PROTOCOL", "json_line").strip().lower().replace("-", "_")
    frame_mode: str = os.getenv("DTU_GATEWAY_FRAME_MODE", "line").strip().lower()
    frame_delimiter: str = os.getenv("DTU_GATEWAY_FRAME_DELIMITER", "\\n")
    idle_flush_seconds: float = float(os.getenv("DTU_GATEWAY_IDLE_FLUSH_SECONDS", "0.5"))
    socket_timeout_seconds: float = float(os.getenv("DTU_GATEWAY_SOCKET_TIMEOUT_SECONDS", "0.5"))
    message_max_bytes: int = int(os.getenv("DTU_GATEWAY_MESSAGE_MAX_BYTES", "32768"))
    socket_read_size: int = int(os.getenv("DTU_GATEWAY_SOCKET_READ_SIZE", "4096"))
    backend_ingest_url: str = os.getenv(
        "DTU_GATEWAY_BACKEND_INGEST_URL",
        "http://127.0.0.1:8000/api/v1/ingest/dtu",
    )
    backend_timeout_seconds: float = float(os.getenv("DTU_GATEWAY_BACKEND_TIMEOUT_SECONDS", "5"))
    backend_retry_times: int = int(os.getenv("DTU_GATEWAY_BACKEND_RETRY_TIMES", "2"))
    raw_log_enabled: bool = os.getenv("DTU_GATEWAY_RAW_LOG_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
    raw_log_dir: str = os.getenv("DTU_GATEWAY_RAW_LOG_DIR", "logs/dtu-raw")


CONFIG = GatewayConfig()
STOP_EVENT = threading.Event()
RAW_LOG_LOCK = threading.Lock()
FRAME_DELIMITER = _decode_delimiter(CONFIG.frame_delimiter)
RAW_LOG_DIR = Path(CONFIG.raw_log_dir)
if not RAW_LOG_DIR.is_absolute():
    RAW_LOG_DIR = PROJECT_ROOT / RAW_LOG_DIR


class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


def _append_raw_log(record: dict):
    if not CONFIG.raw_log_enabled:
        return
    RAW_LOG_DIR.mkdir(parents=True, exist_ok=True)
    target = RAW_LOG_DIR / f"dtu-{datetime.now().strftime('%Y%m%d')}.jsonl"
    with RAW_LOG_LOCK:
        with target.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(record, ensure_ascii=False))
            fp.write("\n")


def _build_backend_payload(frame: bytes, client_address: tuple[str, int]) -> dict:
    payload = {
        "protocol": CONFIG.protocol,
        "remote_addr": client_address[0],
        "remote_port": client_address[1],
        "received_at": _utc_now_iso(),
        "payload_hex": frame.hex(),
    }
    try:
        payload["payload_text"] = frame.decode("utf-8")
    except UnicodeDecodeError:
        pass
    return payload


def _forward_frame(frame: bytes, client_address: tuple[str, int]):
    trimmed = frame.strip()
    if not trimmed:
        return

    backend_payload = _build_backend_payload(trimmed, client_address)
    _append_raw_log(backend_payload)

    retries = max(CONFIG.backend_retry_times, 0)
    for attempt in range(retries + 1):
        try:
            response = requests.post(
                CONFIG.backend_ingest_url,
                json=backend_payload,
                timeout=CONFIG.backend_timeout_seconds,
            )
            if 200 <= response.status_code < 300:
                logger.info(
                    "frame forwarded: client=%s:%s bytes=%s status=%s",
                    client_address[0],
                    client_address[1],
                    len(trimmed),
                    response.status_code,
                )
                return
            logger.warning(
                "backend rejected frame: client=%s:%s status=%s body=%s attempt=%s",
                client_address[0],
                client_address[1],
                response.status_code,
                response.text[:200],
                attempt + 1,
            )
        except Exception as exc:
            logger.warning(
                "forward failed: client=%s:%s attempt=%s error=%s",
                client_address[0],
                client_address[1],
                attempt + 1,
                exc,
            )
        time.sleep(min(0.2 * (attempt + 1), 1.0))


def _drain_line_frames(buffer: bytearray, client_address: tuple[str, int]):
    if not FRAME_DELIMITER:
        return
    while True:
        delimiter_index = buffer.find(FRAME_DELIMITER)
        if delimiter_index < 0:
            return
        frame = bytes(buffer[:delimiter_index]).rstrip(b"\r")
        del buffer[: delimiter_index + len(FRAME_DELIMITER)]
        _forward_frame(frame, client_address)


class DTURequestHandler(socketserver.BaseRequestHandler):
    def handle(self):
        client_host, client_port = self.client_address
        logger.info("client connected: %s:%s", client_host, client_port)
        socket_timeout = CONFIG.idle_flush_seconds if CONFIG.frame_mode == "idle" else CONFIG.socket_timeout_seconds
        self.request.settimeout(max(socket_timeout, 0.1))
        buffer = bytearray()

        try:
            while not STOP_EVENT.is_set():
                try:
                    chunk = self.request.recv(max(CONFIG.socket_read_size, 1024))
                except socket.timeout:
                    if CONFIG.frame_mode == "idle" and buffer:
                        _forward_frame(bytes(buffer), self.client_address)
                        buffer.clear()
                    continue

                if not chunk:
                    break

                buffer.extend(chunk)
                if len(buffer) > max(CONFIG.message_max_bytes, 1024):
                    logger.warning(
                        "frame dropped because it exceeded limit: client=%s:%s bytes=%s",
                        client_host,
                        client_port,
                        len(buffer),
                    )
                    buffer.clear()
                    continue

                if CONFIG.frame_mode == "line":
                    _drain_line_frames(buffer, self.client_address)
        finally:
            if buffer:
                _forward_frame(bytes(buffer), self.client_address)
            logger.info("client disconnected: %s:%s", client_host, client_port)


def _signal_handler(_signum, _frame):
    STOP_EVENT.set()


def main() -> int:
    available_protocols = get_dtu_payload_adapter_names()
    if CONFIG.protocol not in available_protocols:
        logger.error("unsupported DTU protocol=%s available=%s", CONFIG.protocol, ",".join(available_protocols))
        return 1
    if CONFIG.frame_mode not in {"line", "idle"}:
        logger.error("unsupported DTU frame mode=%s", CONFIG.frame_mode)
        return 1

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    server = ThreadedTCPServer((CONFIG.host, CONFIG.port), DTURequestHandler)
    server.timeout = max(CONFIG.idle_flush_seconds, 0.1)

    logger.info(
        "DTU gateway starting: listen=%s:%s protocol=%s frame_mode=%s backend=%s",
        CONFIG.host,
        CONFIG.port,
        CONFIG.protocol,
        CONFIG.frame_mode,
        CONFIG.backend_ingest_url,
    )
    logger.info("available DTU adapters: %s", ", ".join(available_protocols))

    try:
        while not STOP_EVENT.is_set():
            server.handle_request()
    finally:
        logger.info("stopping DTU gateway")
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
