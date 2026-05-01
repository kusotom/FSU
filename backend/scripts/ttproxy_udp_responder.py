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
    parser = argparse.ArgumentParser(description="Capture tt_proxy UDP/10378 and optionally send experimental replies")
    parser.add_argument("--host", default="0.0.0.0", help="Host/IP to bind")
    parser.add_argument("--port", type=int, default=10378, help="UDP port to bind")
    parser.add_argument(
        "--output-dir",
        default=str(Path(__file__).resolve().parents[1] / "logs" / "ttproxy-udp-reply"),
        help="Directory for captured packets",
    )
    parser.add_argument("--buffer-size", type=int, default=8192, help="Receive buffer size")
    parser.add_argument("--limit", type=int, default=0, help="Stop after capturing N packets, 0 means forever")
    parser.add_argument(
        "--reply-mode",
        choices=("none", "echo", "text", "header-text"),
        default="none",
        help="Experimental reply mode",
    )
    parser.add_argument(
        "--reply-text",
        default="60",
        help="Reply text used by text/header-text modes, encoded as GB18030",
    )
    return parser.parse_args()


def build_reply(payload: bytes, mode: str, reply_text: str) -> bytes | None:
    if mode == "none":
        return None
    if mode == "echo":
        return payload

    text_bytes = reply_text.encode("gb18030", errors="replace")
    if mode == "text":
        return text_bytes
    if mode == "header-text":
        if len(payload) >= 15 and payload[:2] == b"\x7e\x3e":
            return payload[:15] + text_bytes
        return text_bytes
    raise ValueError(f"unsupported reply mode: {mode}")


def build_meta(
    remote: tuple[str, int],
    local: tuple[str, int],
    payload: bytes,
    decoded: dict[str, Any] | None,
    reply_payload: bytes | None,
) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "received_at": utc_now().isoformat(),
        "remote_ip": remote[0],
        "remote_port": remote[1],
        "local_ip": local[0],
        "local_port": local[1],
        "payload_size": len(payload),
        "payload_hex": payload.hex(),
        "reply_size": 0 if reply_payload is None else len(reply_payload),
        "reply_hex": "" if reply_payload is None else reply_payload.hex(),
    }
    if decoded is not None:
        meta["decoded_summary"] = {
            "message_code": decoded.get("message_code"),
            "message_type_guess": decoded.get("message_type_guess"),
            "message_body": decoded.get("message_body"),
            "register_summary": decoded.get("register_summary"),
        }
    return meta


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    decoder = load_decoder()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((args.host, args.port))

    print(f"tt_proxy UDP responder listening on {args.host}:{args.port}")
    print(f"output_dir={output_dir}")
    print(f"reply_mode={args.reply_mode} reply_text={args.reply_text!r}")

    count = 0
    while True:
        payload, remote = sock.recvfrom(args.buffer_size)
        local = sock.getsockname()
        stamp = utc_now_text()
        stem = f"{stamp}_{remote[0].replace(':', '-')}_{remote[1]}"

        decoded = decoder.decode_payload(payload)
        reply_payload = build_reply(payload, args.reply_mode, args.reply_text)
        if reply_payload is not None:
            sock.sendto(reply_payload, remote)

        meta = build_meta(remote, local, payload, decoded, reply_payload)
        (output_dir / f"{stem}.bin").write_bytes(payload)
        (output_dir / f"{stem}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        (output_dir / f"{stem}.decoded.json").write_text(
            json.dumps(decoded, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        count += 1
        print(
            f"[{count}] {remote[0]}:{remote[1]} -> {local[0]}:{local[1]} "
            f"{len(payload)} bytes type={decoded.get('message_type_guess')} reply={args.reply_mode}"
        )
        if args.limit > 0 and count >= args.limit:
            break


if __name__ == "__main__":
    main()
