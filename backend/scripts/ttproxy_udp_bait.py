from __future__ import annotations

import argparse
import json
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_now_text() -> str:
    return utc_now().strftime("%Y%m%dT%H%M%S.%fZ")


def load_decoder() -> Any:
    script_dir = Path(__file__).resolve().parent
    sys.path.insert(0, str(script_dir))
    import decode_ttproxy_udp10378

    return decode_ttproxy_udp10378


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture tt_proxy UDP/10378 packets and decode them")
    parser.add_argument("--host", default="0.0.0.0", help="Host/IP to bind")
    parser.add_argument("--port", type=int, default=10378, help="UDP port to bind")
    parser.add_argument(
        "--output-dir",
        default=str(Path(__file__).resolve().parents[1] / "logs" / "ttproxy-udp"),
        help="Directory for captured packets",
    )
    parser.add_argument("--buffer-size", type=int, default=8192, help="Receive buffer size")
    parser.add_argument("--limit", type=int, default=0, help="Stop after capturing N packets, 0 means forever")
    parser.add_argument("--decode", action="store_true", help="Decode each packet with decode_ttproxy_udp10378.py")
    return parser.parse_args()


def decode_payload(payload: bytes) -> dict[str, Any]:
    decoder = load_decoder()
    return decoder.decode_payload(payload)


def build_meta(remote: tuple[str, int], local: tuple[str, int], payload: bytes, decoded: dict[str, Any] | None) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "received_at": utc_now().isoformat(),
        "remote_ip": remote[0],
        "remote_port": remote[1],
        "local_ip": local[0],
        "local_port": local[1],
        "payload_size": len(payload),
        "payload_hex": payload.hex(),
    }
    if decoded is not None:
        meta["decoded_summary"] = {
            "magic_found": decoded.get("magic_found"),
            "message_code": decoded.get("message_code"),
            "message_code_name": decoded.get("message_code_name"),
            "message_type_guess": decoded.get("message_type_guess"),
            "message_body": decoded.get("message_body"),
        }
    return meta


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((args.host, args.port))

    print(f"tt_proxy UDP bait listening on {args.host}:{args.port}")
    print(f"output_dir={output_dir}")
    print(f"decode_enabled={args.decode}")

    count = 0
    while True:
        payload, remote = sock.recvfrom(args.buffer_size)
        local = sock.getsockname()
        stamp = utc_now_text()
        stem = f"{stamp}_{remote[0].replace(':', '-')}_{remote[1]}"

        bin_path = output_dir / f"{stem}.bin"
        json_path = output_dir / f"{stem}.json"
        decoded_path = output_dir / f"{stem}.decoded.json"

        decoded = decode_payload(payload) if args.decode else None
        meta = build_meta(remote, local, payload, decoded)

        bin_path.write_bytes(payload)
        json_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        if decoded is not None:
            decoded_path.write_text(json.dumps(decoded, ensure_ascii=False, indent=2), encoding="utf-8")

        count += 1
        summary = decoded.get("message_type_guess") if decoded else "raw"
        print(f"[{count}] {remote[0]}:{remote[1]} -> {local[0]}:{local[1]} {len(payload)} bytes type={summary}")

        if args.limit > 0 and count >= args.limit:
            break


if __name__ == "__main__":
    main()
