from __future__ import annotations

import argparse
import select
import socket
import time
from argparse import Namespace
from pathlib import Path
from typing import Any

from ds_udp9000_responder import build_reply, decode_payload, safe_print, save_capture, utc_now_text
from sc_b_interface_honeypot import CaptureStore, HoneypotConfig, start_http_server


def make_honeypot_config(host: str, port: int, output_dir: Path) -> HoneypotConfig:
    return HoneypotConfig(
        host=host,
        http_port=port,
        ftp_port=0,
        tcp_port=0,
        output_dir=output_dir,
        ftp_user="anonymous",
        ftp_password="anonymous",
        http_enabled=True,
        ftp_enabled=False,
        tcp_enabled=False,
        poll_target_url="",
        poll_interval_seconds=300,
        poll_timeout_seconds=10,
        poll_enabled=False,
        poll_get_fsuinfo_body="",
        poll_get_data_body="",
    )


def start_http_ports(host: str, ports: list[int], output_root: Path) -> list[Any]:
    servers: list[Any] = []
    for port in ports:
        config = make_honeypot_config(host, port, output_root / f"sc-http-{port}")
        store = CaptureStore(config.output_dir)
        server, _thread = start_http_server(config, store)
        servers.append(server)
        safe_print(f"HTTP SCService listening on {host}:{port}, output={config.output_dir}")
    return servers


def run_udp_responders(args: argparse.Namespace, output_root: Path) -> int:
    udp_args = Namespace(
        reply_mode=args.reply_mode,
        reply_prefix_size=args.reply_prefix_size,
        reply_text=args.reply_text,
        reply_hex=args.reply_hex,
        reply_status=args.reply_status,
        reply_command_mode=args.reply_command_mode,
        reply_seq_delta=args.reply_seq_delta,
        reply_header3=args.reply_header3,
        reply_header6=args.reply_header6,
        sc_url=args.sc_url,
        ds_url=args.ds_url,
        ds_service_types=args.ds_service_types,
        ds_table_status_byte=args.ds_table_status_byte,
        ds_table_length_endian=args.ds_table_length_endian,
        ds_table_size_field=args.ds_table_size_field,
        ds_table_include_count=args.ds_table_include_count,
    )
    ports = parse_int_list(args.udp_ports or str(args.udp_port))
    sockets: list[socket.socket] = []
    for port in ports:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind((args.host, port))
        sock.setblocking(False)
        sockets.append(sock)
        safe_print(f"UDP responder listening on {args.host}:{port}, reply_mode={args.reply_mode}")

    deadline = time.monotonic() + args.duration
    count = 0
    while time.monotonic() < deadline:
        readable, _, _ = select.select(sockets, [], [], 1.0)
        if not readable:
            continue

        for sock in readable:
            payload, remote = sock.recvfrom(args.buffer_size)
            local = sock.getsockname()
            decoded = decode_payload(payload)
            reply = build_reply(payload, udp_args) if payload.startswith(b"m~") else None
            if reply is not None:
                sock.sendto(reply, remote)

            count += 1
            output_dir = output_root / f"udp-{local[1]}"
            stem = f"{utc_now_text()}_{remote[0].replace(':', '-')}_{remote[1]}"
            save_capture(output_dir, stem, payload, decoded, remote, local, reply)
            summary = decoded.get("summary", {})
            safe_print(
                f"[udp {count}] local={local[1]} {remote[0]}:{remote[1]} {len(payload)} bytes "
                f"variant={summary.get('packet_variant')} "
                f"seq={decoded.get('header', {}).get('sequence')} "
                f"cmd={decoded.get('header', {}).get('command_id')} "
                f"checksum={decoded.get('header', {}).get('checksum_valid')} "
                f"reply={0 if reply is None else len(reply)}"
            )

    for sock in sockets:
        sock.close()
    return count


def parse_int_list(text: str) -> list[int]:
    return [int(item.strip()) for item in text.split(",") if item.strip()]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run an eStoneII DS UDP + SC HTTP lab responder.")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--udp-port", type=int, default=9000)
    parser.add_argument("--udp-ports", default="", help="Comma-separated UDP ports; overrides --udp-port")
    parser.add_argument("--http-ports", default="80,8000", help="Comma-separated HTTP ports")
    parser.add_argument("--duration", type=int, default=90)
    parser.add_argument("--buffer-size", type=int, default=8192)
    parser.add_argument("--output-dir", default=str(Path(__file__).resolve().parents[1] / "logs" / "estoneii-sc-lab"))
    parser.add_argument(
        "--reply-mode",
        choices=(
            "none",
            "echo",
            "prefix",
            "text",
            "custom-hex",
            "empty-ack",
            "empty-ack-next-command",
            "status-byte-ack",
            "status-u32-ack",
            "service-list-ack",
            "ds-address-table-ack",
            "ds-session-ack",
            "ds-registration-only-ack",
            "estoneii-ds-ack",
            "ds-toggle-ack",
            "ds-toggle-copy-ack",
        ),
        default="empty-ack",
    )
    parser.add_argument("--reply-prefix-size", type=int, default=22)
    parser.add_argument("--reply-text", default="OK")
    parser.add_argument("--reply-hex", default="")
    parser.add_argument("--reply-status", type=int, default=1)
    parser.add_argument("--reply-command-mode", choices=("same", "increment", "zero", "xor-high-bit"), default="same")
    parser.add_argument("--reply-seq-delta", type=int, default=0)
    parser.add_argument("--reply-header3", type=lambda value: int(value, 0), default=None)
    parser.add_argument("--reply-header6", type=lambda value: int(value, 0), default=None)
    parser.add_argument("--sc-url", default="http://192.168.100.123:80/services/SCService")
    parser.add_argument("--ds-url", default="udp://192.168.100.123:9000")
    parser.add_argument("--ds-service-types", default="0,5,6,7,8,9")
    parser.add_argument("--ds-table-status-byte", type=lambda value: int(value, 0), default=0)
    parser.add_argument("--ds-table-length-endian", choices=("little", "big", "none"), default="little")
    parser.add_argument("--ds-table-size-field", choices=("entry-count", "byte-length", "none"), default="entry-count")
    parser.add_argument("--ds-table-include-count", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_root = Path(args.output_dir)
    output_root.mkdir(parents=True, exist_ok=True)
    ports = parse_int_list(args.http_ports)
    servers = start_http_ports(args.host, ports, output_root)
    try:
        packets = run_udp_responders(args, output_root)
        safe_print(f"finished: udp_packets={packets}, output={output_root}")
    finally:
        for server in servers:
            server.shutdown()
            server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
