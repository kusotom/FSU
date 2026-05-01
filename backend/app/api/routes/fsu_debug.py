from __future__ import annotations

from collections import Counter, deque
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
from typing import Any

from fastapi import APIRouter, Depends, Query

from app.api.deps_authz import permission_required
from app.core.config import settings

router = APIRouter(prefix="/fsu-debug", tags=["fsu-debug"])

RAW_LOG_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\.jsonl$")
URI_RE = re.compile(r"\b(?:udp|ftp)://[A-Za-z0-9._~:/?#[\]@!$&'()*+,;=%-]+")
ASCII_RE = re.compile(rb"[\x20-\x7e]{4,}")
KNOWN_LENGTHS = {24, 30, 209, 245}
KNOWN_CONFIG_CLASSES = {"DSC_CONFIG_209_TYPE_1100_46FF", "DSC_CONFIG_245_TYPE_1100_46FF"}
DAILY_REPORT_RE = re.compile(r"^daily-observation-(\d{4}-\d{2}-\d{2})\.(md|json)$")

FRAME_CLASS_ANNOTATIONS: dict[str, dict[str, Any]] = {
    "DSC_CONFIG_209_TYPE_1100_46FF": {
        "semanticClass": "DSC_REGISTER_CONFIG_RETRY",
        "chineseName": "DSC注册/配置重试帧A",
        "confidence": 0.75,
        "businessDataConfirmed": False,
        "notes": [
            "DSC 通道",
            "totalLength=209",
            "typeA=1100_46FF",
            "当前约 3.031 秒周期重复",
            "当前没有收到能使其停止的确认",
            "暂不判定为业务数据帧",
            "只读逆向注释，未由厂商协议文档确认",
        ],
    },
    "DSC_CONFIG_245_TYPE_1100_46FF": {
        "semanticClass": "DSC_REGISTER_CONFIG_RETRY_EXT",
        "chineseName": "DSC注册/配置重试帧B/扩展帧",
        "confidence": 0.75,
        "businessDataConfirmed": False,
        "notes": [
            "DSC 通道",
            "totalLength=245",
            "typeA=1100_46FF",
            "与 209 帧同 typeA 但长度不同",
            "245 与 209 的 36 字节长度差异需要优先验证是否由 URI 字符串长度差异解释",
            "可能属于注册/配置阶段的显式 IP 版本配置帧",
            "暂不判定为业务数据帧",
            "只读逆向注释，未由厂商协议文档确认",
        ],
    },
    "DSC_SHORT_24_TYPE_1F00_D2FF": {
        "semanticClass": "DSC_KEEPALIVE_OR_ACK_WAIT",
        "chineseName": "DSC短心跳/等待确认候选帧",
        "confidence": 0.7,
        "businessDataConfirmed": False,
        "notes": [
            "DSC 通道",
            "totalLength=24",
            "typeA=1F00_D2FF",
            "当前约 1.063 秒周期重复",
            "与 RDS_SHORT_30 成对出现",
            "当前不判定为业务数据帧",
            "ACK_WAIT 仅为推断，不代表已确认 ACK 语义",
            "只读逆向注释，未由厂商协议文档确认",
        ],
    },
    "RDS_SHORT_30_TYPE_1180_D2FF": {
        "semanticClass": "RDS_HEARTBEAT_OR_KEEPALIVE",
        "chineseName": "RDS实时通道心跳/保活候选帧",
        "confidence": 0.85,
        "businessDataConfirmed": False,
        "notes": [
            "RDS 通道",
            "totalLength=30",
            "typeA=1180_D2FF",
            "当前约 1.063 秒周期重复",
            "当前 RDS 通道尚未出现非 30 字节业务数据帧",
            "暂不判定为实时业务数据帧",
            "只读逆向注释，未由厂商协议文档确认",
        ],
    },
}

TYPE_A_ANNOTATIONS: dict[str, dict[str, Any]] = {
    "110046ff": {
        "typeA": "1100_46FF",
        "semanticClass": "DSC_REGISTER_CONFIG_RETRY_CANDIDATE",
        "chineseName": "DSC注册/配置重试候选",
        "confidence": 0.75,
        "notes": ["只读逆向注释，未由厂商协议文档确认"],
    },
    "1f00d2ff": {
        "typeA": "1F00_D2FF",
        "semanticClass": "DSC_KEEPALIVE_OR_ACK_WAIT_CANDIDATE",
        "chineseName": "DSC短心跳/等待确认候选",
        "confidence": 0.7,
        "notes": ["ACK_WAIT_INFERRED 不是确认 ACK 状态，只是推断"],
    },
    "1180d2ff": {
        "typeA": "1180_D2FF",
        "semanticClass": "RDS_HEARTBEAT_OR_KEEPALIVE_CANDIDATE",
        "chineseName": "RDS心跳/保活候选",
        "confidence": 0.85,
        "notes": ["暂不判定为实时业务数据帧"],
    },
}


def _backend_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _raw_log_dir() -> Path:
    configured = Path(settings.fsu_raw_log_dir)
    if configured.is_absolute():
        return configured
    cwd_candidate = Path.cwd() / configured
    if cwd_candidate.exists():
        return cwd_candidate
    return _backend_root() / configured


def _raw_logs() -> list[Path]:
    raw_dir = _raw_log_dir()
    if not raw_dir.exists():
        return []
    return sorted(
        [item for item in raw_dir.iterdir() if item.is_file() and RAW_LOG_RE.match(item.name)],
        key=lambda item: item.name,
    )


def _count(counter: Counter[str], value: Any) -> None:
    counter[str(value) if value not in (None, "") else "(empty)"] += 1


def _hex_slice(buf: bytes, start: int, end: int) -> str:
    if start >= len(buf):
        return ""
    return buf[start : min(end, len(buf))].hex()


def _u16le(buf: bytes, offset: int) -> int | None:
    if offset + 1 >= len(buf):
        return None
    return int.from_bytes(buf[offset : offset + 2], "little")


def _classify(protocol: str | None, total_length: int, type_a: str) -> str:
    if protocol == "UDP_DSC" and total_length == 24 and type_a == "1f00d2ff":
        return "DSC_SHORT_24_TYPE_1F00_D2FF"
    if protocol == "UDP_DSC" and total_length == 209 and type_a == "110046ff":
        return "DSC_CONFIG_209_TYPE_1100_46FF"
    if protocol == "UDP_DSC" and total_length == 245 and type_a == "110046ff":
        return "DSC_CONFIG_245_TYPE_1100_46FF"
    if protocol == "UDP_RDS" and total_length == 30 and type_a == "1180d2ff":
        return "RDS_SHORT_30_TYPE_1180_D2FF"
    return "UNKNOWN"


def _ascii_spans(buf: bytes) -> list[dict[str, Any]]:
    spans: list[dict[str, Any]] = []
    for match in ASCII_RE.finditer(buf):
        text = match.group(0).decode("ascii", errors="ignore")
        spans.append(
            {
                "offsetStart": match.start(),
                "offsetEnd": match.end() - 1,
                "length": match.end() - match.start(),
                "text": text,
            }
        )
    return spans


def _parse_packet(row: dict[str, Any], source_file: str) -> dict[str, Any] | None:
    raw_hex = str(row.get("rawHex") or "").strip().lower()
    if not raw_hex or len(raw_hex) % 2 != 0 or not re.fullmatch(r"[0-9a-f]+", raw_hex):
        return None
    try:
        buf = bytes.fromhex(raw_hex)
    except ValueError:
        return None

    protocol = row.get("protocol")
    total_length = len(buf)
    type_a = _hex_slice(buf, 4, 8)
    frame_class = row.get("frameClass") or _classify(protocol, total_length, type_a)
    spans = _ascii_spans(buf)
    uris: list[str] = []
    for span in spans:
        uris.extend(URI_RE.findall(span["text"]))

    return {
        "sourceFile": source_file,
        "receivedAt": row.get("receivedAt"),
        "protocol": protocol,
        "remoteAddress": row.get("remoteAddress"),
        "remotePort": row.get("remotePort"),
        "localPort": row.get("localPort"),
        "length": row.get("length") or total_length,
        "rawHex": raw_hex,
        "frameClass": frame_class,
        "annotation": _frame_class_annotation(frame_class),
        "headerHex": _hex_slice(buf, 0, 2),
        "seqLE": _u16le(buf, 2),
        "seqLEHex": _hex_slice(buf, 2, 4),
        "typeA": type_a,
        "typeAAnnotation": _type_a_annotation(type_a),
        "lengthLE": _u16le(buf, 20),
        "checksumLE": _u16le(buf, 22),
        "bodyOffset": 24,
        "bodyLength": max(0, total_length - 24),
        "payloadLengthCandidate": _u16le(buf, 20),
        "uris": uris,
        "asciiSpans": spans[:20],
        "isUnknown": frame_class == "UNKNOWN",
    }


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _top(counter: Counter[str], limit: int = 20) -> list[dict[str, Any]]:
    return [{"value": key, "count": count} for key, count in counter.most_common(limit)]


def _frame_class_annotation(frame_class: Any) -> dict[str, Any] | None:
    annotation = FRAME_CLASS_ANNOTATIONS.get(str(frame_class))
    if not annotation:
        return None
    return dict(annotation)


def _type_a_annotation(type_a: Any) -> dict[str, Any] | None:
    annotation = TYPE_A_ANNOTATIONS.get(str(type_a or "").lower())
    if not annotation:
        return None
    return dict(annotation)


def _annotated_frame_class_top(counter: Counter[str], limit: int = 20) -> list[dict[str, Any]]:
    return [
        {
            "value": key,
            "count": count,
            "annotation": _frame_class_annotation(key),
        }
        for key, count in counter.most_common(limit)
    ]


def _annotated_type_a_top(counter: Counter[str], limit: int = 20) -> list[dict[str, Any]]:
    return [
        {
            "value": key,
            "count": count,
            "typeAAnnotation": _type_a_annotation(key),
        }
        for key, count in counter.most_common(limit)
    ]


def _annotated_type_length_top(counter: Counter[str], limit: int = 50) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key, count in counter.most_common(limit):
        parts = key.split("|")
        type_a = parts[1] if len(parts) >= 3 else ""
        rows.append(
            {
                "value": key,
                "count": count,
                "typeAAnnotation": _type_a_annotation(type_a),
            }
        )
    return rows


def _daily_reports() -> list[dict[str, Any]]:
    raw_dir = _raw_log_dir()
    reports: dict[str, dict[str, Any]] = {}
    if not raw_dir.exists():
        return []
    for item in raw_dir.iterdir():
        match = DAILY_REPORT_RE.match(item.name)
        if not item.is_file() or not match:
            continue
        date, suffix = match.groups()
        reports.setdefault(date, {"date": date})
        reports[date][suffix] = str(item)
    return [reports[key] for key in sorted(reports.keys(), reverse=True)]


def _sample(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "sourceFile": record.get("sourceFile"),
        "receivedAt": record.get("receivedAt"),
        "protocol": record.get("protocol"),
        "remoteAddress": record.get("remoteAddress"),
        "remotePort": record.get("remotePort"),
        "localPort": record.get("localPort"),
        "frameClass": record.get("frameClass"),
        "annotation": record.get("annotation"),
        "typeA": record.get("typeA"),
        "typeAAnnotation": record.get("typeAAnnotation"),
        "length": record.get("length"),
        "seqLEHex": record.get("seqLEHex"),
        "payloadLengthCandidate": record.get("payloadLengthCandidate"),
        "uris": record.get("uris", []),
        "asciiSpans": record.get("asciiSpans", [])[:5],
        "rawHex": record.get("rawHex"),
    }


def _latest_record(records: list[dict[str, Any]], protocol: str) -> dict[str, Any] | None:
    latest: tuple[datetime, dict[str, Any]] | None = None
    for record in records:
        if record.get("protocol") != protocol:
            continue
        parsed_time = _parse_time(record.get("receivedAt"))
        if not parsed_time:
            continue
        if latest is None or parsed_time > latest[0]:
            latest = (parsed_time, record)
    return latest[1] if latest else None


def _packet_status(record: dict[str, Any] | None, now_utc: datetime) -> dict[str, Any]:
    if not record:
        return {
            "lastSeenAt": None,
            "ageSeconds": None,
            "status": "no_data",
            "abnormal": True,
            "sample": None,
        }
    parsed_time = _parse_time(record.get("receivedAt"))
    age_seconds = int((now_utc - parsed_time).total_seconds()) if parsed_time else None
    abnormal = age_seconds is None or age_seconds > 60
    return {
        "lastSeenAt": record.get("receivedAt"),
        "ageSeconds": age_seconds,
        "status": "offline_or_abnormal" if abnormal else "online",
        "abnormal": abnormal,
        "sample": _sample(record),
    }


def _diagnostic_suggestions(
    records: list[dict[str, Any]],
    online_status: dict[str, Any],
    still_repeating_config: bool,
    last24_new_frames: bool,
    last24_business_candidates: list[dict[str, Any]],
    frame_class_counts: Counter[str],
) -> list[dict[str, Any]]:
    suggestions: list[dict[str, Any]] = []
    if not records:
        suggestions.append(
            {
                "code": "NO_PACKETS",
                "level": "danger",
                "title": "未收到包",
                "detail": "raw packet 日志中没有可解析记录。先确认 fsu-gateway 只读抓包进程和 UDP 监听状态。",
            }
        )
        return suggestions

    if online_status.get("overallStatus") != "online":
        suggestions.append(
            {
                "code": "OFFLINE_OR_STALE",
                "level": "warning",
                "title": "设备在线状态异常",
                "detail": "至少一个关键协议超过 60 秒无包或没有数据，建议先确认设备、网线、VPN/路由和监听端口。",
            }
        )

    known_short_count = frame_class_counts.get("DSC_SHORT_24_TYPE_1F00_D2FF", 0) + frame_class_counts.get(
        "RDS_SHORT_30_TYPE_1180_D2FF", 0
    )
    config_count = frame_class_counts.get("DSC_CONFIG_209_TYPE_1100_46FF", 0) + frame_class_counts.get(
        "DSC_CONFIG_245_TYPE_1100_46FF", 0
    )
    if known_short_count > 0 and config_count == 0:
        suggestions.append(
            {
                "code": "ONLY_SHORT_FRAMES",
                "level": "info",
                "title": "只收到短帧",
                "detail": "当前样本以 DSC/RDS 短帧为主，暂未看到配置长帧。继续只读观察端口和帧类型变化。",
            }
        )
    if still_repeating_config:
        suggestions.append(
            {
                "code": "REPEATING_CONFIG",
                "level": "warning",
                "title": "配置长帧重复",
                "detail": "最近 24 小时仍以 DSC_CONFIG_209/245 重复为主，设备可能仍处于登录/服务地址配置阶段。",
            }
        )
    if last24_new_frames:
        suggestions.append(
            {
                "code": "NEW_TYPE_OR_LENGTH",
                "level": "warning",
                "title": "出现新 typeA/length",
                "detail": "最近窗口发现新的 frameClass、typeA 或 length，建议导出 UNKNOWN 和新帧样本做离线分析。",
            }
        )
    if last24_business_candidates:
        suggestions.append(
            {
                "code": "BUSINESS_FRAME_CANDIDATE",
                "level": "success",
                "title": "出现疑似业务帧",
                "detail": "发现非已知短帧/配置帧或含明显 ASCII 的新帧，建议优先做只读解析和面板展示。",
            }
        )
    if not suggestions:
        suggestions.append(
            {
                "code": "OBSERVE",
                "level": "info",
                "title": "继续只读观察",
                "detail": "当前未发现新的业务阶段证据，也未触发明确异常；继续查看日报、UNKNOWN 和端口分布。",
            }
        )
    return suggestions


@router.get("/raw-packets")
def raw_packets_debug(
    max_records: int = Query(5000, ge=100, le=50000),
    recent_limit: int = Query(100, ge=1, le=500),
    _=Depends(permission_required("realtime.view")),
):
    logs = _raw_logs()
    retained: deque[dict[str, Any]] = deque(maxlen=max_records)
    parse_errors: list[dict[str, Any]] = []
    total_lines = 0

    for log_path in reversed(logs):
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        for line_number_from_end, line in enumerate(reversed(lines), start=1):
                if len(retained) >= max_records:
                    break
                if not line.strip():
                    continue
                total_lines += 1
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    parse_errors.append({"file": log_path.name, "lineFromEnd": line_number_from_end, "error": str(exc)})
                    continue
                parsed = _parse_packet(row, log_path.name)
                if parsed is not None:
                    retained.appendleft(parsed)
        if len(retained) >= max_records:
            break

    records = list(retained)
    frame_class_counts: Counter[str] = Counter()
    remote_port_counts: Counter[str] = Counter()
    protocol_remote_port_counts: dict[str, Counter[str]] = {"UDP_DSC": Counter(), "UDP_RDS": Counter()}
    type_a_counts: Counter[str] = Counter()
    length_counts: Counter[str] = Counter()
    seq_counts: Counter[str] = Counter()
    uri_counts: Counter[str] = Counter()
    type_length_counts: Counter[str] = Counter()
    unknown_examples: list[dict[str, Any]] = []
    non_standard_length_frames: list[dict[str, Any]] = []
    ascii_new_frames: list[dict[str, Any]] = []
    payload_length_anomalies: list[dict[str, Any]] = []
    business_frame_candidates: list[dict[str, Any]] = []
    dsc_config_samples: list[dict[str, Any]] = []

    latest_time: datetime | None = None
    for record in records:
        _count(frame_class_counts, record["frameClass"])
        _count(remote_port_counts, record["remotePort"])
        if record["protocol"] in protocol_remote_port_counts:
            _count(protocol_remote_port_counts[record["protocol"]], record["remotePort"])
        _count(type_a_counts, record["typeA"])
        _count(length_counts, record["length"])
        _count(seq_counts, record["seqLEHex"])
        _count(type_length_counts, f"{record['protocol']}|{record['typeA']}|{record['length']}")
        for uri in record["uris"]:
            _count(uri_counts, uri)
        if record["isUnknown"] and len(unknown_examples) < 20:
            unknown_examples.append(_sample(record))
        if record["frameClass"] in KNOWN_CONFIG_CLASSES and len(dsc_config_samples) < 50:
            dsc_config_samples.append(_sample(record))
        if int(record["length"] or 0) not in KNOWN_LENGTHS and len(non_standard_length_frames) < 100:
            non_standard_length_frames.append(_sample(record))
        if record.get("payloadLengthCandidate") is not None and record["payloadLengthCandidate"] != record["bodyLength"]:
            if len(payload_length_anomalies) < 100:
                payload_length_anomalies.append(_sample(record))
        has_ascii = any(span.get("length", 0) >= 8 for span in record.get("asciiSpans", []))
        if has_ascii and (record["isUnknown"] or int(record["length"] or 0) not in KNOWN_LENGTHS):
            if len(ascii_new_frames) < 100:
                ascii_new_frames.append(_sample(record))
        if (
            record["isUnknown"]
            or int(record["length"] or 0) not in KNOWN_LENGTHS
            or record["typeA"] not in {"1f00d2ff", "1180d2ff", "110046ff"}
            or (has_ascii and record["frameClass"] not in KNOWN_CONFIG_CLASSES)
        ):
            if len(business_frame_candidates) < 100:
                business_frame_candidates.append(
                    {
                        **_sample(record),
                        "reason": "unknown frameClass, non-standard length, or new typeA",
                    }
                )
        parsed_time = _parse_time(record["receivedAt"])
        if parsed_time and (latest_time is None or parsed_time > latest_time):
            latest_time = parsed_time

    trend_24h: dict[str, Counter[str]] = {}
    last_24h_cutoff = latest_time - timedelta(hours=24) if latest_time else None
    recent_cutoff = latest_time - timedelta(minutes=10) if latest_time else None
    previous_frame_classes: set[str] = set()
    recent_frame_classes: set[str] = set()
    previous_type_a: set[str] = set()
    recent_type_a: set[str] = set()
    previous_lengths: set[str] = set()
    recent_lengths: set[str] = set()
    last24_records: list[dict[str, Any]] = []
    for record in records:
        parsed_time = _parse_time(record["receivedAt"])
        if last_24h_cutoff and parsed_time and parsed_time >= last_24h_cutoff:
            last24_records.append(record)
        if last_24h_cutoff and parsed_time and parsed_time >= last_24h_cutoff:
            bucket = parsed_time.replace(minute=0, second=0, microsecond=0).isoformat()
            trend_24h.setdefault(bucket, Counter())
            _count(trend_24h[bucket], record["frameClass"])
        if recent_cutoff and parsed_time and parsed_time >= recent_cutoff:
            recent_frame_classes.add(record["frameClass"])
            recent_type_a.add(record["typeA"])
            recent_lengths.add(str(record["length"]))
        else:
            previous_frame_classes.add(record["frameClass"])
            previous_type_a.add(record["typeA"])
            previous_lengths.add(str(record["length"]))

    last24_config_count = sum(1 for item in last24_records if item["frameClass"] in KNOWN_CONFIG_CLASSES)
    last24_business_candidates = [
        item for item in business_frame_candidates if item.get("remoteAddress") != "127.0.0.1"
    ]
    last24_new_frames = bool(recent_frame_classes - previous_frame_classes or recent_type_a - previous_type_a or recent_lengths - previous_lengths)
    still_repeating_config = last24_config_count >= 10 and not last24_business_candidates
    now_utc = datetime.now(timezone.utc)
    online_status = {
        "thresholdSeconds": 60,
        "UDP_DSC": _packet_status(_latest_record(records, "UDP_DSC"), now_utc),
        "UDP_RDS": _packet_status(_latest_record(records, "UDP_RDS"), now_utc),
        "HTTP_SOAP": _packet_status(_latest_record(records, "HTTP_SOAP"), now_utc),
    }
    online_status["overallStatus"] = (
        "online"
        if online_status["UDP_DSC"]["status"] == "online" or online_status["UDP_RDS"]["status"] == "online"
        else "offline_or_abnormal"
    )
    daily_reports = _daily_reports()
    diagnostic_suggestions = _diagnostic_suggestions(
        records,
        online_status,
        still_repeating_config,
        last24_new_frames,
        last24_business_candidates,
        frame_class_counts,
    )
    recent_packets = records[-recent_limit:][::-1]
    export_bundles = {
        "recentRawPackets": {
            "filename": "fsu-recent-100-raw-packets.json",
            "records": recent_packets,
        },
        "latestDailyReports": {
            "filename": "fsu-latest-daily-reports.json",
            "records": daily_reports[:7],
        },
        "unknownSamples": {
            "filename": "fsu-unknown-samples.json",
            "records": unknown_examples,
        },
        "dscConfigSamples": {
            "filename": "fsu-dsc-config-samples.json",
            "records": dsc_config_samples[:100],
        },
    }

    return {
        "notice": "只读 FSU 接入诊断页：当前协议解析为逆向分析结果，候选 ACK 未确认，线上回包未启用。",
        "safety": {
            "readOnly": True,
            "udpSendEnabled": False,
            "autoAckEnabled": False,
            "businessTableWrites": False,
        },
        "rawLogDir": str(_raw_log_dir()),
        "logs": [{"name": item.name, "path": str(item), "size": item.stat().st_size} for item in logs],
        "totalRawLinesScanned": total_lines,
        "recordsRetained": len(records),
        "maxRecords": max_records,
        "parseErrors": parse_errors[:50],
        "summary": {
            "frameClass": _annotated_frame_class_top(frame_class_counts),
            "remotePort": _top(remote_port_counts),
            "protocolRemotePort": {
                key: _top(value) for key, value in protocol_remote_port_counts.items()
            },
            "typeA": _annotated_type_a_top(type_a_counts),
            "length": _top(length_counts),
            "typeALength": _annotated_type_length_top(type_length_counts, 50),
            "seqLE": _top(seq_counts),
            "uri": _top(uri_counts),
            "unknownCount": frame_class_counts.get("UNKNOWN", 0),
            "newFrameClassesInLast10Minutes": sorted(recent_frame_classes - previous_frame_classes),
            "newTypeAInLast10Minutes": sorted(recent_type_a - previous_type_a),
            "newLengthsInLast10Minutes": sorted(recent_lengths - previous_lengths),
            "frameClassTrend24h": [
                {"hour": hour, "frameClass": _top(counter, 50)}
                for hour, counter in sorted(trend_24h.items())
            ],
        },
        "dailyReports": daily_reports,
        "onlineStatus": online_status,
        "currentDeviceStage": {
            "stillLoginConfigRepeatStage": still_repeating_config,
            "businessDataStageSignals": bool(last24_business_candidates),
            "abnormalSignals": bool(unknown_examples or payload_length_anomalies or online_status["overallStatus"] != "online"),
            "summary": (
                "最近 24 小时仍以 DSC_CONFIG 重复和短帧为主，未发现确认的业务数据阶段。"
                if still_repeating_config
                else "最近 24 小时未满足持续配置长帧重复阶段判定，需结合日志继续观察。"
            ),
        },
        "last24hSignals": {
            "hasNewFrame": last24_new_frames,
            "hasBusinessFrameCandidate": bool(last24_business_candidates),
            "stillRepeatingConfigLongFrames": still_repeating_config,
            "dscConfigCount": last24_config_count,
        },
        "unknownExamples": unknown_examples,
        "nonStandardLengthFrames": non_standard_length_frames,
        "asciiNewFrames": ascii_new_frames,
        "payloadLengthAnomalies": payload_length_anomalies,
        "businessFrameCandidates": business_frame_candidates,
        "dscConfigSamples": dsc_config_samples[:100],
        "diagnosticSuggestions": diagnostic_suggestions,
        "exportBundles": export_bundles,
        "recentPackets": recent_packets,
    }
