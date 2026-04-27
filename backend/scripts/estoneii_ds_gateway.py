from __future__ import annotations

import argparse
import json
import logging
import os
import select
import signal
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ds_udp9000_responder import build_reply, decode_payload, save_capture


CURRENT_DIR = Path(__file__).resolve().parent
BACKEND_ROOT = CURRENT_DIR.parent
REPO_ROOT = CURRENT_DIR.parents[1]
STOP_EVENT = threading.Event()
LOG_LOCK = threading.Lock()


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_now_text() -> str:
    return utc_now().strftime("%Y%m%dT%H%M%S.%fZ")


def parse_int_list(text: str) -> list[int]:
    return [int(item.strip(), 0) for item in text.split(",") if item.strip()]


def resolve_path(path_text: str) -> Path:
    path = Path(path_text)
    if not path.is_absolute():
        first_part = path.parts[0].lower() if path.parts else ""
        if first_part == "backend":
            path = REPO_ROOT / path
        else:
            path = BACKEND_ROOT / path
    return path


@dataclass(frozen=True)
class GatewayConfig:
    host: str
    udp_ports: list[int]
    output_dir: Path
    event_log_name: str
    capture_packets: bool
    duration_seconds: int
    buffer_size: int
    ds_url: str
    ds_service_types: str
    ds_table_status_byte: int
    ds_table_length_endian: str
    ds_table_size_field: str
    ds_table_include_count: bool
    backend_ingest_url: str
    backend_timeout_seconds: float
    backend_retry_times: int
    backend_worker_count: int
    forward_short_acks: bool
    site_code: str
    site_name: str
    fsu_code: str
    fsu_name: str


class ReplyArgs:
    reply_mode = "estoneii-ds-ack"
    reply_prefix_size = 22
    reply_text = "OK"
    reply_hex = ""
    reply_status = 1
    reply_command_mode = "same"
    reply_seq_delta = 0
    reply_header3 = None
    reply_header6 = None
    sc_url = ""

    def __init__(self, config: GatewayConfig):
        self.ds_url = config.ds_url
        self.ds_service_types = config.ds_service_types
        self.ds_table_status_byte = config.ds_table_status_byte
        self.ds_table_length_endian = config.ds_table_length_endian
        self.ds_table_size_field = config.ds_table_size_field
        self.ds_table_include_count = config.ds_table_include_count


def classify_packet(payload: bytes, decoded: dict[str, Any], local_port: int, reply: bytes | None) -> dict[str, Any]:
    header = decoded.get("header") or {}
    body = payload[24:] if len(payload) >= 24 else b""
    command_id = header.get("command_id")
    header6 = payload[6] if len(payload) > 6 else None
    event_type = "unknown"
    parsed: dict[str, Any] = {}

    if command_id == 0x0011 and header6 == 0x46:
        event_type = "ds_get_service_addr"
        parsed["reported_urls"] = decoded.get("summary", {}).get("device_udp_urls", [])
    elif command_id == 0x8011 and header6 == 0xD2 and len(body) == 6:
        event_type = "ds_heartbeat"
        timestamp = int.from_bytes(body[1:5], "little")
        parsed["device_timestamp_unix"] = timestamp
        if timestamp:
            parsed["device_timestamp_local_hint"] = datetime.fromtimestamp(timestamp).isoformat()
    elif command_id == 0x001F:
        event_type = "ds_short_ack"
    elif command_id == 0x8010 and header6 == 0x2B:
        event_type = "send_all_comm_state"
        if len(body) >= 27:
            timestamp = int.from_bytes(body[22:26], "little")
            parsed.update(
                {
                    "body_hex": body.hex(),
                    "device_timestamp_unix": timestamp,
                    "device_timestamp_local_hint": datetime.fromtimestamp(timestamp).isoformat()
                    if timestamp
                    else "",
                    "tail": body[26],
                }
            )

    return {
        "event_type": event_type,
        "received_at": utc_now().isoformat(),
        "local_port": local_port,
        "payload_size": len(payload),
        "reply_size": 0 if reply is None else len(reply),
        "sequence": header.get("sequence"),
        "command_id": command_id,
        "command_hex": "" if command_id is None else f"0x{command_id:04x}",
        "header6": header6,
        "header6_hex": "" if header6 is None else f"0x{header6:02x}",
        "body_length": header.get("body_length"),
        "checksum_valid": header.get("checksum_valid"),
        "checksum_peer_valid": header.get("checksum_excluding_peer_word_valid"),
        "parsed": parsed,
    }


def append_event(output_dir: Path, event_log_name: str, event: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / event_log_name
    with LOG_LOCK:
        with target.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(event, ensure_ascii=False))
            fp.write("\n")


def _metric(key: str, name: str, value: float, *, unit: str | None = None) -> dict[str, Any]:
    return {
        "key": key,
        "name": name,
        "value": value,
        "unit": unit,
        "category": "communication",
    }


def event_to_telemetry_payload(event: dict[str, Any], config: GatewayConfig) -> dict[str, Any] | None:
    event_type = event.get("event_type")
    if event_type == "ds_short_ack" and not config.forward_short_acks:
        return None

    metrics = [
        _metric("estoneii.ds.packet", "eStoneII DS packet", 1),
        _metric("estoneii.ds.reply_size", "eStoneII DS reply size", float(event.get("reply_size") or 0), unit="B"),
    ]
    checksum_valid = event.get("checksum_valid")
    if checksum_valid is not None:
        metrics.append(_metric("estoneii.ds.checksum_valid", "eStoneII DS checksum valid", 1 if checksum_valid else 0))

    if event_type == "ds_get_service_addr":
        metrics.append(_metric("estoneii.ds.get_service_addr", "eStoneII DS service address request", 1))
    elif event_type == "ds_heartbeat":
        metrics.append(_metric("estoneii.ds.heartbeat", "eStoneII DS heartbeat", 1))
    elif event_type == "send_all_comm_state":
        metrics.append(_metric("estoneii.ds.send_all_comm_state", "eStoneII DS send all comm state", 1))
    elif event_type == "ds_short_ack":
        metrics.append(_metric("estoneii.ds.short_ack", "eStoneII DS short ack packet", 1))
    else:
        return None

    return {
        "site_code": config.site_code,
        "site_name": config.site_name,
        "fsu_code": config.fsu_code,
        "fsu_name": config.fsu_name,
        "collected_at": event.get("received_at") or utc_now().isoformat(),
        "metrics": metrics,
    }


def forward_event_to_backend(event: dict[str, Any], config: GatewayConfig, logger: logging.Logger) -> bool:
    if not config.backend_ingest_url:
        return False
    payload = event_to_telemetry_payload(event, config)
    if payload is None:
        return False
    payload_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    for attempt in range(max(config.backend_retry_times, 0) + 1):
        try:
            request = urllib.request.Request(
                config.backend_ingest_url,
                data=payload_bytes,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=config.backend_timeout_seconds) as response:
                status_code = response.getcode()
                body = response.read(200).decode("utf-8", errors="replace")
                if 200 <= status_code < 300:
                    return True
                logger.warning(
                    "backend ingest rejected event=%s status=%s body=%s attempt=%s",
                    event.get("event_type"),
                    status_code,
                    body,
                    attempt + 1,
                )
        except urllib.error.HTTPError as exc:
            body = exc.read(200).decode("utf-8", errors="replace")
            logger.warning(
                "backend ingest rejected event=%s status=%s body=%s attempt=%s",
                event.get("event_type"),
                exc.code,
                body,
                attempt + 1,
            )
        except Exception as exc:
            logger.warning(
                "backend ingest failed event=%s attempt=%s error=%s",
                event.get("event_type"),
                attempt + 1,
                exc,
            )
        if attempt < config.backend_retry_times:
            time.sleep(0.2)
    return False


def bind_udp_sockets(host: str, ports: list[int]) -> list[socket.socket]:
    sockets: list[socket.socket] = []
    for port in ports:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((host, port))
        sock.setblocking(False)
        sockets.append(sock)
    return sockets


def run_gateway(config: GatewayConfig) -> int:
    logger = logging.getLogger("estoneii-ds-gateway")
    reply_args = ReplyArgs(config)
    sockets = bind_udp_sockets(config.host, config.udp_ports)
    backend_pool = (
        ThreadPoolExecutor(max_workers=max(config.backend_worker_count, 1))
        if config.backend_ingest_url
        else None
    )
    packet_count = 0
    event_counts: dict[str, int] = {}

    logger.info(
        "gateway starting: listen=%s ports=%s ds_url=%s output=%s capture_packets=%s",
        config.host,
        ",".join(str(port) for port in config.udp_ports),
        config.ds_url,
        config.output_dir,
        config.capture_packets,
    )

    try:
        deadline = time.monotonic() + config.duration_seconds if config.duration_seconds > 0 else None
        while not STOP_EVENT.is_set():
            if deadline is not None and time.monotonic() >= deadline:
                break
            readable, _, _ = select.select(sockets, [], [], 1.0)
            for sock in readable:
                payload, remote = sock.recvfrom(config.buffer_size)
                local = sock.getsockname()
                decoded = decode_payload(payload)
                reply = build_reply(payload, reply_args) if payload.startswith(b"m~") else None
                if reply is not None:
                    sock.sendto(reply, remote)

                packet_count += 1
                event = classify_packet(payload, decoded, local[1], reply)
                event["remote_ip"] = remote[0]
                event["remote_port"] = remote[1]
                append_event(config.output_dir, config.event_log_name, event)
                forward_queued = False
                if backend_pool is not None and event_to_telemetry_payload(event, config) is not None:
                    backend_pool.submit(forward_event_to_backend, event, config, logger)
                    forward_queued = True
                event_counts[event["event_type"]] = event_counts.get(event["event_type"], 0) + 1

                if config.capture_packets:
                    output_dir = config.output_dir / f"udp-{local[1]}"
                    stem = f"{utc_now_text()}_{remote[0].replace(':', '-')}_{remote[1]}"
                    save_capture(output_dir, stem, payload, decoded, remote, local, reply)

                logger.info(
                    "packet=%s event=%s local=%s remote=%s:%s cmd=%s header6=%s bytes=%s reply=%s backend=%s",
                    packet_count,
                    event["event_type"],
                    local[1],
                    remote[0],
                    remote[1],
                    event["command_hex"],
                    event["header6_hex"],
                    len(payload),
                    0 if reply is None else len(reply),
                    "queued" if forward_queued else "skipped",
                )
    finally:
        for sock in sockets:
            sock.close()
        if backend_pool is not None:
            backend_pool.shutdown(wait=False)
        logger.info("gateway stopped: packets=%s events=%s", packet_count, event_counts)
    return 0


def signal_handler(_signum, _frame) -> None:
    STOP_EVENT.set()


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Production eStoneII DS UDP gateway.")
    parser.add_argument("--host", default=os.getenv("ESTONEII_DS_HOST", "0.0.0.0"))
    parser.add_argument("--udp-ports", default=os.getenv("ESTONEII_DS_UDP_PORTS", "9000,7000"))
    parser.add_argument("--output-dir", default=os.getenv("ESTONEII_DS_OUTPUT_DIR", "logs/estoneii-ds-gateway"))
    parser.add_argument("--event-log-name", default=os.getenv("ESTONEII_DS_EVENT_LOG_NAME", "events.jsonl"))
    parser.add_argument("--capture-packets", action="store_true")
    parser.add_argument(
        "--duration-seconds",
        type=int,
        default=int(os.getenv("ESTONEII_DS_DURATION_SECONDS", "0")),
        help="Stop after N seconds; 0 means run until interrupted.",
    )
    parser.add_argument("--buffer-size", type=int, default=int(os.getenv("ESTONEII_DS_BUFFER_SIZE", "8192")))
    parser.add_argument("--ds-url", default=os.getenv("ESTONEII_DS_URL", "udp://192.168.100.123:9000"))
    parser.add_argument("--ds-service-types", default=os.getenv("ESTONEII_DS_SERVICE_TYPES", "0,5,6,7,8,9"))
    parser.add_argument("--ds-table-status-byte", type=lambda value: int(value, 0), default=0)
    parser.add_argument("--ds-table-length-endian", choices=("little", "big", "none"), default="little")
    parser.add_argument("--ds-table-size-field", choices=("entry-count", "byte-length", "none"), default="entry-count")
    parser.add_argument("--ds-table-include-count", action="store_true")
    parser.add_argument("--backend-ingest-url", default=os.getenv("ESTONEII_DS_BACKEND_INGEST_URL", ""))
    parser.add_argument(
        "--backend-timeout-seconds",
        type=float,
        default=float(os.getenv("ESTONEII_DS_BACKEND_TIMEOUT_SECONDS", "5")),
    )
    parser.add_argument(
        "--backend-retry-times",
        type=int,
        default=int(os.getenv("ESTONEII_DS_BACKEND_RETRY_TIMES", "2")),
    )
    parser.add_argument(
        "--backend-worker-count",
        type=int,
        default=int(os.getenv("ESTONEII_DS_BACKEND_WORKER_COUNT", "2")),
    )
    parser.add_argument(
        "--forward-short-acks",
        action="store_true",
        default=env_bool("ESTONEII_DS_FORWARD_SHORT_ACKS", False),
    )
    parser.add_argument("--site-code", default=os.getenv("ESTONEII_DS_SITE_CODE", "51051243812345"))
    parser.add_argument("--site-name", default=os.getenv("ESTONEII_DS_SITE_NAME", "eStoneII Site"))
    parser.add_argument("--fsu-code", default=os.getenv("ESTONEII_DS_FSU_CODE", "51051243812345"))
    parser.add_argument("--fsu-name", default=os.getenv("ESTONEII_DS_FSU_NAME", "eStoneII FSU"))
    parser.add_argument("--log-level", default=os.getenv("LOG_LEVEL", "INFO"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s [estoneii-ds-gateway] %(message)s",
    )
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    config = GatewayConfig(
        host=args.host,
        udp_ports=parse_int_list(args.udp_ports),
        output_dir=resolve_path(args.output_dir),
        event_log_name=args.event_log_name,
        capture_packets=args.capture_packets,
        duration_seconds=args.duration_seconds,
        buffer_size=args.buffer_size,
        ds_url=args.ds_url,
        ds_service_types=args.ds_service_types,
        ds_table_status_byte=args.ds_table_status_byte,
        ds_table_length_endian=args.ds_table_length_endian,
        ds_table_size_field=args.ds_table_size_field,
        ds_table_include_count=args.ds_table_include_count,
        backend_ingest_url=args.backend_ingest_url,
        backend_timeout_seconds=args.backend_timeout_seconds,
        backend_retry_times=args.backend_retry_times,
        backend_worker_count=args.backend_worker_count,
        forward_short_acks=args.forward_short_acks,
        site_code=args.site_code,
        site_name=args.site_name,
        fsu_code=args.fsu_code,
        fsu_name=args.fsu_name,
    )
    return run_gateway(config)


if __name__ == "__main__":
    sys.exit(main())
