from __future__ import annotations

import argparse
import json
import re
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ASCII_RE = re.compile(rb"[ -~]{4,}")
URL_RE = re.compile(rb"(?:udp|ftp)://[ -~]+")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_now_text() -> str:
    return utc_now().strftime("%Y%m%dT%H%M%S.%fZ")


def safe_print(text: str) -> None:
    encoding = sys.stdout.encoding or "utf-8"
    data = text.encode(encoding, errors="backslashreplace")
    print(data.decode(encoding, errors="replace"), flush=True)


def ascii_spans(payload: bytes) -> list[dict[str, Any]]:
    spans: list[dict[str, Any]] = []
    for match in ASCII_RE.finditer(payload):
        raw = match.group()
        spans.append(
            {
                "start": match.start(),
                "end": match.end(),
                "text": raw.decode("ascii", errors="replace"),
            }
        )
    return spans


def extract_urls(payload: bytes) -> list[dict[str, Any]]:
    urls: list[dict[str, Any]] = []
    for match in URL_RE.finditer(payload):
        raw = match.group().rstrip(b"\x00")
        text = raw.decode("ascii", errors="replace")
        urls.append(
            {
                "start": match.start(),
                "end": match.start() + len(raw),
                "url": text,
            }
        )
    return urls


def split_null_strings(payload: bytes, offset: int = 22) -> list[dict[str, Any]]:
    parts: list[dict[str, Any]] = []
    index = offset
    while index < len(payload):
        next_zero = payload.find(b"\x00", index)
        if next_zero < 0:
            chunk = payload[index:]
            end = len(payload)
        else:
            chunk = payload[index:next_zero]
            end = next_zero
        if chunk and all(32 <= b < 127 for b in chunk):
            parts.append(
                {
                    "start": index,
                    "end": end,
                    "text": chunk.decode("ascii", errors="replace"),
                }
            )
        if next_zero < 0:
            break
        index = next_zero + 1
    return parts


def decode_payload(payload: bytes) -> dict[str, Any]:
    result: dict[str, Any] = {
        "payload_length": len(payload),
        "payload_hex": payload.hex(),
        "magic_hex": payload[:2].hex() if len(payload) >= 2 else payload.hex(),
        "looks_like_ds_udp9000": len(payload) >= 2 and payload[:2] == b"m~",
        "ascii_spans": ascii_spans(payload),
        "urls": extract_urls(payload),
    }

    if len(payload) >= 22:
        result["header"] = {
            "raw_hex": payload[:22].hex(),
            "byte_2": payload[2],
            "word_3_4_be": int.from_bytes(payload[3:5], "big"),
            "word_3_4_le": int.from_bytes(payload[3:5], "little"),
            "word_5_6_be": int.from_bytes(payload[5:7], "big"),
            "word_5_6_le": int.from_bytes(payload[5:7], "little"),
            "word_12_13_be": int.from_bytes(payload[12:14], "big"),
            "word_12_13_le": int.from_bytes(payload[12:14], "little"),
            "word_20_21_be": int.from_bytes(payload[20:22], "big"),
            "word_20_21_le": int.from_bytes(payload[20:22], "little"),
        }
        result["null_strings_after_header"] = split_null_strings(payload, 22)

    url_values = [item["url"] for item in result["urls"]]
    result["summary"] = {
        "type_guess": "ds_udp9000_handshake" if result["looks_like_ds_udp9000"] else "unknown",
        "device_udp_urls": [value for value in url_values if value.startswith("udp://")],
        "device_ftp_urls": [value for value in url_values if value.startswith("ftp://")],
    }
    return result


def build_reply(payload: bytes, args: argparse.Namespace) -> bytes | None:
    if args.reply_mode == "none":
        return None
    if args.reply_mode == "echo":
        return payload
    if args.reply_mode == "prefix":
        return payload[: max(0, args.reply_prefix_size)]
    if args.reply_mode == "text":
        return args.reply_text.encode("utf-8")
    if args.reply_mode == "custom-hex":
        if not args.reply_hex:
            raise ValueError("--reply-hex is required for custom-hex mode")
        return bytes.fromhex(args.reply_hex.replace(" ", ""))
    raise ValueError(f"unsupported reply mode: {args.reply_mode}")


def save_capture(
    output_dir: Path,
    stem: str,
    payload: bytes,
    decoded: dict[str, Any],
    remote: tuple[str, int],
    local: tuple[str, int],
    reply: bytes | None,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / f"{stem}.bin").write_bytes(payload)
    (output_dir / f"{stem}.decoded.json").write_text(
        json.dumps(decoded, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    meta = {
        "received_at": utc_now().isoformat(),
        "remote_ip": remote[0],
        "remote_port": remote[1],
        "local_ip": local[0],
        "local_port": local[1],
        "payload_size": len(payload),
        "payload_hex": payload.hex(),
        "reply_size": 0 if reply is None else len(reply),
        "reply_hex": "" if reply is None else reply.hex(),
        "decoded_summary": decoded.get("summary"),
    }
    (output_dir / f"{stem}.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def run_server(args: argparse.Namespace) -> int:
    output_dir = Path(args.output_dir)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((args.host, args.port))

    safe_print(f"DS UDP/9000 responder listening on {args.host}:{args.port}")
    safe_print(f"output_dir={output_dir}")
    safe_print(f"reply_mode={args.reply_mode}")

    count = 0
    while True:
        payload, remote = sock.recvfrom(args.buffer_size)
        local = sock.getsockname()
        decoded = decode_payload(payload)
        reply = build_reply(payload, args)
        if reply is not None:
            sock.sendto(reply, remote)

        count += 1
        stem = f"{utc_now_text()}_{remote[0].replace(':', '-')}_{remote[1]}"
        save_capture(output_dir, stem, payload, decoded, remote, local, reply)
        summary = decoded.get("summary", {})
        safe_print(
            f"[{count}] {remote[0]}:{remote[1]} -> {local[0]}:{local[1]} "
            f"{len(payload)} bytes type={summary.get('type_guess')} "
            f"udp_urls={len(summary.get('device_udp_urls', []))} "
            f"ftp_urls={len(summary.get('device_ftp_urls', []))} "
            f"reply={0 if reply is None else len(reply)}"
        )

        if args.verbose:
            for span in decoded.get("ascii_spans", []):
                safe_print(f"  ascii[{span['start']}:{span['end']}] {span['text']}")

        if args.limit > 0 and count >= args.limit:
            break
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Capture and experiment with eStoneII SiteUnit DS UDP/9000 handshakes."
    )
    parser.add_argument("--host", default="0.0.0.0", help="Host/IP to bind")
    parser.add_argument("--port", type=int, default=9000, help="UDP port to bind")
    parser.add_argument(
        "--output-dir",
        default=str(Path(__file__).resolve().parents[1] / "logs" / "ds-udp9000"),
        help="Directory for captured packets",
    )
    parser.add_argument("--buffer-size", type=int, default=8192)
    parser.add_argument("--limit", type=int, default=0, help="Stop after N packets; 0 means forever")
    parser.add_argument("--verbose", action="store_true", help="Print decoded ASCII spans")
    parser.add_argument(
        "--decode-file",
        help="Decode a captured UDP payload .bin file and exit",
    )
    parser.add_argument(
        "--reply-mode",
        choices=("none", "echo", "prefix", "text", "custom-hex"),
        default="none",
        help="Experimental reply mode",
    )
    parser.add_argument("--reply-prefix-size", type=int, default=22)
    parser.add_argument("--reply-text", default="OK")
    parser.add_argument("--reply-hex", default="")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.decode_file:
        payload = Path(args.decode_file).read_bytes()
        print(json.dumps(decode_payload(payload), ensure_ascii=False, indent=2))
        return
    raise SystemExit(run_server(args))


if __name__ == "__main__":
    main()
