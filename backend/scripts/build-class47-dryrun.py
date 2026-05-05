from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
MODULE_PATH = BACKEND_DIR / "app" / "modules" / "fsu_gateway" / "dsc_class47.py"

spec = importlib.util.spec_from_file_location("dsc_class47_standalone", MODULE_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError(f"Unable to load dsc_class47 module from {MODULE_PATH}")
dsc_class47 = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = dsc_class47
spec.loader.exec_module(dsc_class47)
build_class47_response_from_request = dsc_class47.build_class47_response_from_request


def parse_hex(value: str) -> bytes:
    cleaned = re.sub(r"0x", "", value, flags=re.IGNORECASE)
    cleaned = re.sub(r"[^0-9a-fA-F]", "", cleaned)
    if len(cleaned) % 2 != 0:
        raise ValueError("hex input has an odd number of digits")
    return bytes.fromhex(cleaned)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build classByte=0x47 FSU response in dry-run mode only.")
    parser.add_argument("--hex", required=True, help="Complete 0x46 request hex.")
    parser.add_argument("--platform-ip", default="192.168.100.123")
    parser.add_argument("--dsc-port", type=int, default=9000)
    parser.add_argument("--rds-port", type=int, default=7000)
    args = parser.parse_args()

    try:
        request = parse_hex(args.hex)
        result = build_class47_response_from_request(request, args.platform_ip, args.dsc_port, args.rds_port)
    except Exception as exc:  # noqa: BLE001 - CLI must return structured failure.
        print(json.dumps({"safety": "DRY_RUN_ONLY_NO_UDP_SENT", "ok": False, "reason": str(exc)}, ensure_ascii=False))
        return 2

    output = {
        "safety": "DRY_RUN_ONLY_NO_UDP_SENT",
        "ok": result.ok,
        "reason": result.reason,
        "seqLE": result.seq_le,
        "seqBytes": result.seq_bytes_hex,
        "payloadLength": result.payload_length,
        "totalLength": result.total_length,
        "checksumLE": result.checksum_le,
        "responseHex": result.response.hex() if result.response else "",
        "payloadHex": result.payload.hex() if result.payload else "",
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
