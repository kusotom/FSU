from __future__ import annotations

import argparse
import html
import json
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


SOAP_ENV_NS = "http://schemas.xmlsoap.org/soap/envelope/"
FSU_SERVICE_NS = "http://FSUService.chinatowercom.com"


@dataclass
class ProbeResult:
    command: str
    variant: str
    status: int | None
    elapsed_seconds: float
    request_file: str
    response_file: str | None
    error: str | None
    packet_name: str
    packet_code: str
    device_ids: list[str]
    signal_count: int


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")


def local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    if ":" in tag:
        return tag.rsplit(":", 1)[1]
    return tag


def iter_by_name(root: ET.Element, name: str) -> Iterable[ET.Element]:
    for elem in root.iter():
        if local_name(elem.tag) == name:
            yield elem


def first_text(root: ET.Element, name: str) -> str:
    for elem in iter_by_name(root, name):
        if elem.text:
            return elem.text.strip()
    return ""


def decode_payload(raw: bytes) -> str:
    for encoding in ("utf-8", "gb18030", "gbk", "latin1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            pass
    return raw.decode("utf-8", errors="replace")


def parse_xml(text: str) -> ET.Element:
    return ET.fromstring(text.strip("\ufeff\r\n\t "))


def unwrap_protocol_xml(text: str) -> tuple[str, bool]:
    root = parse_xml(text)
    if local_name(root.tag) != "Envelope":
        return text, False

    for field in ("xmlData", "invokeReturn", "return"):
        value = first_text(root, field)
        if value:
            return html.unescape(value), True

    for elem in root.iter():
        candidate = html.unescape((elem.text or "").strip())
        if "<Request" in candidate or "<Response" in candidate:
            return candidate, True

    raise ValueError("SOAP payload does not contain protocol XML")


def packet_summary(protocol_xml: str) -> tuple[str, str, list[str], int]:
    root = parse_xml(protocol_xml)
    pk_type = next(iter_by_name(root, "PK_Type"), None)
    name = first_text(pk_type, "Name") if pk_type is not None else ""
    code = first_text(pk_type, "Code") if pk_type is not None else ""
    device_ids = []
    for elem in iter_by_name(root, "Device"):
        value = elem.attrib.get("Id") or elem.attrib.get("ID") or elem.attrib.get("id")
        if value:
            device_ids.append(value)
    signal_count = sum(1 for name_ in ("TSemaphore", "Semaphore", "Signal", "TSignal") for _ in iter_by_name(root, name_))
    return name, code, device_ids, signal_count


def device_list_xml(device_ids: list[str], indent: str = "        ", signal_map: dict[str, list[str]] | None = None) -> str:
    if not device_ids:
        return ""
    signal_map = signal_map or {}
    lines = [f"{indent}<DeviceList>"]
    for device_id in device_ids:
        escaped_device_id = html.escape(device_id)
        signals = signal_map.get(device_id, [])
        if not signals:
            lines.append(f'{indent}    <Device Id="{escaped_device_id}" Code="{escaped_device_id}"/>')
            continue
        lines.append(f'{indent}    <Device Id="{escaped_device_id}" Code="{escaped_device_id}">')
        for signal_id in signals:
            escaped_signal_id = html.escape(signal_id)
            lines.append(f'{indent}        <TSemaphore Id="{escaped_signal_id}" Code="{escaped_signal_id}"/>')
        lines.append(f"{indent}    </Device>")
    lines.append(f"{indent}</DeviceList>")
    return "\n".join(lines)


def request_xml(
    command: str,
    code: str,
    fsu_code: str,
    variant: str,
    device_ids: list[str],
    signal_map: dict[str, list[str]] | None = None,
) -> str:
    signal_map = signal_map or {}
    use_signals = variant in {"info-devices-signals"}
    device_list = device_list_xml(device_ids, signal_map=signal_map if use_signals else None)
    info_lines = [
        f"        <FsuId>{html.escape(fsu_code)}</FsuId>",
        f"        <FsuCode>{html.escape(fsu_code)}</FsuCode>",
    ]
    if variant == "info-devices" and device_list:
        info_lines.append(device_list)
    if variant == "info-values-devices" and device_list:
        info_lines.append("        <Values>")
        info_lines.append(device_list.replace("        ", "            "))
        info_lines.append("        </Values>")
    if variant == "info-devices-signals" and device_list:
        info_lines.append(device_list)
    info = "\n".join(info_lines)
    root_device_list = ""
    if variant == "root-devices" and device_list:
        root_device_list = f"{device_list}\n"
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<Request>\n"
        "    <PK_Type>\n"
        f"        <Name>{html.escape(command)}</Name>\n"
        f"        <Code>{html.escape(code)}</Code>\n"
        "    </PK_Type>\n"
        "    <Info>\n"
        f"{info}\n"
        "    </Info>\n"
        f"{root_device_list}"
        "</Request>\n"
    )


def soap_request(inner_xml: str) -> str:
    escaped = html.escape(inner_xml, quote=False)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<SOAP-ENV:Envelope xmlns:SOAP-ENV="{SOAP_ENV_NS}" '
        'xmlns:SOAP-ENC="http://schemas.xmlsoap.org/soap/encoding/" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        'xmlns:xsd="http://www.w3.org/2001/XMLSchema" '
        f'xmlns:ns1="{FSU_SERVICE_NS}">'
        '<SOAP-ENV:Body SOAP-ENV:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
        "<ns1:invoke>"
        f"<xmlData>{escaped}</xmlData>"
        "</ns1:invoke>"
        "</SOAP-ENV:Body>"
        "</SOAP-ENV:Envelope>\n"
    )


def post_soap(url: str, soap_xml: str, timeout: float) -> tuple[int, bytes]:
    request = urllib.request.Request(
        url,
        data=soap_xml.encode("utf-8"),
        headers={
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": '""',
            "User-Agent": "fsu-platform/estoneii-fsu-soap-probe",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.status, response.read()


def run_probe(
    url: str,
    output_dir: Path,
    command: str,
    code: str,
    fsu_code: str,
    variant: str,
    device_ids: list[str],
    signal_map: dict[str, list[str]],
    timeout: float,
) -> ProbeResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = utc_stamp()
    safe_variant = variant.replace(",", "-")
    request_file = output_dir / f"{stamp}_{command}_{safe_variant}_request.xml"
    response_file = output_dir / f"{stamp}_{command}_{safe_variant}_response.xml"
    request_body = request_xml(command, code, fsu_code, variant, device_ids, signal_map)
    soap_body = soap_request(request_body)
    request_file.write_text(soap_body, encoding="utf-8")

    started = time.monotonic()
    status: int | None = None
    response_text = ""
    error: str | None = None
    packet_name = ""
    packet_code = ""
    response_device_ids: list[str] = []
    signal_count = 0

    try:
        status, raw = post_soap(url, soap_body, timeout)
        response_text = decode_payload(raw)
        response_file.write_text(response_text, encoding="utf-8")
        protocol_xml, _is_soap = unwrap_protocol_xml(response_text)
        packet_name, packet_code, response_device_ids, signal_count = packet_summary(protocol_xml)
    except urllib.error.HTTPError as exc:
        status = exc.code
        raw = exc.read()
        response_text = decode_payload(raw)
        response_file.write_text(response_text, encoding="utf-8")
        error = f"HTTPError: {exc.code} {exc.reason}"
    except Exception as exc:  # noqa: BLE001 - probe should persist failure details
        if not response_text:
            response_file = None
        error = f"{type(exc).__name__}: {exc}"

    elapsed = time.monotonic() - started
    return ProbeResult(
        command=command,
        variant=variant,
        status=status,
        elapsed_seconds=round(elapsed, 3),
        request_file=request_file.name,
        response_file=response_file.name if response_file else None,
        error=error,
        packet_name=packet_name,
        packet_code=packet_code,
        device_ids=response_device_ids,
        signal_count=signal_count,
    )


def write_summary(output_dir: Path, results: list[ProbeResult]) -> None:
    payload = [result.__dict__ for result in results]
    (output_dir / "summary.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe eStoneII local FSUService SOAP invoke/xmlData endpoint.")
    parser.add_argument("--url", default="http://192.168.100.100:8080/")
    parser.add_argument("--fsu-code", default="51051243812345")
    parser.add_argument("--get-fsuinfo-code", default="101")
    parser.add_argument("--get-data-code", default="401")
    parser.add_argument("--output-dir", default="backend/logs/estoneii-fsu-soap-probe")
    parser.add_argument("--timeout", type=float, default=25)
    parser.add_argument("--device-id", action="append", default=[], help="Device Id/Code to include. Repeatable.")
    parser.add_argument(
        "--signal",
        action="append",
        default=[],
        help="Requested signal list in DEVICE_ID:SIGNAL_ID[,SIGNAL_ID] form. Repeatable.",
    )
    parser.add_argument(
        "--variants",
        default="minimal,info-devices,root-devices,per-device",
        help="Comma-separated GET_DATA variants.",
    )
    parser.add_argument("--skip-fsuinfo", action="store_true")
    parser.add_argument("--skip-get-data", action="store_true")
    return parser.parse_args()


def parse_signal_map(values: list[str]) -> dict[str, list[str]]:
    signal_map: dict[str, list[str]] = {}
    for value in values:
        if ":" not in value:
            raise ValueError(f"invalid --signal value, expected DEVICE_ID:SIGNAL_ID[,SIGNAL_ID]: {value}")
        device_id, raw_signals = value.split(":", 1)
        device_id = device_id.strip()
        signals = [signal.strip() for signal in raw_signals.split(",") if signal.strip()]
        if not device_id or not signals:
            raise ValueError(f"invalid --signal value, expected DEVICE_ID:SIGNAL_ID[,SIGNAL_ID]: {value}")
        signal_map.setdefault(device_id, [])
        for signal in signals:
            if signal not in signal_map[device_id]:
                signal_map[device_id].append(signal)
    return signal_map


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir)
    results: list[ProbeResult] = []
    device_ids = list(dict.fromkeys(args.device_id))
    signal_map = parse_signal_map(args.signal)

    if not args.skip_fsuinfo:
        result = run_probe(
            args.url,
            output_dir,
            "GET_FSUINFO",
            args.get_fsuinfo_code,
            args.fsu_code,
            "minimal",
            [],
            {},
            args.timeout,
        )
        results.append(result)
        if result.device_ids and not device_ids:
            device_ids = result.device_ids

    if not args.skip_get_data:
        variants = [variant.strip() for variant in args.variants.split(",") if variant.strip()]
        for variant in variants:
            if variant == "per-device":
                for device_id in device_ids:
                    results.append(
                        run_probe(
                            args.url,
                            output_dir,
                            "GET_DATA",
                            args.get_data_code,
                            args.fsu_code,
                            variant,
                            [device_id],
                            signal_map,
                            args.timeout,
                        )
                    )
                continue
            results.append(
                run_probe(
                    args.url,
                    output_dir,
                    "GET_DATA",
                    args.get_data_code,
                    args.fsu_code,
                    variant,
                    device_ids,
                    signal_map,
                    args.timeout,
                )
            )

    write_summary(output_dir, results)
    return 1 if any(result.error for result in results) else 0


if __name__ == "__main__":
    sys.exit(main())
