from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def load_decoder(script_path: Path):
    spec = importlib.util.spec_from_file_location("decode_ttproxy_udp10378", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load {script_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze captured tt_proxy UDP/10378 packets")
    parser.add_argument(
        "log_dir",
        nargs="?",
        default=str(Path(__file__).resolve().parents[1] / "logs" / "ttproxy-udp"),
        help="Directory containing captured .bin files from ttproxy_udp_bait.py",
    )
    parser.add_argument("--limit", type=int, default=0, help="Only analyze newest N .bin files")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def iter_bin_files(log_dir: Path, limit: int) -> list[Path]:
    files = sorted(log_dir.glob("*.bin"))
    if limit > 0:
        files = files[-limit:]
    return files


def summarize_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    message_code_counter: Counter[str] = Counter()
    message_type_counter: Counter[str] = Counter()
    remote_counter: Counter[str] = Counter()
    register_status_counter: Counter[str] = Counter()
    data_scip_counter: Counter[str] = Counter()
    code_samples: dict[str, list[str]] = defaultdict(list)
    type_samples: dict[str, list[str]] = defaultdict(list)

    for record in records:
        remote = f"{record['remote_ip']}:{record['remote_port']}"
        remote_counter[remote] += 1

        code = record.get("message_code")
        code_key = "none" if code is None else str(code)
        message_code_counter[code_key] += 1

        msg_type = record.get("message_type_guess") or "unknown"
        message_type_counter[msg_type] += 1

        register_summary = record.get("register_summary") or {}
        status_text = register_summary.get("register_status_text")
        if status_text:
            register_status_counter[str(status_text)] += 1
        data_scip = register_summary.get("data_scip")
        if data_scip:
            data_scip_counter[str(data_scip)] += 1

        body = (record.get("message_body") or "")[:200]
        if body and len(code_samples[code_key]) < 3 and body not in code_samples[code_key]:
            code_samples[code_key].append(body)
        if body and len(type_samples[msg_type]) < 3 and body not in type_samples[msg_type]:
            type_samples[msg_type].append(body)

    return {
        "packet_count": len(records),
        "remote_endpoints": [
            {"remote": remote, "packets": count}
            for remote, count in remote_counter.most_common()
        ],
        "message_codes": [
            {"message_code": code, "packets": count, "samples": code_samples.get(code, [])}
            for code, count in message_code_counter.most_common()
        ],
        "message_types": [
            {"message_type": msg_type, "packets": count, "samples": type_samples.get(msg_type, [])}
            for msg_type, count in message_type_counter.most_common()
        ],
        "register_statuses": [
            {"register_status": status, "packets": count}
            for status, count in register_status_counter.most_common()
        ],
        "data_scip_values": [
            {"data_scip": data_scip, "packets": count}
            for data_scip, count in data_scip_counter.most_common()
        ],
    }


def render_text(summary: dict[str, Any], records: list[dict[str, Any]]) -> str:
    lines = [f"packet_count: {summary['packet_count']}"]
    if summary["remote_endpoints"]:
        lines.append("remote_endpoints:")
        for item in summary["remote_endpoints"]:
            lines.append(f"  {item['remote']} packets={item['packets']}")
    if summary["message_codes"]:
        lines.append("message_codes:")
        for item in summary["message_codes"]:
            lines.append(f"  code={item['message_code']} packets={item['packets']}")
            for sample in item["samples"]:
                lines.append(f"    sample={sample}")
    if summary["message_types"]:
        lines.append("message_types:")
        for item in summary["message_types"]:
            lines.append(f"  type={item['message_type']} packets={item['packets']}")
            for sample in item["samples"]:
                lines.append(f"    sample={sample}")
    if summary.get("register_statuses"):
        lines.append("register_statuses:")
        for item in summary["register_statuses"]:
            lines.append(f"  status={item['register_status']} packets={item['packets']}")
    if summary.get("data_scip_values"):
        lines.append("data_scip_values:")
        for item in summary["data_scip_values"]:
            lines.append(f"  data_scip={item['data_scip']} packets={item['packets']}")
    if records:
        lines.append("latest_packets:")
        for item in records[-5:]:
            register_summary = item.get("register_summary") or {}
            register_bits = []
            if register_summary.get("site_code"):
                register_bits.append(f"site={register_summary['site_code']}")
            if register_summary.get("data_scip"):
                register_bits.append(f"scip={register_summary['data_scip']}")
            if register_summary.get("register_status_text"):
                register_bits.append(f"status={register_summary['register_status_text']}")
            lines.append(
                f"  {item['capture_file']} remote={item['remote_ip']}:{item['remote_port']} "
                f"code={item.get('message_code')} type={item.get('message_type_guess')} "
                f"{' '.join(register_bits)} "
                f"body={json.dumps((item.get('message_body') or '')[:120], ensure_ascii=False)}"
            )
    return "\n".join(lines)


def main() -> None:
    args = parse_args()
    log_dir = Path(args.log_dir)
    decoder = load_decoder(Path(__file__).resolve().parent / "decode_ttproxy_udp10378.py")

    records: list[dict[str, Any]] = []
    for path in iter_bin_files(log_dir, args.limit):
        payload = path.read_bytes()
        decoded = decoder.decode_payload(payload)
        stem = path.stem
        parts = stem.split("_")
        remote_ip = parts[-2] if len(parts) >= 2 else ""
        try:
            remote_port = int(parts[-1]) if len(parts) >= 1 else 0
        except ValueError:
            remote_port = 0
        records.append(
            {
                "capture_file": path.name,
                "remote_ip": remote_ip,
                "remote_port": remote_port,
                **decoded,
            }
        )

    summary = summarize_records(records)
    output = {"summary": summary, "records": records} if args.json else render_text(summary, records)
    stdout = getattr(sys.stdout, "buffer", None)
    text = json.dumps(output, ensure_ascii=False, indent=2) if args.json else output
    if stdout is not None:
        stdout.write((text + "\n").encode("utf-8", errors="backslashreplace"))
    else:
        print(text)


if __name__ == "__main__":
    main()
