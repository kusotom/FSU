from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


def load_l2tp_module(script_path: Path):
    spec = importlib.util.spec_from_file_location("l2tp_bait", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load {script_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Decode UDP/7000 payloads captured inside L2TP")
    parser.add_argument(
        "path",
        nargs="?",
        default=str(Path(__file__).resolve().parents[1] / "logs" / "l2tp-bait"),
        help="A single .bin file or a directory containing *_recv_*.bin captures",
    )
    parser.add_argument("--limit", type=int, default=0, help="When input is a directory, decode newest N matching files")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


@dataclass
class RunInfo:
    key: tuple[int, int, int]
    start_index: int
    end_index: int
    count: int


def iter_input_files(path: Path, limit: int) -> list[Path]:
    if path.is_file():
        return [path]
    files = sorted(path.glob("*_recv_*.bin"))
    if limit > 0:
        files = files[-limit:]
    return files


def extract_udp7000_payload(l2tp_bait: Any, path: Path) -> dict[str, Any] | None:
    parsed = l2tp_bait.parse_packet(path.read_bytes())
    if not parsed or parsed.ppp_protocol != 0x0021 or not parsed.payload_info or not parsed.payload_bytes:
        return None

    info = parsed.payload_info
    if info.get("protocol") != 17:
        return None
    udp = info.get("udp") or {}
    if udp.get("src_port") != 6001 or udp.get("dst_port") != 7000:
        return None

    ip_header_length = int(info.get("header_length", 0))
    payload = parsed.payload_bytes[4 + ip_header_length + 8 :]
    return {
        "capture_file": str(path),
        "captured_at": path.name.split("_", 1)[0],
        "src_ip": info.get("src_ip"),
        "src_port": udp.get("src_port"),
        "dst_ip": info.get("dst_ip"),
        "dst_port": udp.get("dst_port"),
        "payload": payload,
    }


def decode_payload(payload: bytes) -> dict[str, Any]:
    result: dict[str, Any] = {
        "payload_hex": payload.hex(),
        "payload_length": len(payload),
    }
    if len(payload) < 30:
        result["warning"] = "payload shorter than expected 30-byte sketch"
        return result

    result["frame_head_hex"] = payload[0:2].hex()
    result["msg_seq_or_state_u8"] = payload[2]
    result["fixed_header_hex"] = payload[3:22].hex()
    result["dynamic_word_a_hex"] = payload[22:24].hex()
    result["dynamic_word_a_be"] = int.from_bytes(payload[22:24], "big")
    result["dynamic_word_a_le"] = int.from_bytes(payload[22:24], "little")
    result["reserved_or_flag_hex"] = payload[24:25].hex()
    result["dynamic_word_b_hex"] = payload[25:27].hex()
    result["dynamic_word_b_be"] = int.from_bytes(payload[25:27], "big")
    result["dynamic_word_b_le"] = int.from_bytes(payload[25:27], "little")
    result["tail_marker_hex"] = payload[27:30].hex()
    if len(payload) > 30:
        result["trailing_extra_hex"] = payload[30:].hex()
    return result


def parse_capture_time(value: str) -> datetime:
    return datetime.strptime(value, "%Y%m%dT%H%M%S.%fZ")


def build_runs(records: list[dict[str, Any]]) -> list[RunInfo]:
    runs: list[RunInfo] = []
    for index, record in enumerate(records):
        key = (
            int(record["msg_seq_or_state_u8"]),
            int(record["dynamic_word_a_le"]),
            int(record["dynamic_word_b_le"]),
        )
        if not runs or runs[-1].key != key:
            runs.append(RunInfo(key=key, start_index=index, end_index=index, count=1))
        else:
            runs[-1].end_index = index
            runs[-1].count += 1
    return runs


def annotate_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(records, key=lambda item: item["captured_at"])
    runs = build_runs(ordered)
    run_by_index: dict[int, RunInfo] = {}
    for run in runs:
        for index in range(run.start_index, run.end_index + 1):
            run_by_index[index] = run

    for index, record in enumerate(ordered):
        record["rolling_counter_guess_u8"] = record["msg_seq_or_state_u8"]
        run = run_by_index[index]
        record["burst_repeat_count"] = run.count
        record["burst_position"] = index - run.start_index + 1
        record["burst_role_guess"] = "repeated-burst" if run.count >= 2 else "single-shot"
        record["dynamic_word_a_role_guess"] = "state_or_small_counter_16le"
        record["dynamic_word_b_role_guess"] = "monotonic_counter_16le"

        if index > 0:
            previous = ordered[index - 1]
            delta_seconds = (parse_capture_time(record["captured_at"]) - parse_capture_time(previous["captured_at"])).total_seconds()
            record["delta_from_previous"] = {
                "seconds": round(delta_seconds, 3),
                "seq_u8": int(record["msg_seq_or_state_u8"]) - int(previous["msg_seq_or_state_u8"]),
                "dynamic_word_a_le": int(record["dynamic_word_a_le"]) - int(previous["dynamic_word_a_le"]),
                "dynamic_word_b_le": int(record["dynamic_word_b_le"]) - int(previous["dynamic_word_b_le"]),
            }

    run_summary = []
    for run in runs:
        first = ordered[run.start_index]
        run_summary.append(
            {
                "start_capture": first["captured_at"],
                "count": run.count,
                "seq_u8": run.key[0],
                "dynamic_word_a_le": run.key[1],
                "dynamic_word_b_le": run.key[2],
                "role_guess": "repeated-burst" if run.count >= 2 else "single-shot",
            }
        )

    return {
        "records": ordered,
        "run_summary": run_summary,
        "protocol_guess": {
            "frame_head_hex": "6d7e",
            "msg_seq_or_state_u8": "rolling counter or state byte",
            "fixed_header_hex": "stable header block",
            "dynamic_word_a_le": "small state/counter field",
            "dynamic_word_b_le": "monotonic counter field",
            "tail_marker_hex": "stable tail marker b96900",
            "transport_guess": "private udp heartbeat/status protocol over l2tp",
        },
    }


def render_text(records: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for item in records:
        lines.append(f"capture_file: {item['capture_file']}")
        lines.append(f"captured_at: {item['captured_at']}")
        lines.append(f"flow: {item['src_ip']}:{item['src_port']} -> {item['dst_ip']}:{item['dst_port']}")
        lines.append(f"payload_hex: {item['payload_hex']}")
        if "warning" in item:
            lines.append(f"warning: {item['warning']}")
        else:
            lines.append(f"frame_head_hex: {item['frame_head_hex']}")
            lines.append(f"msg_seq_or_state_u8: {item['msg_seq_or_state_u8']}")
            lines.append(f"rolling_counter_guess_u8: {item.get('rolling_counter_guess_u8', item['msg_seq_or_state_u8'])}")
            lines.append(f"fixed_header_hex: {item['fixed_header_hex']}")
            lines.append(
                f"dynamic_word_a: hex={item['dynamic_word_a_hex']} be={item['dynamic_word_a_be']} le={item['dynamic_word_a_le']}"
            )
            lines.append(f"dynamic_word_a_role_guess: {item.get('dynamic_word_a_role_guess', '')}")
            lines.append(f"reserved_or_flag_hex: {item['reserved_or_flag_hex']}")
            lines.append(
                f"dynamic_word_b: hex={item['dynamic_word_b_hex']} be={item['dynamic_word_b_be']} le={item['dynamic_word_b_le']}"
            )
            lines.append(f"dynamic_word_b_role_guess: {item.get('dynamic_word_b_role_guess', '')}")
            lines.append(f"tail_marker_hex: {item['tail_marker_hex']}")
            lines.append(
                f"burst_role_guess: {item.get('burst_role_guess', '')} "
                f"burst_position={item.get('burst_position', 1)}/{item.get('burst_repeat_count', 1)}"
            )
            if "delta_from_previous" in item:
                delta = item["delta_from_previous"]
                lines.append(
                    f"delta_from_previous: dt={delta['seconds']}s seq={delta['seq_u8']} "
                    f"a_le={delta['dynamic_word_a_le']} b_le={delta['dynamic_word_b_le']}"
                )
            if "trailing_extra_hex" in item:
                lines.append(f"trailing_extra_hex: {item['trailing_extra_hex']}")
        lines.append("")
    return "\n".join(lines).rstrip()


def main() -> None:
    args = parse_args()
    target = Path(args.path)
    l2tp_bait = load_l2tp_module(Path(__file__).resolve().parent / "l2tp_bait.py")
    records = []
    for file_path in iter_input_files(target, args.limit):
        extracted = extract_udp7000_payload(l2tp_bait, file_path)
        if extracted is None:
            continue
        decoded = decode_payload(extracted["payload"])
        records.append(
            {
                "capture_file": extracted["capture_file"],
                "captured_at": extracted["captured_at"],
                "src_ip": extracted["src_ip"],
                "src_port": extracted["src_port"],
                "dst_ip": extracted["dst_ip"],
                "dst_port": extracted["dst_port"],
                **decoded,
            }
        )

    annotated = annotate_records(records)

    stdout = getattr(sys.stdout, "buffer", None)
    output = json.dumps(annotated, ensure_ascii=False, indent=2) if args.json else render_text(annotated["records"])
    if stdout is not None:
        stdout.write((output + "\n").encode("utf-8", errors="backslashreplace"))
    else:
        print(output)


if __name__ == "__main__":
    main()
