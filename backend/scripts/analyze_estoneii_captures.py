from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ds_udp9000_responder import decode_payload


@dataclass(frozen=True)
class CaptureRow:
    path: Path
    local_port: int | None
    remote_port: int | None
    size: int
    sequence: int | None
    command_id: int | None
    header6: int | None
    body_length: int | None
    checksum_valid: bool | None
    checksum_peer_valid: bool | None
    reply_size: int | None
    variant: str


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def parse_port_from_parent(path: Path) -> int | None:
    name = path.parent.name
    if not name.startswith("udp-"):
        return None
    try:
        return int(name.split("-", 1)[1])
    except ValueError:
        return None


def parse_remote_port(path: Path) -> int | None:
    try:
        return int(path.stem.rsplit("_", 1)[1])
    except (IndexError, ValueError):
        return None


def row_from_bin(path: Path) -> CaptureRow:
    payload = path.read_bytes()
    decoded = decode_payload(payload)
    header = decoded.get("header") or {}
    summary = decoded.get("summary") or {}
    meta = read_json(path.with_suffix(".json"))
    return CaptureRow(
        path=path,
        local_port=parse_port_from_parent(path),
        remote_port=parse_remote_port(path),
        size=len(payload),
        sequence=header.get("sequence"),
        command_id=header.get("command_id"),
        header6=payload[6] if len(payload) > 6 else None,
        body_length=header.get("body_length"),
        checksum_valid=header.get("checksum_valid"),
        checksum_peer_valid=header.get("checksum_excluding_peer_word_valid"),
        reply_size=meta.get("reply_size"),
        variant=summary.get("packet_variant") or "unknown",
    )


def format_hex(value: int | None) -> str:
    return "--" if value is None else f"0x{value:02x}"


def format_command(value: int | None) -> str:
    return "--" if value is None else f"0x{value:04x}"


def print_group_counts(rows: list[CaptureRow]) -> None:
    groups: Counter[tuple[int | None, int | None, int | None, int, int | None, int | None]] = Counter()
    for row in rows:
        groups[(row.local_port, row.remote_port, row.command_id, row.size, row.header6, row.reply_size)] += 1

    print("Grouped captures:")
    print("count local remote command header6 size reply")
    for key, count in sorted(groups.items(), key=lambda item: (item[0][0] or 0, item[0][1] or 0, item[0][2] or 0, item[0][3], item[0][4] or 0)):
        local_port, remote_port, command_id, size, header6, reply_size = key
        reply_text = "--" if reply_size is None else str(reply_size)
        print(
            f"{count:5d} {local_port or 0:5d} {remote_port or 0:6d} "
            f"{format_command(command_id):>8} {format_hex(header6):>7} {size:4d} {reply_text:>5}"
        )


def print_timeline(rows: list[CaptureRow], *, limit: int) -> None:
    print()
    print(f"Timeline first/last {limit}:")
    selected = rows[:limit]
    if len(rows) > limit:
        selected += rows[-limit:]
    seen: set[Path] = set()
    print("time local remote command header6 size seq checksum reply file")
    for row in selected:
        if row.path in seen:
            continue
        seen.add(row.path)
        checksum = "ok" if row.checksum_valid else ("peer" if row.checksum_peer_valid else "bad")
        reply_text = "--" if row.reply_size is None else str(row.reply_size)
        print(
            f"{row.path.stem[:22]} {row.local_port or 0:5d} {row.remote_port or 0:6d} "
            f"{format_command(row.command_id):>8} {format_hex(row.header6):>7} {row.size:4d} "
            f"{row.sequence if row.sequence is not None else '--':>3} {checksum:>8} {reply_text:>5} {row.path.name}"
        )


def print_candidates(rows: list[CaptureRow], *, min_size: int) -> None:
    candidates = [row for row in rows if row.size >= min_size]
    print()
    print(f"Large/business candidates >= {min_size} bytes: {len(candidates)}")
    for row in candidates[:50]:
        print(
            f"{row.path} local={row.local_port} remote={row.remote_port} "
            f"cmd={format_command(row.command_id)} header6={format_hex(row.header6)} "
            f"size={row.size} reply={row.reply_size}"
        )


def print_by_header6(rows: list[CaptureRow]) -> None:
    by_header: dict[int | None, Counter[tuple[int | None, int]]] = defaultdict(Counter)
    for row in rows:
        by_header[row.header6][(row.command_id, row.size)] += 1

    print()
    print("By header offset 6:")
    for header6, counter in sorted(by_header.items(), key=lambda item: -1 if item[0] is None else item[0]):
        parts = ", ".join(
            f"{format_command(command)}:{size}x{count}"
            for (command, size), count in sorted(counter.items(), key=lambda item: (item[0][0] or 0, item[0][1]))
        )
        print(f"{format_hex(header6):>7} {parts}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize eStoneII SC lab .bin captures.")
    parser.add_argument("capture_dir", help="Lab output directory or udp-* subdirectory")
    parser.add_argument("--timeline-limit", type=int, default=12)
    parser.add_argument("--large-min-size", type=int, default=64)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.capture_dir)
    rows = [row_from_bin(path) for path in sorted(root.rglob("*.bin"))]
    if not rows:
        print(f"no .bin captures found under {root}")
        return 1

    print(f"captures={len(rows)} root={root}")
    print_group_counts(rows)
    print_by_header6(rows)
    print_timeline(rows, limit=max(0, args.timeline_limit))
    print_candidates(rows, min_size=args.large_min_size)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
