from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ds_udp9000_responder import decode_payload


@dataclass(frozen=True)
class EventRow:
    index: int
    received_at: str
    event_type: str
    local_port: int | None
    remote_ip: str
    remote_port: int | None
    command_id: int | None
    header6: int | None
    payload_size: int
    reply_size: int
    sequence: int | None
    checksum_valid: bool | None
    parsed: dict[str, Any]


@dataclass(frozen=True)
class CaptureRow:
    path: Path
    local_port: int | None
    remote_port: int | None
    command_id: int | None
    header6: int | None
    payload_size: int
    body_length: int | None
    checksum_valid: bool | None
    body_hex_sample: str


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def parse_event_line(index: int, line: str) -> EventRow | None:
    line = line.strip()
    if not line:
        return None
    try:
        item = json.loads(line)
    except json.JSONDecodeError:
        return None
    return EventRow(
        index=index,
        received_at=str(item.get("received_at") or ""),
        event_type=str(item.get("event_type") or "unknown"),
        local_port=item.get("local_port"),
        remote_ip=str(item.get("remote_ip") or ""),
        remote_port=item.get("remote_port"),
        command_id=item.get("command_id"),
        header6=item.get("header6"),
        payload_size=int(item.get("payload_size") or 0),
        reply_size=int(item.get("reply_size") or 0),
        sequence=item.get("sequence"),
        checksum_valid=item.get("checksum_valid"),
        parsed=item.get("parsed") if isinstance(item.get("parsed"), dict) else {},
    )


def read_events(path: Path) -> list[EventRow]:
    if not path.exists():
        return []
    rows: list[EventRow] = []
    for index, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
        row = parse_event_line(index, line)
        if row is not None:
            rows.append(row)
    return rows


def parse_port_from_parent(path: Path) -> int | None:
    name = path.parent.name
    if "-" not in name:
        return None
    try:
        return int(name.rsplit("-", 1)[1])
    except ValueError:
        return None


def parse_remote_port(path: Path) -> int | None:
    try:
        return int(path.stem.rsplit("_", 1)[1])
    except (IndexError, ValueError):
        return None


def capture_from_bin(path: Path) -> CaptureRow:
    payload = path.read_bytes()
    decoded = decode_payload(payload)
    header = decoded.get("header") or {}
    body = payload[24:] if len(payload) >= 24 else b""
    return CaptureRow(
        path=path,
        local_port=parse_port_from_parent(path),
        remote_port=parse_remote_port(path),
        command_id=header.get("command_id"),
        header6=payload[6] if len(payload) > 6 else None,
        payload_size=len(payload),
        body_length=header.get("body_length"),
        checksum_valid=header.get("checksum_valid"),
        body_hex_sample=body[:64].hex(),
    )


def read_captures(root: Path) -> list[CaptureRow]:
    return [capture_from_bin(path) for path in sorted(root.rglob("*.bin"))]


def format_hex(value: int | None, width: int = 2) -> str:
    return "--" if value is None else f"0x{value:0{width}x}"


def print_status(root: Path) -> None:
    status = read_json(root / "status.json")
    if not status:
        print("status: missing")
        return
    print("status:")
    print(f"  running={status.get('running')} updated_at={status.get('updated_at')}")
    print(f"  stale_after_seconds={status.get('stale_after_seconds')} packets={status.get('packet_count')}")
    print(f"  event_counts={status.get('event_counts')}")
    print(f"  backend={status.get('backend')}")


def print_event_summary(rows: list[EventRow], *, timeline_limit: int) -> None:
    print()
    print(f"events={len(rows)}")
    if not rows:
        return
    by_type = Counter(row.event_type for row in rows)
    by_shape = Counter((row.event_type, row.local_port, row.remote_port, row.command_id, row.header6, row.payload_size, row.reply_size) for row in rows)
    print("event counts:")
    for event_type, count in by_type.most_common():
        print(f"  {event_type}: {count}")
    print()
    print("event shapes:")
    print("count event local remote command header6 size reply")
    for key, count in sorted(by_shape.items(), key=lambda item: (-item[1], item[0])):
        event_type, local_port, remote_port, command_id, header6, size, reply = key
        print(
            f"{count:5d} {event_type[:28]:28s} {local_port or 0:5d} {remote_port or 0:6d} "
            f"{format_hex(command_id, 4):>8} {format_hex(header6):>7} {size:4d} {reply:5d}"
        )
    print()
    print(f"timeline first/last {timeline_limit}:")
    selected = rows[:timeline_limit]
    if len(rows) > timeline_limit:
        selected += rows[-timeline_limit:]
    seen: set[int] = set()
    print("idx time event local remote command header6 size reply seq checksum")
    for row in selected:
        if row.index in seen:
            continue
        seen.add(row.index)
        checksum = "ok" if row.checksum_valid else ("bad" if row.checksum_valid is False else "--")
        print(
            f"{row.index:4d} {row.received_at[:19]:19s} {row.event_type[:24]:24s} "
            f"{row.local_port or 0:5d} {row.remote_port or 0:6d} "
            f"{format_hex(row.command_id, 4):>8} {format_hex(row.header6):>7} "
            f"{row.payload_size:4d} {row.reply_size:5d} "
            f"{row.sequence if row.sequence is not None else '--':>4} {checksum:>8}"
        )
    print_business_events(rows)


def print_business_events(rows: list[EventRow]) -> None:
    interesting = [
        row
        for row in rows
        if row.event_type in {"send_all_comm_state", "unknown_business_frame", "unknown_ds_frame", "unknown"}
        or row.payload_size >= 51
    ]
    print()
    print(f"business/unknown events: {len(interesting)}")
    if not interesting:
        return
    print("idx time event local remote command header6 size reply parsed")
    for row in interesting[:80]:
        parsed_parts: list[str] = []
        if row.parsed.get("device_timestamp_unix") is not None:
            parsed_parts.append(f"ts={row.parsed.get('device_timestamp_unix')}")
        if row.parsed.get("tail") is not None:
            parsed_parts.append(f"tail={row.parsed.get('tail')}")
        body_hex = row.parsed.get("body_hex") or row.parsed.get("body_hex_sample") or ""
        if body_hex:
            parsed_parts.append(f"body={str(body_hex)[:96]}")
        print(
            f"{row.index:4d} {row.received_at[:19]:19s} {row.event_type[:24]:24s} "
            f"{row.local_port or 0:5d} {row.remote_port or 0:6d} "
            f"{format_hex(row.command_id, 4):>8} {format_hex(row.header6):>7} "
            f"{row.payload_size:4d} {row.reply_size:5d} {' '.join(parsed_parts)}"
        )


def print_capture_summary(rows: list[CaptureRow], *, min_size: int, show_hex: bool) -> None:
    print()
    print(f"captures={len(rows)}")
    if not rows:
        return
    by_shape = Counter((row.local_port, row.remote_port, row.command_id, row.header6, row.payload_size, row.body_length) for row in rows)
    print("capture shapes:")
    print("count local remote command header6 size body_len")
    for key, count in sorted(by_shape.items(), key=lambda item: (-item[1], item[0])):
        local_port, remote_port, command_id, header6, size, body_length = key
        print(
            f"{count:5d} {local_port or 0:5d} {remote_port or 0:6d} "
            f"{format_hex(command_id, 4):>8} {format_hex(header6):>7} {size:4d} {body_length or 0:8d}"
        )
    candidates = [row for row in rows if row.payload_size >= min_size]
    print()
    print(f"business candidates >= {min_size} bytes: {len(candidates)}")
    for row in candidates[:80]:
        suffix = f" body={row.body_hex_sample}" if show_hex else ""
        print(
            f"{row.path} local={row.local_port} remote={row.remote_port} "
            f"cmd={format_hex(row.command_id, 4)} header6={format_hex(row.header6)} "
            f"size={row.payload_size} body_len={row.body_length}{suffix}"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize eStoneII DS gateway events and unknown captures.")
    parser.add_argument("gateway_dir", help="Gateway output directory containing events.jsonl/status.json")
    parser.add_argument("--event-log-name", default="events.jsonl")
    parser.add_argument("--timeline-limit", type=int, default=12)
    parser.add_argument("--large-min-size", type=int, default=31)
    parser.add_argument("--show-hex", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.gateway_dir)
    if not root.exists():
        print(f"gateway directory does not exist: {root}")
        return 1
    print(f"root={root}")
    print_status(root)
    print_event_summary(read_events(root / args.event_log_name), timeline_limit=max(args.timeline_limit, 0))
    print_capture_summary(read_captures(root), min_size=args.large_min_size, show_hex=args.show_hex)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
