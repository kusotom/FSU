from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


MAGIC = b"QZ^&"
STATUS_MAGIC = b"\x7e\x3e"
STATUS_HEADER_LENGTH = 15
KNOWN_CODES = {
    200: "realtime-data",
}
STATUS_LABELS = {
    6: "offline-or-read-failed",
}
HEARTBEAT_STATUS_WORDS = {"online", "offline", "unknown"}
REGISTER_FIELD_LABELS = {
    1: "signal_strength_summary",
    2: "register_status_code",
    3: "carrier_code",
    4: "wireless_sysinfo_raw",
    5: "xml_log_timestamps",
    6: "uptime_summary",
    7: "site_name",
    8: "virtual_host",
    9: "mac_address",
    10: "fsu_model",
    11: "fsu_software_version",
    12: "protocol_version",
    13: "device_serial",
    14: "modem_do_config",
    15: "light_do_config",
    16: "do_status",
    17: "do_health",
    18: "runtime_hours",
    19: "site_code",
    20: "vpn_dial_stats",
    21: "modem_dial_stats",
    22: "data_scip",
    23: "tt_proxy_virtual_host",
    24: "data_scip_ping",
    25: "modem_power_stats",
    26: "register_status_text",
    27: "kernel_version",
    28: "modem_partition_usage",
    29: "data_partition_usage",
    40: "camera_vendor_info",
    100: "ds_route_test",
    101: "siteunit_runtime_info",
    103: "vpn_username_password",
    1000: "tt_proxy_interval",
    1001: "tt_proxy_virtual_machine",
    1002: "tt_proxy_version",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Decode inferred tt_proxy UDP/10378 packets")
    parser.add_argument("input", help="Path to a binary file, or a hex string when --hex is used")
    parser.add_argument("--hex", action="store_true", help="Treat input as a hex string instead of a file path")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def load_payload(value: str, is_hex: bool) -> bytes:
    if is_hex:
        return bytes.fromhex(value.replace(" ", ""))
    return Path(value).read_bytes()


def clean_text(value: str) -> str:
    return value.replace("\x00", "").strip()


def parse_kv_segment(segment: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in segment.split("`"):
        if "=" not in item:
            continue
        key, value = item.split("=", 1)
        result[key] = value
    return result


def annotate_realtime_item(item: dict[str, str]) -> dict[str, Any]:
    annotated: dict[str, Any] = dict(item)
    if "status" in item:
        try:
            status_code = int(item["status"])
        except ValueError:
            status_code = None
        annotated["status_code"] = status_code
        if status_code is not None:
            annotated["status_label_guess"] = STATUS_LABELS.get(status_code, "unknown-status-code")
    if "bGet" in item:
        annotated["bget_bool"] = item["bGet"].lower() == "true"
    if "value" in item:
        annotated["value_is_empty"] = item["value"] == ""
    return annotated


def decode_status_text(payload: bytes) -> str:
    return clean_text(payload.decode("gb18030", errors="replace"))


def parse_register_fields(text: str) -> list[dict[str, Any]]:
    fields: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or "|" not in line:
            continue
        key_text, value = line.split("|", 1)
        field: dict[str, Any] = {
            "raw": line,
            "field_id_text": key_text,
            "value": value.strip(),
        }
        if key_text.isdigit():
            field_id = int(key_text)
            field["field_id"] = field_id
            field["field_name_guess"] = REGISTER_FIELD_LABELS.get(field_id, "unknown-field")
        fields.append(field)
    return fields


def annotate_register_summary(fields: list[dict[str, Any]]) -> dict[str, Any]:
    field_map = {
        int(item["field_id"]): item["value"]
        for item in fields
        if isinstance(item.get("field_id"), int)
    }
    summary: dict[str, Any] = {}
    if 19 in field_map:
        summary["site_code"] = field_map[19]
    if 7 in field_map:
        summary["site_name"] = field_map[7]
    if 22 in field_map:
        summary["data_scip"] = field_map[22]
    if 2 in field_map:
        summary["register_status_code"] = field_map[2]
    if 26 in field_map:
        summary["register_status_text"] = field_map[26]
    if 10 in field_map:
        summary["fsu_model"] = field_map[10]
    if 11 in field_map:
        summary["fsu_software_version"] = field_map[11]
    return summary


def decode_payload(payload: bytes) -> dict[str, Any]:
    result: dict[str, Any] = {
        "payload_length": len(payload),
        "payload_hex": payload.hex(),
        "magic_found": False,
        "magic_expected_hex": MAGIC.hex(),
        "magic_prefix_hex": "",
        "message_code": None,
        "message_code_name": None,
        "message_body": None,
        "message_type_guess": "unknown",
        "body_format_guess": "opaque-text",
        "realtime_items": [],
        "register_fields": [],
        "register_summary": {},
        "protocol_summary": {},
    }

    body = payload
    magic_offset = payload.find(MAGIC)
    if magic_offset >= 0:
        result["magic_found"] = True
        result["magic_offset"] = magic_offset
        result["magic_prefix_hex"] = payload[:magic_offset].hex()
        body = payload[magic_offset + len(MAGIC) :]

    text = clean_text(body.decode("utf-8", errors="replace"))
    result["decoded_text"] = text

    pipe_index = text.find("|")
    if pipe_index > 0 and text[:pipe_index].isdigit():
        result["message_code"] = int(text[:pipe_index])
        result["message_code_name"] = KNOWN_CODES.get(result["message_code"])
        result["message_body"] = text[pipe_index + 1 :]
    else:
        result["message_body"] = text

    code = result["message_code"]
    message_body = clean_text(result["message_body"] or "")
    result["message_body"] = message_body
    if code == 200:
        result["message_type_guess"] = "realtime-data"
        result["body_format_guess"] = "semicolon-records with backtick-kv"
        items = []
        for segment in message_body.split(";"):
            segment = segment.strip()
            if not segment:
                continue
            parsed = parse_kv_segment(segment)
            if parsed:
                items.append(annotate_realtime_item(parsed))
            else:
                items.append({"raw": segment})
        result["realtime_items"] = items
    elif "heartbeat" in message_body.lower():
        result["message_type_guess"] = "heartbeat"

    if message_body in HEARTBEAT_STATUS_WORDS:
        result["message_type_guess"] = "heartbeat-status"
        result["body_format_guess"] = "single-status-word"

    if "deviceId=" in message_body and result["message_type_guess"] == "unknown":
        result["message_type_guess"] = "realtime-data"
        result["body_format_guess"] = "semicolon-records with backtick-kv"

    if payload.startswith(STATUS_MAGIC) and len(payload) > STATUS_HEADER_LENGTH:
        result["status_header_found"] = True
        result["status_header_length"] = STATUS_HEADER_LENGTH
        result["status_header_hex"] = payload[:STATUS_HEADER_LENGTH].hex()
        result["status_header"] = {
            "magic_hex": payload[0:2].hex(),
            "token_hex": payload[2:6].hex(),
            "version_hex": payload[6:8].hex(),
            "reserved_hex": payload[8:11].hex(),
            "device_token_hex": payload[11:15].hex(),
        }

        status_body = payload[STATUS_HEADER_LENGTH:]
        status_text = decode_status_text(status_body)
        result["decoded_text"] = status_text
        result["message_body"] = status_text
        result["message_code"] = None
        result["message_code_name"] = None
        result["message_type_guess"] = "register-status"
        result["body_format_guess"] = "gb18030 newline records with numeric field ids"
        result["register_fields"] = parse_register_fields(status_text)
        result["register_summary"] = annotate_register_summary(result["register_fields"])

    result["protocol_summary"] = {
        "transport_guess": "tt_proxy private udp northbound",
        "wrapper_guess": "either QZ^& + <code>|<body> or 15-byte status header + gb18030 field records",
        "realtime_code_guess": 200,
        "realtime_item_format_guess": "deviceId=...`ID=...`bGet=...`status=...`value=...;",
        "heartbeat_status_words": sorted(HEARTBEAT_STATUS_WORDS),
    }

    return result


def render_text(decoded: dict[str, Any]) -> str:
    lines = [
        f"payload_length: {decoded['payload_length']}",
        f"magic_found: {decoded['magic_found']}",
    ]
    if "magic_offset" in decoded:
        lines.append(f"magic_offset: {decoded['magic_offset']}")
    if decoded.get("magic_prefix_hex"):
        lines.append(f"magic_prefix_hex: {decoded['magic_prefix_hex']}")
    lines.append(f"message_code: {decoded['message_code']}")
    lines.append(f"message_code_name: {decoded['message_code_name']}")
    lines.append(f"message_type_guess: {decoded['message_type_guess']}")
    lines.append(f"body_format_guess: {decoded['body_format_guess']}")
    lines.append(f"message_body: {decoded['message_body']}")
    if decoded["realtime_items"]:
        lines.append("realtime_items:")
        for item in decoded["realtime_items"]:
            lines.append(f"  {json.dumps(item, ensure_ascii=False)}")
    if decoded.get("status_header"):
        lines.append(f"status_header: {json.dumps(decoded['status_header'], ensure_ascii=False)}")
    if decoded.get("register_summary"):
        lines.append(f"register_summary: {json.dumps(decoded['register_summary'], ensure_ascii=False)}")
    if decoded.get("register_fields"):
        lines.append("register_fields:")
        for item in decoded["register_fields"]:
            lines.append(f"  {json.dumps(item, ensure_ascii=False)}")
    summary = decoded.get("protocol_summary") or {}
    if summary:
        lines.append("protocol_summary:")
        lines.append(f"  transport_guess: {summary.get('transport_guess')}")
        lines.append(f"  wrapper_guess: {summary.get('wrapper_guess')}")
        lines.append(f"  realtime_code_guess: {summary.get('realtime_code_guess')}")
        lines.append(f"  realtime_item_format_guess: {summary.get('realtime_item_format_guess')}")
    return "\n".join(lines)


def main() -> None:
    args = parse_args()
    payload = load_payload(args.input, args.hex)
    decoded = decode_payload(payload)
    if args.json:
        print(json.dumps(decoded, ensure_ascii=False, indent=2))
    else:
        print(render_text(decoded))


if __name__ == "__main__":
    main()
