from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


HTTP_METHODS = (b"GET ", b"POST ", b"PUT ", b"DELETE ", b"HEAD ", b"OPTIONS ", b"PATCH ")


@dataclass
class TcpStream:
    src_ip: str
    src_port: int
    dst_ip: str
    dst_port: int
    next_sequence: int | None = None
    assembled: bytearray = field(default_factory=bytearray)
    pending: dict[int, bytes] = field(default_factory=dict)
    packets: int = 0
    bytes_seen: int = 0


@dataclass
class UdpFlow:
    src_ip: str
    src_port: int
    dst_ip: str
    dst_port: int
    packets: int = 0
    total_payload_bytes: int = 0
    unique_payloads: dict[str, dict[str, Any]] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)


CRC16_VARIANTS = {
    "crc16_ibm": (0xA001, 0xFFFF, True),
    "crc16_modbus": (0xA001, 0xFFFF, True),
    "crc16_ccitt_false": (0x1021, 0xFFFF, False),
    "crc16_xmodem": (0x1021, 0x0000, False),
}


def load_l2tp_module(script_path: Path):
    spec = importlib.util.spec_from_file_location("l2tp_bait", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load {script_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze captured L2TP PPP/IP sessions")
    parser.add_argument(
        "log_dir",
        nargs="?",
        default=str(Path(__file__).resolve().parents[1] / "logs" / "l2tp-bait"),
    )
    parser.add_argument("--limit", type=int, default=0, help="Only analyze the newest N recv .bin files")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--save-json", default="")
    return parser.parse_args()


def iter_capture_files(log_dir: Path, limit: int) -> list[Path]:
    files = sorted(log_dir.glob("*_recv_*.bin"))
    if limit > 0:
        files = files[-limit:]
    return files


def classify_payload(payload: bytes) -> dict[str, Any]:
    preview = payload[:256]
    text_preview = preview.decode("utf-8", errors="replace")
    lowered = preview.lower()
    result: dict[str, Any] = {
        "size": len(payload),
        "preview_text": text_preview,
        "preview_hex": preview.hex(),
    }
    if any(preview.startswith(method) for method in HTTP_METHODS):
        result["kind"] = "http-request"
    elif lowered.startswith(b"http/1."):
        result["kind"] = "http-response"
    elif b"<?xml" in lowered or b"<request" in lowered or b"<response" in lowered:
        result["kind"] = "xml"
    elif preview and all(32 <= b < 127 or b in {9, 10, 13} for b in preview[:64]):
        result["kind"] = "text"
    else:
        result["kind"] = "binary"
    return result


def payload_signature(payload: bytes) -> str:
    return payload.hex()


def payload_preview(payload: bytes, limit: int = 128) -> dict[str, Any]:
    sample = payload[:limit]
    return {
        "size": len(payload),
        "preview_hex": sample.hex(),
        "preview_text": sample.decode("utf-8", errors="replace"),
        "kind": classify_payload(payload)["kind"],
    }


def analyze_binary_layout(samples: list[bytes]) -> dict[str, Any] | None:
    if not samples:
        return None
    length = len(samples[0])
    if length == 0 or any(len(sample) != length for sample in samples):
        return None

    fixed_offsets = []
    variable_offsets = []
    for index in range(length):
        values = {sample[index] for sample in samples}
        entry = {
            "offset": index,
            "values_hex": sorted(f"{value:02x}" for value in values),
        }
        if len(values) == 1:
            entry["value_hex"] = next(iter(entry["values_hex"]))
            fixed_offsets.append(entry)
        else:
            variable_offsets.append(entry)

    multi_byte_fields = []
    for width in (2, 4):
        if length < width:
            continue
        for start in range(0, length - width + 1):
            chunks = [sample[start : start + width] for sample in samples]
            be_values = [int.from_bytes(chunk, "big") for chunk in chunks]
            le_values = [int.from_bytes(chunk, "little") for chunk in chunks]
            if len(set(be_values)) > 1:
                multi_byte_fields.append(
                    {
                        "offset": start,
                        "width": width,
                        "byte_order": "big",
                        "min": min(be_values),
                        "max": max(be_values),
                        "unique_count": len(set(be_values)),
                    }
                )
            if len(set(le_values)) > 1:
                multi_byte_fields.append(
                    {
                        "offset": start,
                        "width": width,
                        "byte_order": "little",
                        "min": min(le_values),
                        "max": max(le_values),
                        "unique_count": len(set(le_values)),
                    }
                )

    multi_byte_fields.sort(key=lambda item: (item["offset"], item["width"], item["byte_order"]))
    return {
        "length": length,
        "sample_count": len(samples),
        "fixed_offsets": fixed_offsets,
        "variable_offsets": variable_offsets,
        "candidate_numeric_fields": multi_byte_fields[:24],
    }


def crc16(data: bytes, polynomial: int, init: int, reflected: bool) -> int:
    crc = init
    if reflected:
        for byte in data:
            crc ^= byte
            for _ in range(8):
                if crc & 1:
                    crc = (crc >> 1) ^ polynomial
                else:
                    crc >>= 1
        return crc & 0xFFFF

    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ polynomial) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc & 0xFFFF


def analyze_checksum_candidates(samples: list[bytes]) -> list[dict[str, Any]]:
    if not samples:
        return []

    results: list[dict[str, Any]] = []
    for trailer_size in (1, 2, 3):
        if any(len(sample) <= trailer_size for sample in samples):
            continue

        sum8_matches = 0
        xor8_matches = 0
        sum16_be_matches = 0
        sum16_le_matches = 0
        crc_matches: dict[str, int] = {name: 0 for name in CRC16_VARIANTS}

        for sample in samples:
            body = sample[:-trailer_size]
            trailer = sample[-trailer_size:]
            if trailer_size >= 1:
                tail1 = trailer[-1]
                if (sum(body) & 0xFF) == tail1:
                    sum8_matches += 1
                xor_value = 0
                for byte in body:
                    xor_value ^= byte
                if xor_value == tail1:
                    xor8_matches += 1
            if trailer_size >= 2:
                tail2_be = int.from_bytes(trailer[-2:], "big")
                tail2_le = int.from_bytes(trailer[-2:], "little")
                words = [int.from_bytes(body[index : index + 2].ljust(2, b"\x00"), "big") for index in range(0, len(body), 2)]
                sum16 = sum(words) & 0xFFFF
                if sum16 == tail2_be:
                    sum16_be_matches += 1
                if sum16 == tail2_le:
                    sum16_le_matches += 1
                for name, (poly, init, reflected) in CRC16_VARIANTS.items():
                    value = crc16(body, poly, init, reflected)
                    if value == tail2_be or value == tail2_le:
                        crc_matches[name] += 1

        candidate = {
            "trailer_size": trailer_size,
            "sum8_matches": sum8_matches,
            "xor8_matches": xor8_matches,
            "sum16_be_matches": sum16_be_matches,
            "sum16_le_matches": sum16_le_matches,
            "crc16_matches": {name: count for name, count in crc_matches.items() if count > 0},
        }
        results.append(candidate)
    return results


def analyze_time_series(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not events:
        return None
    ordered = sorted(events, key=lambda item: item["captured_at"])
    payloads = [bytes(item["payload"]) for item in ordered]
    length = len(payloads[0])
    if any(len(payload) != length for payload in payloads):
        return None

    variable_offsets = []
    for index in range(length):
        values = [payload[index] for payload in payloads]
        if len(set(values)) > 1:
            deltas = [values[i + 1] - values[i] for i in range(len(values) - 1)]
            variable_offsets.append(
                {
                    "offset": index,
                    "values": values,
                    "deltas": deltas,
                }
            )

    field_windows = []
    for start in range(0, max(0, length - 1)):
        values_be = [int.from_bytes(payload[start : start + 2], "big") for payload in payloads if start + 2 <= len(payload)]
        if len(values_be) == len(payloads) and len(set(values_be)) > 1:
            deltas = [values_be[i + 1] - values_be[i] for i in range(len(values_be) - 1)]
            field_windows.append(
                {
                    "offset": start,
                    "width": 2,
                    "byte_order": "big",
                    "values": values_be,
                    "deltas": deltas,
                }
            )
        values_le = [int.from_bytes(payload[start : start + 2], "little") for payload in payloads if start + 2 <= len(payload)]
        if len(values_le) == len(payloads) and len(set(values_le)) > 1:
            deltas = [values_le[i + 1] - values_le[i] for i in range(len(values_le) - 1)]
            field_windows.append(
                {
                    "offset": start,
                    "width": 2,
                    "byte_order": "little",
                    "values": values_le,
                    "deltas": deltas,
                }
            )

    field_windows.sort(key=lambda item: (item["offset"], item["byte_order"]))
    return {
        "events": [
            {
                "captured_at": item["captured_at"],
                "payload_hex": bytes(item["payload"]).hex(),
            }
            for item in ordered
        ],
        "variable_offsets": variable_offsets,
        "candidate_16bit_fields": field_windows[:20],
    }


def build_protocol_sketch(samples: list[bytes]) -> list[dict[str, Any]]:
    if not samples:
        return []
    length = len(samples[0])
    if any(len(sample) != length for sample in samples):
        return []

    variable = [len({sample[index] for sample in samples}) > 1 for index in range(length)]
    regions: list[tuple[int, int, bool]] = []
    start = 0
    current = variable[0]
    for index in range(1, length):
        if variable[index] != current:
            regions.append((start, index - 1, current))
            start = index
            current = variable[index]
    regions.append((start, length - 1, current))

    sketch = []
    fixed_count = 0
    dynamic_count = 0
    for start, end, is_variable in regions:
        region_samples = [sample[start : end + 1] for sample in samples]
        width = end - start + 1
        if is_variable:
            dynamic_count += 1
            name = f"dynamic_block_{dynamic_count}"
            values = sorted({chunk.hex() for chunk in region_samples})
            role = "dynamic-field"
        else:
            fixed_count += 1
            name = f"fixed_block_{fixed_count}"
            values = [region_samples[0].hex()]
            role = "constant"
        sketch.append(
            {
                "name": name,
                "offset_start": start,
                "offset_end": end,
                "width": width,
                "role": role,
                "sample_values": values[:8],
            }
        )
    return sketch


def append_tcp_segment(stream: TcpStream, sequence: int, payload: bytes) -> None:
    if stream.next_sequence is None:
        stream.next_sequence = sequence

    if sequence < stream.next_sequence:
        overlap = stream.next_sequence - sequence
        if overlap >= len(payload):
            return
        payload = payload[overlap:]
        sequence = stream.next_sequence

    if sequence == stream.next_sequence:
        stream.assembled.extend(payload)
        stream.next_sequence = sequence + len(payload)
        flush_pending(stream)
        return

    existing = stream.pending.get(sequence)
    if existing is None or len(payload) > len(existing):
        stream.pending[sequence] = payload


def flush_pending(stream: TcpStream) -> None:
    while stream.next_sequence in stream.pending:
        sequence = stream.next_sequence
        payload = stream.pending.pop(sequence)
        stream.assembled.extend(payload)
        stream.next_sequence = sequence + len(payload)


def analyze(log_dir: Path, limit: int) -> dict[str, Any]:
    script_path = Path(__file__).resolve().parent / "l2tp_bait.py"
    l2tp_bait = load_l2tp_module(script_path)
    files = iter_capture_files(log_dir, limit)

    tcp_streams: dict[tuple[str, int, str, int], TcpStream] = {}
    udp_flows: dict[tuple[str, int, str, int], UdpFlow] = {}
    icmp_events: list[dict[str, Any]] = []
    control_counts: dict[str, int] = {}

    for path in files:
        parsed = l2tp_bait.parse_packet(path.read_bytes())
        if parsed is None:
            continue
        if parsed.is_control:
            key = str(parsed.message_type)
            control_counts[key] = control_counts.get(key, 0) + 1
            continue
        if parsed.ppp_protocol != 0x0021 or not parsed.payload_info:
            continue

        info = parsed.payload_info
        protocol = info.get("protocol")
        if protocol == 1:
            record = {
                "src_ip": info.get("src_ip"),
                "dst_ip": info.get("dst_ip"),
                "icmp": info.get("icmp"),
            }
            icmp_events.append(record)
            continue
        if protocol == 17:
            udp = info.get("udp") or {}
            ip_header_length = int(info.get("header_length", 0))
            payload = parsed.payload_bytes[4 + ip_header_length + 8 :] if parsed.payload_bytes else b""
            key = (
                str(info.get("src_ip")),
                int(udp.get("src_port", 0)),
                str(info.get("dst_ip")),
                int(udp.get("dst_port", 0)),
            )
            flow = udp_flows.setdefault(
                key,
                UdpFlow(src_ip=key[0], src_port=key[1], dst_ip=key[2], dst_port=key[3]),
            )
            flow.packets += 1
            flow.total_payload_bytes += len(payload)
            flow.events.append(
                {
                    "captured_at": path.name.split("_", 1)[0],
                    "payload": payload,
                }
            )
            signature = payload_signature(payload)
            sample = flow.unique_payloads.setdefault(
                signature,
                {
                    "count": 0,
                    "payload": payload,
                },
            )
            sample["count"] += 1
            continue
        if protocol != 6:
            continue

        tcp = info.get("tcp") or {}
        ip_header_length = int(info.get("header_length", 0))
        tcp_header_length = int(tcp.get("data_offset", 0))
        payload = parsed.payload_bytes[4 + ip_header_length + tcp_header_length :] if parsed.payload_bytes else b""
        key = (
            str(info.get("src_ip")),
            int(tcp.get("src_port", 0)),
            str(info.get("dst_ip")),
            int(tcp.get("dst_port", 0)),
        )
        stream = tcp_streams.setdefault(
            key,
            TcpStream(src_ip=key[0], src_port=key[1], dst_ip=key[2], dst_port=key[3]),
        )
        stream.packets += 1
        stream.bytes_seen += len(payload)
        append_tcp_segment(stream, int(tcp.get("sequence", 0)), payload)

    tcp_summary = []
    for stream in sorted(tcp_streams.values(), key=lambda item: (item.dst_ip, item.dst_port, item.src_ip, item.src_port)):
        assembled = bytes(stream.assembled)
        tcp_summary.append(
            {
                "src_ip": stream.src_ip,
                "src_port": stream.src_port,
                "dst_ip": stream.dst_ip,
                "dst_port": stream.dst_port,
                "packets": stream.packets,
                "payload_bytes_seen": stream.bytes_seen,
                "assembled_bytes": len(assembled),
                "pending_segments": len(stream.pending),
                "payload_guess": classify_payload(assembled),
            }
        )

    return {
        "log_dir": str(log_dir),
        "recv_bin_files": len(files),
        "control_message_counts": control_counts,
        "icmp_events": icmp_events,
        "udp_flows": [
            {
                "src_ip": flow.src_ip,
                "src_port": flow.src_port,
                "dst_ip": flow.dst_ip,
                "dst_port": flow.dst_port,
                "packets": flow.packets,
                "total_payload_bytes": flow.total_payload_bytes,
                "unique_payload_count": len(flow.unique_payloads),
                "samples": [
                    {
                        **payload_preview(item["payload"]),
                        "count": item["count"],
                    }
                    for item in sorted(
                        flow.unique_payloads.values(),
                        key=lambda value: (-int(value["count"]), payload_signature(value["payload"])),
                    )[:8]
                ],
                "binary_layout": analyze_binary_layout(
                    [item["payload"] for item in sorted(flow.unique_payloads.values(), key=lambda value: payload_signature(value["payload"]))]
                ),
                "checksum_candidates": analyze_checksum_candidates(
                    [item["payload"] for item in sorted(flow.unique_payloads.values(), key=lambda value: payload_signature(value["payload"]))]
                ),
                "time_series": analyze_time_series(flow.events),
                "protocol_sketch": build_protocol_sketch(
                    [item["payload"] for item in sorted(flow.unique_payloads.values(), key=lambda value: payload_signature(value["payload"]))]
                ),
            }
            for flow in udp_flows.values()
        ],
        "tcp_streams": tcp_summary,
    }


def render_text(summary: dict[str, Any]) -> str:
    lines = []
    lines.append(f"log_dir: {summary['log_dir']}")
    lines.append(f"recv_bin_files: {summary['recv_bin_files']}")
    if summary["control_message_counts"]:
        lines.append("control_message_counts:")
        for key, value in sorted(summary["control_message_counts"].items(), key=lambda item: int(item[0])):
            lines.append(f"  type={key} count={value}")
    if summary["icmp_events"]:
        lines.append("icmp_events:")
        for item in summary["icmp_events"][:20]:
            lines.append(
                f"  {item['src_ip']} -> {item['dst_ip']} icmp={json.dumps(item['icmp'], ensure_ascii=False)}"
            )
        if len(summary["icmp_events"]) > 20:
            lines.append(f"  ... total={len(summary['icmp_events'])}")
    if summary["udp_flows"]:
        lines.append("udp_flows:")
        for item in summary["udp_flows"]:
            lines.append(
                f"  {item['src_ip']}:{item['src_port']} -> {item['dst_ip']}:{item['dst_port']} "
                f"packets={item['packets']} payload_bytes={item['total_payload_bytes']} "
                f"unique_payloads={item['unique_payload_count']}"
            )
            for sample in item["samples"][:3]:
                preview = sample["preview_text"].replace("\r", "\\r").replace("\n", "\\n")
                lines.append(
                    f"    sample kind={sample['kind']} count={sample['count']} hex={sample['preview_hex'][:96]}"
                )
                if preview:
                    lines.append(f"    text={preview[:120]}")
            layout = item.get("binary_layout")
            if layout:
                variable_offsets = ", ".join(
                    f"{entry['offset']}[{ '/'.join(entry['values_hex']) }]" for entry in layout["variable_offsets"][:12]
                )
                if variable_offsets:
                    lines.append(f"    variable_offsets={variable_offsets}")
                candidate_fields = layout.get("candidate_numeric_fields") or []
                for field in candidate_fields[:6]:
                    lines.append(
                        f"    field offset={field['offset']} width={field['width']} {field['byte_order']} "
                        f"range={field['min']}..{field['max']} unique={field['unique_count']}"
                    )
                for checksum in item.get("checksum_candidates", []):
                    crc_text = ", ".join(
                        f"{name}={count}" for name, count in sorted(checksum["crc16_matches"].items())
                    ) or "none"
                    lines.append(
                        f"    checksum trailer={checksum['trailer_size']} "
                        f"sum8={checksum['sum8_matches']} xor8={checksum['xor8_matches']} "
                        f"sum16be={checksum['sum16_be_matches']} sum16le={checksum['sum16_le_matches']} "
                        f"crc16={crc_text}"
                    )
                time_series = item.get("time_series")
                if time_series:
                    for variable in time_series["variable_offsets"][:6]:
                        lines.append(
                            f"    series offset={variable['offset']} values={variable['values'][:12]} deltas={variable['deltas'][:12]}"
                        )
                    for field in time_series["candidate_16bit_fields"][:6]:
                        lines.append(
                            f"    series16 offset={field['offset']} {field['byte_order']} "
                            f"values={field['values'][:12]} deltas={field['deltas'][:12]}"
                        )
                for block in item.get("protocol_sketch", []):
                    values = ", ".join(block["sample_values"][:4])
                    lines.append(
                        f"    sketch {block['name']} offset={block['offset_start']}..{block['offset_end']} "
                        f"width={block['width']} role={block['role']} values={values}"
                    )
    if summary["tcp_streams"]:
        lines.append("tcp_streams:")
        for item in summary["tcp_streams"]:
            guess = item["payload_guess"]
            lines.append(
                f"  {item['src_ip']}:{item['src_port']} -> {item['dst_ip']}:{item['dst_port']} "
                f"packets={item['packets']} assembled={item['assembled_bytes']} kind={guess['kind']}"
            )
            preview = guess["preview_text"].replace("\r", "\\r").replace("\n", "\\n")
            if preview:
                lines.append(f"    preview={preview[:180]}")
    return "\n".join(lines)


def main() -> None:
    args = parse_args()
    summary = analyze(Path(args.log_dir), args.limit)
    if args.save_json:
        Path(args.save_json).write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    stdout = getattr(sys.stdout, "buffer", None)
    if args.json:
        output = json.dumps(summary, ensure_ascii=False, indent=2)
    else:
        output = render_text(summary)
    if stdout is not None:
        stdout.write((output + "\n").encode("utf-8", errors="backslashreplace"))
    else:
        print(output)


if __name__ == "__main__":
    main()
