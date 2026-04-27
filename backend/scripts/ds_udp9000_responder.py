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
HEADER_LEN = 24
CHECKSUM_OFFSET = 22
CHECKSUM_END = 24
SERVICE_TYPE_LABELS = {
    0x00: "primary_udp",
    0x01: "secondary_udp",
    0x14: "ftp",
    0xFF: "fallback_udp",
}
COMMAND_LABELS = {
    0x0011: "log_to_ds_or_get_service_addr",
    0x001F: "short_ds_keepalive_or_ack",
    0x8010: "ds_business_state_or_report",
    0x8011: "rds_heartbeat",
    0x801F: "short_ds_keepalive_or_ack_response",
}


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


def checksum16(payload: bytes) -> int:
    if len(payload) < HEADER_LEN:
        return 0
    return sum(payload[2:CHECKSUM_OFFSET] + payload[HEADER_LEN:]) & 0xFFFF


def checksum16_excluding_peer_word(payload: bytes) -> int:
    if len(payload) < HEADER_LEN:
        return 0
    return sum(payload[2:16] + payload[20:CHECKSUM_OFFSET] + payload[HEADER_LEN:]) & 0xFFFF


def parse_service_block(body: bytes) -> dict[str, Any] | None:
    if len(body) < 105:
        return None

    timestamp = int.from_bytes(body[97:101], "little")
    result: dict[str, Any] = {
        "token_a": body[0:32].decode("ascii", errors="replace"),
        "token_separator_hex": body[32:33].hex(),
        "token_b": body[33:65].decode("ascii", errors="replace"),
        "token_b_padding": body[65:97].decode("ascii", errors="replace"),
        "timestamp_unix": timestamp,
        "timestamp_utc": datetime.fromtimestamp(timestamp, timezone.utc).isoformat()
        if timestamp
        else "",
        "address_count": body[101],
        "address_reserved_hex": body[102:104].hex(),
        "addresses": [],
    }

    cursor = 102
    for index in range(result["address_count"]):
        if cursor >= len(body):
            break
        if index == 0 and cursor + 3 <= len(body):
            service_type = body[cursor]
            reserved = body[cursor + 1]
            value_len = body[cursor + 2]
            cursor += 3
        elif cursor + 2 <= len(body):
            service_type = body[cursor]
            reserved = None
            value_len = body[cursor + 1]
            cursor += 2
        else:
            break

        value = body[cursor : cursor + value_len]
        cursor += value_len
        result["addresses"].append(
            {
                "index": index,
                "service_type": service_type,
                "service_type_hex": f"{service_type:02x}",
                "service_type_guess": SERVICE_TYPE_LABELS.get(service_type, "unknown"),
                "reserved": reserved,
                "length": value_len,
                "value": value.decode("ascii", errors="replace"),
            }
        )

    result["remaining_hex"] = body[cursor:].hex()
    return result


def decode_short_body(command_id: int, body: bytes) -> dict[str, Any] | None:
    if command_id != 0x8011 or len(body) != 6:
        return None
    timestamp = int.from_bytes(body[1:5], "little")
    return {
        "kind": "rds_heartbeat",
        "status_or_flag": body[0],
        "timestamp_unix": timestamp,
        "timestamp_local_hint": datetime.fromtimestamp(timestamp).isoformat() if timestamp else "",
        "tail": body[5],
    }


def decode_payload(payload: bytes) -> dict[str, Any]:
    body = payload[HEADER_LEN:] if len(payload) >= HEADER_LEN else b""
    result: dict[str, Any] = {
        "payload_length": len(payload),
        "payload_hex": payload.hex(),
        "magic_hex": payload[:2].hex() if len(payload) >= 2 else payload.hex(),
        "looks_like_ds_udp9000": len(payload) >= 2 and payload[:2] == b"m~",
        "body_length_actual": len(body),
        "ascii_spans": ascii_spans(payload),
        "urls": extract_urls(payload),
    }

    if len(payload) >= HEADER_LEN:
        body_length_field = int.from_bytes(payload[20:22], "little")
        checksum_field = int.from_bytes(payload[22:24], "little")
        computed_checksum = checksum16(payload)
        computed_checksum_excluding_peer_word = checksum16_excluding_peer_word(payload)
        command_id = int.from_bytes(payload[4:6], "little")
        result["header"] = {
            "raw_hex": payload[:HEADER_LEN].hex(),
            "sequence": payload[2],
            "reserved_3": payload[3],
            "command_id": command_id,
            "command_id_hex": payload[4:6].hex(),
            "command_guess": COMMAND_LABELS.get(command_id, "unknown"),
            "fixed_6_19_hex": payload[6:20].hex(),
            "word_3_4_be": int.from_bytes(payload[3:5], "big"),
            "word_3_4_le": int.from_bytes(payload[3:5], "little"),
            "word_5_6_be": int.from_bytes(payload[5:7], "big"),
            "word_5_6_le": int.from_bytes(payload[5:7], "little"),
            "word_12_13_be": int.from_bytes(payload[12:14], "big"),
            "word_12_13_le": int.from_bytes(payload[12:14], "little"),
            "word_20_21_be": int.from_bytes(payload[20:22], "big"),
            "word_20_21_le": int.from_bytes(payload[20:22], "little"),
            "body_length": body_length_field,
            "checksum": checksum_field,
            "checksum_computed": computed_checksum,
            "checksum_valid": checksum_field == computed_checksum,
            "checksum_excluding_peer_word_computed": computed_checksum_excluding_peer_word,
            "checksum_excluding_peer_word_valid": checksum_field == computed_checksum_excluding_peer_word,
        }
        result["body"] = parse_service_block(body)
        result["short_body"] = decode_short_body(command_id, body)
        result["null_strings_after_header"] = split_null_strings(payload, HEADER_LEN)

    url_values = [item["url"] for item in result["urls"]]
    if len(payload) >= HEADER_LEN and payload[:2] == b"m~":
        if payload.find(b"[dhcp]") >= 0:
            packet_variant = "dhcp-address-report"
        elif any("192.168." in value for value in url_values):
            packet_variant = "resolved-address-report"
        else:
            packet_variant = "address-report"
    else:
        packet_variant = "unknown"
    result["summary"] = {
        "type_guess": "ds_udp9000_handshake" if result["looks_like_ds_udp9000"] else "unknown",
        "packet_variant": packet_variant,
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
    if args.reply_mode in {"empty-ack", "empty-ack-next-command"}:
        return build_empty_ack(payload, increment_command=args.reply_mode == "empty-ack-next-command")
    if args.reply_mode == "status-byte-ack":
        return build_framed_reply(payload, bytes([args.reply_status & 0xFF]), args=args)
    if args.reply_mode == "status-u32-ack":
        return build_framed_reply(
            payload,
            int(args.reply_status).to_bytes(4, "little", signed=False),
            args=args,
        )
    if args.reply_mode == "service-list-ack":
        return build_framed_reply(payload, build_service_list_body(args.reply_status, args.sc_url), args=args)
    if args.reply_mode == "ds-address-table-ack":
        return build_framed_reply(
            payload,
            build_ds_address_table_body(
                args.ds_url,
                args.ds_service_types,
                status_byte=args.ds_table_status_byte,
                length_endian=args.ds_table_length_endian,
                size_field=args.ds_table_size_field,
                include_count=args.ds_table_include_count,
            ),
            args=args,
        )
    if args.reply_mode == "ds-session-ack":
        return build_ds_session_ack(payload, args)
    if args.reply_mode == "ds-registration-only-ack":
        return build_ds_registration_only_ack(payload, args)
    if args.reply_mode == "estoneii-ds-ack":
        return build_estoneii_ds_ack(payload, args)
    if args.reply_mode == "ds-toggle-ack":
        return build_ds_toggle_ack(payload, args)
    if args.reply_mode == "ds-toggle-copy-ack":
        return build_ds_toggle_copy_ack(payload, args)
    raise ValueError(f"unsupported reply mode: {args.reply_mode}")


def build_empty_ack(payload: bytes, *, increment_command: bool) -> bytes:
    if len(payload) < HEADER_LEN or payload[:2] != b"m~":
        return b"m~\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"

    reply = bytearray(payload[:HEADER_LEN])
    command_id = int.from_bytes(reply[4:6], "little")
    if increment_command:
        reply[4:6] = ((command_id + 1) & 0xFFFF).to_bytes(2, "little")
    reply[20:22] = (0).to_bytes(2, "little")
    reply[22:24] = (0).to_bytes(2, "little")
    reply[22:24] = checksum16(bytes(reply)).to_bytes(2, "little")
    return bytes(reply)


def build_ds_session_ack(payload: bytes, args: argparse.Namespace) -> bytes | None:
    if len(payload) < HEADER_LEN or payload[:2] != b"m~":
        return None
    command_id = int.from_bytes(payload[4:6], "little")
    if command_id == 0x0011:
        return build_framed_reply(payload, bytes([args.reply_status & 0xFF]), args=args)
    if command_id in {0x001F, 0x8011}:
        return payload
    return build_framed_reply(payload, bytes([args.reply_status & 0xFF]), args=args)


def is_ds_registration_report(payload: bytes) -> bool:
    if len(payload) < HEADER_LEN or payload[:2] != b"m~":
        return False
    command_id = int.from_bytes(payload[4:6], "little")
    body_length = int.from_bytes(payload[20:22], "little")
    return command_id == 0x0011 and body_length >= 100 and len(payload) >= HEADER_LEN + body_length


def build_ds_registration_only_ack(payload: bytes, args: argparse.Namespace) -> bytes | None:
    if not is_ds_registration_report(payload):
        return None
    return build_framed_reply(
        payload,
        build_ds_address_table_body(
            args.ds_url,
            args.ds_service_types,
            status_byte=args.ds_table_status_byte,
            length_endian=args.ds_table_length_endian,
            size_field=args.ds_table_size_field,
            include_count=args.ds_table_include_count,
        ),
        args=args,
    )


def build_estoneii_ds_ack(payload: bytes, args: argparse.Namespace) -> bytes | None:
    if is_ds_registration_report(payload):
        return build_framed_reply(
            payload,
            build_ds_address_table_body(
                args.ds_url,
                args.ds_service_types,
                status_byte=args.ds_table_status_byte,
                length_endian=args.ds_table_length_endian,
                size_field=args.ds_table_size_field,
                include_count=args.ds_table_include_count,
            ),
            command_id=int.from_bytes(payload[4:6], "little") ^ 0x8000,
            args=with_overrides(args, reply_header6=0x47),
        )

    if len(payload) >= HEADER_LEN + 6 and payload[:2] == b"m~":
        command_id = int.from_bytes(payload[4:6], "little")
        body_length = int.from_bytes(payload[20:22], "little")
        if command_id == 0x8011 and body_length == 6:
            timestamp = payload[HEADER_LEN + 1 : HEADER_LEN + 5]
            return build_framed_reply(
                payload,
                timestamp,
                command_id=command_id,
                args=with_overrides(args, reply_header6=0xD3),
            )
        if command_id == 0x8010 and payload[6] == 0x2B:
            return build_short_command_ack(payload)

    return None


def build_short_command_ack(payload: bytes) -> bytes | None:
    if len(payload) < HEADER_LEN or payload[:2] != b"m~":
        return None
    reply = bytearray(payload[:HEADER_LEN])
    reply[4:6] = (0x001F).to_bytes(2, "little")
    reply[20:22] = (0).to_bytes(2, "little")
    reply[22:24] = b"\x00\x00"
    reply[22:24] = checksum16(bytes(reply)).to_bytes(2, "little")
    return bytes(reply)


def with_overrides(args: argparse.Namespace, **overrides: Any) -> argparse.Namespace:
    values = vars(args).copy()
    values.update(overrides)
    return argparse.Namespace(**values)


def build_ds_toggle_ack(payload: bytes, args: argparse.Namespace) -> bytes | None:
    if len(payload) < HEADER_LEN or payload[:2] != b"m~":
        return None
    command_id = int.from_bytes(payload[4:6], "little")
    ack_command_id = command_id ^ 0x8000
    body = bytes([args.reply_status & 0xFF]) if len(payload) > HEADER_LEN else b""
    return build_framed_reply(payload, body, command_id=ack_command_id, args=args)


def build_ds_toggle_copy_ack(payload: bytes, args: argparse.Namespace) -> bytes | None:
    if len(payload) < HEADER_LEN or payload[:2] != b"m~":
        return None
    command_id = int.from_bytes(payload[4:6], "little")
    body = payload[HEADER_LEN:]
    if command_id in {0x0011, 0x8011, 0x001F, 0x801F}:
        return build_framed_reply(payload, body, command_id=command_id ^ 0x8000, args=args)
    return build_framed_reply(payload, body, command_id=command_id ^ 0x8000, args=args)


def resolve_reply_command_id(
    request_command_id: int,
    command_id: int | None,
    command_mode: str,
) -> int:
    if command_id is not None:
        return command_id & 0xFFFF
    if command_mode == "same":
        return request_command_id & 0xFFFF
    if command_mode == "increment":
        return (request_command_id + 1) & 0xFFFF
    if command_mode == "zero":
        return 0
    if command_mode == "xor-high-bit":
        return request_command_id ^ 0x8000
    raise ValueError(f"unsupported reply command mode: {command_mode}")


def apply_reply_header_options(header: bytearray, args: argparse.Namespace | None) -> None:
    if args is None:
        return
    if getattr(args, "reply_seq_delta", 0):
        header[2] = (header[2] + args.reply_seq_delta) & 0xFF
    if getattr(args, "reply_header3", None) is not None:
        header[3] = args.reply_header3 & 0xFF
    if getattr(args, "reply_header6", None) is not None:
        header[6] = args.reply_header6 & 0xFF


def build_framed_reply(
    payload: bytes,
    body: bytes,
    *,
    command_id: int | None = None,
    args: argparse.Namespace | None = None,
) -> bytes:
    if len(payload) < HEADER_LEN or payload[:2] != b"m~":
        header = bytearray(HEADER_LEN)
        header[:2] = b"m~"
        resolved_command_id = resolve_reply_command_id(
            0x0011,
            command_id,
            getattr(args, "reply_command_mode", "same"),
        )
        header[4:6] = resolved_command_id.to_bytes(2, "little")
    else:
        header = bytearray(payload[:HEADER_LEN])
        request_command_id = int.from_bytes(header[4:6], "little")
        resolved_command_id = resolve_reply_command_id(
            request_command_id,
            command_id,
            getattr(args, "reply_command_mode", "same"),
        )
        header[4:6] = resolved_command_id.to_bytes(2, "little")

    apply_reply_header_options(header, args)
    header[20:22] = len(body).to_bytes(2, "little")
    header[22:24] = b"\x00\x00"
    reply = bytes(header) + body
    reply = bytearray(reply)
    reply[22:24] = checksum16(bytes(reply)).to_bytes(2, "little")
    return bytes(reply)


def build_service_list_body(status: int, sc_url: str) -> bytes:
    encoded_url = sc_url.encode("ascii")
    if len(encoded_url) > 255:
        raise ValueError("--sc-url is too long for one-byte length encoding")
    # Experimental DS response shape: status + one service endpoint.
    # The exact device ACK body is still being validated against captures.
    return (
        int(status).to_bytes(4, "little", signed=False)
        + b"\x01"
        + b"\x00"
        + bytes([len(encoded_url)])
        + encoded_url
    )


def build_ds_address_table_body(
    ds_url: str,
    service_types_text: str,
    *,
    status_byte: int = 0,
    length_endian: str = "little",
    size_field: str = "entry-count",
    include_count: bool = False,
) -> bytes:
    encoded_url = ds_url.encode("ascii")
    if len(encoded_url) > 255:
        raise ValueError("--ds-url is too long for one-byte length encoding")
    service_types = [
        int(item.strip(), 0) & 0xFF
        for item in service_types_text.split(",")
        if item.strip()
    ]
    entries = bytearray()
    for service_type in service_types:
        entries.append(service_type)
        entries.append(len(encoded_url))
        entries.extend(encoded_url)
    if len(entries) > 0xFFFF:
        raise ValueError("DS address table body is too large")
    prefix = bytearray([status_byte & 0xFF])
    if size_field == "byte-length" and length_endian != "none":
        prefix.extend(len(entries).to_bytes(2, length_endian))
    elif size_field == "entry-count" and length_endian != "none":
        prefix.extend(len(service_types).to_bytes(2, length_endian))
    elif size_field != "none":
        raise ValueError(f"unsupported DS table size field: {size_field}")
    if include_count:
        if len(service_types) > 255:
            raise ValueError("too many DS service types for one-byte count")
        prefix.append(len(service_types))
    return bytes(prefix) + bytes(entries)


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
            f"variant={summary.get('packet_variant')} "
            f"seq={decoded.get('header', {}).get('sequence')} "
            f"cmd={decoded.get('header', {}).get('command_id')} "
            f"checksum={decoded.get('header', {}).get('checksum_valid')} "
            f"udp_urls={len(summary.get('device_udp_urls', []))} "
            f"ftp_urls={len(summary.get('device_ftp_urls', []))} "
            f"reply={0 if reply is None else len(reply)}"
        )

        if args.verbose:
            for span in decoded.get("ascii_spans", []):
                safe_print(f"  ascii[{span['start']}:{span['end']}] {span['text']}")
            service_body = decoded.get("body") or {}
            if service_body.get("timestamp_utc"):
                safe_print(
                    f"  token_a={service_body.get('token_a')} "
                    f"token_b={service_body.get('token_b')} "
                    f"time={service_body.get('timestamp_utc')}"
                )
            for address in service_body.get("addresses", []):
                safe_print(
                    f"  addr[{address['index']}] type={address['service_type_guess']} "
                    f"len={address['length']} value={address['value']}"
                )

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
        default="none",
        help="Experimental reply mode",
    )
    parser.add_argument("--reply-prefix-size", type=int, default=22)
    parser.add_argument("--reply-text", default="OK")
    parser.add_argument("--reply-hex", default="")
    parser.add_argument("--reply-status", type=int, default=1, help="Status value for status ACK experiments")
    parser.add_argument(
        "--reply-command-mode",
        choices=("same", "increment", "zero", "xor-high-bit"),
        default="same",
        help="How to set the framed reply command id when --reply-mode builds a DS frame",
    )
    parser.add_argument(
        "--reply-seq-delta",
        type=int,
        default=0,
        help="Add this signed delta to the request sequence byte in framed replies",
    )
    parser.add_argument(
        "--reply-header3",
        type=lambda value: int(value, 0),
        default=None,
        help="Override framed reply header byte at offset 3, e.g. 0x01",
    )
    parser.add_argument(
        "--reply-header6",
        type=lambda value: int(value, 0),
        default=None,
        help="Override framed reply header byte at offset 6, e.g. 0x47 for GetServiceAddr ACK",
    )
    parser.add_argument(
        "--sc-url",
        default="http://192.168.100.123:8000/services/SCService",
        help="SC service URL used by service-list-ack experiments",
    )
    parser.add_argument(
        "--ds-url",
        default="udp://192.168.100.123:9000",
        help="DS UDP service URL used by ds-address-table-ack experiments",
    )
    parser.add_argument(
        "--ds-service-types",
        default="0,5,6,7,8,9",
        help="Comma-separated DS service type bytes for ds-address-table-ack",
    )
    parser.add_argument(
        "--ds-table-status-byte",
        type=lambda value: int(value, 0),
        default=0,
        help="Leading status byte for ds-address-table-ack before the address table",
    )
    parser.add_argument(
        "--ds-table-length-endian",
        choices=("little", "big", "none"),
        default="little",
        help="Endian for the two-byte address-table size/count prefix",
    )
    parser.add_argument(
        "--ds-table-size-field",
        choices=("entry-count", "byte-length", "none"),
        default="entry-count",
        help="Meaning of the two-byte field after the status byte in ds-address-table bodies",
    )
    parser.add_argument(
        "--ds-table-include-count",
        action="store_true",
        help="Append a one-byte service count before address-table entries",
    )
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
