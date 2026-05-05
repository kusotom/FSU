from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from app.core.config import settings
from app.modules.b_interface.alarm_store import list_alarm_history, list_current_alarms, list_recent_alarms
from app.modules.b_interface.client import (
    build_fsu_service_endpoint,
    build_all_devices_code,
    build_get_data_xml,
    build_get_hisdata_xml,
    build_invoke_soap,
    build_get_fsuinfo_xml,
    build_get_logininfo_xml,
    build_time_check_xml,
    perform_outbound_call,
)
from app.modules.b_interface.history_store import list_history, parse_get_hisdata_ack, save_history_values
from app.modules.b_interface.info_store import (
    get_latest_fsuinfo,
    get_latest_logininfo,
    parse_get_fsuinfo_ack,
    parse_get_logininfo_ack,
    save_fsuinfo_ack,
    save_logininfo_ack,
)
from app.modules.b_interface.outbound_store import get_outbound_call, list_outbound_calls, record_outbound_call
from app.modules.b_interface.realtime_store import list_realtime, parse_get_data_ack, save_realtime_values
from app.modules.b_interface.status_store import get_fsu_status, get_latest_login_status, list_fsu_statuses
from app.modules.b_interface.xml_protocol import parse_b_interface_xml


router = APIRouter(prefix="/api/b-interface", tags=["b-interface"])
JSONL_RE = re.compile(r"^soap-invoke-\d{4}-\d{2}-\d{2}\.jsonl$")


class FSUActionRequest(BaseModel):
    dry_run: bool | None = Field(default=None)
    timeout_seconds: float | None = Field(default=None, ge=0.1, le=60.0)
    endpoint: str | None = Field(default=None)
    all_devices: bool = Field(default=False)
    device_list: list[str] | None = Field(default=None)
    device_id: str | None = Field(default=None)
    device_code: str | None = Field(default=None)
    start_time: str | None = Field(default=None)
    end_time: str | None = Field(default=None)
    max_records: int | None = Field(default=None, ge=1, le=20000)


def _backend_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _b_interface_log_dir() -> Path:
    configured = Path(settings.b_interface_log_dir)
    if configured.is_absolute():
        return configured
    cwd_candidate = Path.cwd() / configured
    if cwd_candidate.exists():
        return cwd_candidate
    return _backend_root() / configured


def _samples_dir() -> Path:
    return _b_interface_log_dir() / "samples"


def _log_files() -> list[Path]:
    log_dir = _b_interface_log_dir()
    if not log_dir.exists():
        return []
    return sorted(
        [item for item in log_dir.iterdir() if item.is_file() and JSONL_RE.match(item.name)],
        key=lambda item: item.name,
        reverse=True,
    )


def _read_recent_records(limit: int) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for log_path in _log_files():
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        for line in reversed(lines):
            if len(records) >= limit:
                return records
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            records.append(row)
    return records


def _filter_records(
    rows: list[dict[str, Any]],
    *,
    command_name: str | None = None,
    direction: str | None = None,
    blocked: bool | None = None,
) -> list[dict[str, Any]]:
    filtered = rows
    if command_name:
        filtered = [row for row in filtered if str(row.get("command_name") or "").upper() == command_name.upper()]
    if direction:
        filtered = [row for row in filtered if str(row.get("direction") or "").upper() == direction.upper()]
    if blocked is not None:
        filtered = [row for row in filtered if row.get("blocked") is blocked]
    return filtered


def _latest_record_by_message(message_name: str) -> dict[str, Any] | None:
    for row in _read_recent_records(1000):
        if str(row.get("message_name") or "").upper() == message_name.upper():
            return row
    return None


def _parse_record_xml(row: dict[str, Any]) -> Any:
    xml_text = str(row.get("extracted_xmlData_sanitized") or "").strip()
    if not xml_text:
        return None
    try:
        return parse_b_interface_xml(xml_text)
    except Exception:
        return None


def _fsu_action_context(fsu_id: str) -> dict[str, Any]:
    row = get_fsu_status(fsu_id)
    if row is None:
        raise HTTPException(status_code=404, detail="FSU not found")
    fsu_code = row.get("fsu_code") or row.get("fsu_id") or fsu_id
    fsu_ip = row.get("fsu_ip") or ""
    endpoint = build_fsu_service_endpoint(fsu_ip) if fsu_ip else ""
    return {
        "status": row,
        "fsu_id": row.get("fsu_id") or fsu_id,
        "fsu_code": fsu_code,
        "device_list": list(row.get("device_list") or []),
        "endpoint": endpoint,
    }


def _run_fsu_action(fsu_id: str, action_name: str, xml_data: str, payload: FSUActionRequest) -> dict[str, Any]:
    context = _fsu_action_context(fsu_id)
    endpoint = payload.endpoint or context["endpoint"]
    outbound = perform_outbound_call(
        action=action_name,
        fsu_id=context["fsu_id"],
        fsu_code=context["fsu_code"],
        endpoint=endpoint,
        xml_data=xml_data,
        dry_run=bool(payload.dry_run),
        timeout_seconds=payload.timeout_seconds,
    )
    audit = record_outbound_call(outbound)
    return {
        "call_id": audit["call_id"],
        "ok": outbound.ok,
        "dry_run": outbound.dry_run,
        "action": outbound.action,
        "fsu_id": outbound.fsu_id,
        "fsu_code": outbound.fsu_code,
        "endpoint": outbound.endpoint,
        "request_xml": outbound.request_xml,
        "xmlData": outbound.xmlData,
        "request_xml_sanitized": outbound.request_xml_sanitized,
        "soap_request": outbound.soap_request,
        "soap_request_sanitized": outbound.soap_request_sanitized,
        "http_status": outbound.http_status,
        "response_text_sanitized": outbound.response_text_sanitized,
        "invoke_return": outbound.invoke_return,
        "invoke_return_sanitized": outbound.invoke_return_sanitized,
        "business_name": outbound.business_name,
        "business_code": outbound.business_code,
        "error_type": outbound.error_type,
        "error_message": outbound.error_message,
        "elapsed_ms": outbound.elapsed_ms,
        "created_at": outbound.created_at,
    }


def _merged_action_payload(dry_run: bool, payload: FSUActionRequest | None) -> FSUActionRequest:
    if payload is None:
        return FSUActionRequest(dry_run=dry_run)
    data = payload.model_dump()
    data["dry_run"] = dry_run if payload.dry_run is None else payload.dry_run
    return FSUActionRequest(**data)


def _parse_request_time(value: str | None, fallback: datetime | None = None) -> datetime:
    text = (value or "").strip()
    if not text:
        return fallback or datetime.now(timezone.utc)
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y/%m/%d %H:%M:%S", "%Y%m%d%H%M%S"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError as exc:
        raise ValueError(f"invalid time format: {value}") from exc


def _format_request_time(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _hisdata_invalid_result(fsu_id: str, action: str, endpoint: str, message: str) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "call_id": "",
        "ok": False,
        "dry_run": True,
        "action": action.lower(),
        "fsu_id": fsu_id,
        "fsu_code": fsu_id,
        "endpoint": endpoint,
        "request_xml": "",
        "xmlData": "",
        "request_xml_sanitized": "",
        "soap_request": "",
        "soap_request_sanitized": "",
        "http_status": None,
        "response_text_sanitized": "",
        "invoke_return": "",
        "invoke_return_sanitized": "",
        "business_name": "",
        "business_code": "",
        "error_type": "invalid_time_range",
        "error_message": message,
        "elapsed_ms": 0,
        "created_at": now,
    }


@router.get("/messages")
def list_messages(limit: int = Query(50, ge=1, le=500)):
    rows = _read_recent_records(limit)
    return [
        {
            "timestamp": row.get("timestamp"),
            "remote_addr": row.get("remote_addr"),
            "message_name": row.get("message_name"),
            "message_code": row.get("message_code"),
            "fsu_id": row.get("fsu_id"),
            "fsu_code": row.get("fsu_code"),
            "alarm_count": row.get("alarm_count", 0),
            "parse_ok": row.get("parse_ok"),
            "error": row.get("error"),
        }
        for row in rows
    ]


@router.get("/logs")
def list_logs(
    limit: int = Query(50, ge=1, le=500),
    command_name: str | None = Query(default=None),
    direction: str | None = Query(default=None),
    blocked: bool | None = Query(default=None),
):
    rows = _filter_records(_read_recent_records(limit=1000), command_name=command_name, direction=direction, blocked=blocked)
    return rows[:limit]


@router.get("/overview")
def overview():
    latest_login = get_latest_login_status()
    current_alarms = list_current_alarms(1000)
    history_alarms = list_alarm_history(1000)
    realtime_rows = list_realtime(limit=1000)
    return {
        "fsu_count": len(list_fsu_statuses(1000)),
        "latest_login": {
            "fsu_id": latest_login["fsu_id"],
            "fsu_code": latest_login["fsu_code"],
            "fsu_ip": latest_login["fsu_ip"],
            "last_login_at": latest_login["last_login_at"],
        } if latest_login is not None else None,
        "current_alarm_count": len(current_alarms),
        "history_alarm_count": len(history_alarms),
        "realtime_count": len(realtime_rows),
        "sample_count": len(list_samples()),
        "recent_messages": list_messages(limit=10),
    }


@router.get("/latest-login")
def latest_login():
    row = get_latest_login_status()
    if row is None:
        raise HTTPException(status_code=404, detail="no LOGIN record found")
    return {
        "FsuId": row["fsu_id"],
        "FsuCode": row["fsu_code"],
        "FsuIP": row["fsu_ip"],
        "MacId": row["mac_id"],
        "RegMode": row["reg_mode"],
        "FSUVendor": row["fsu_vendor"],
        "FSUType": row["fsu_type"],
        "FSUClass": row["fsu_class"],
        "Version": row["version"],
        "DictVersion": row["dict_version"],
        "DeviceList": [
            {"Id": device_code, "Code": device_code}
            for device_code in row["device_list"]
        ],
    }


@router.get("/fsus")
def list_fsus(limit: int = Query(100, ge=1, le=500)):
    return list_fsu_statuses(limit)


@router.get("/fsus/{fsu_id}")
def get_fsu(fsu_id: str):
    row = get_fsu_status(fsu_id)
    if row is None:
        raise HTTPException(status_code=404, detail="FSU not found")
    return row


@router.get("/fsus/{fsu_id}/fsuinfo")
def fsu_info(fsu_id: str):
    row = get_latest_fsuinfo(fsu_id)
    if row is None:
        raise HTTPException(status_code=404, detail="FSU info not found")
    return row


@router.get("/fsus/{fsu_id}/logininfo")
def fsu_logininfo(fsu_id: str):
    row = get_latest_logininfo(fsu_id)
    if row is None:
        raise HTTPException(status_code=404, detail="FSU login info not found")
    return row


@router.post("/fsus/{fsu_id}/actions/get-data")
def fsu_action_get_data(
    fsu_id: str,
    dry_run: bool = Query(True),
    payload: FSUActionRequest | None = None,
):
    context = _fsu_action_context(fsu_id)
    resolved = _merged_action_payload(dry_run, payload)
    if resolved.all_devices:
        seed = context["device_list"][0] if context["device_list"] else context["fsu_code"]
        device_list = [build_all_devices_code(seed)]
    elif resolved.device_list:
        device_list = resolved.device_list
    else:
        device_list = context["device_list"]
    xml_data = build_get_data_xml(context["fsu_id"], context["fsu_code"], device_list)
    result = _run_fsu_action(fsu_id, "GET_DATA", xml_data, resolved)
    if not resolved.dry_run and result.get("ok") and result.get("invoke_return"):
        try:
            values = parse_get_data_ack(str(result["invoke_return"]))
            saved = save_realtime_values(values)
            result["realtime_count"] = len(saved)
        except Exception as exc:
            result.update({"ok": False, "error_type": "parse_error", "error_message": str(exc)})
    return result


@router.post("/fsus/{fsu_id}/actions/get-hisdata")
def fsu_action_get_hisdata(fsu_id: str, dry_run: bool = Query(True), payload: FSUActionRequest | None = None):
    context = _fsu_action_context(fsu_id)
    resolved = _merged_action_payload(dry_run, payload)
    now = datetime.now(timezone.utc)
    end_dt = _parse_request_time(resolved.end_time, fallback=now)
    start_dt = _parse_request_time(resolved.start_time, fallback=end_dt - timedelta(hours=1))
    if start_dt >= end_dt:
        return _hisdata_invalid_result(context["fsu_id"], "GET_HISDATA", resolved.endpoint or context["endpoint"], "start_time must be earlier than end_time")
    if end_dt - start_dt > timedelta(hours=24):
        return _hisdata_invalid_result(context["fsu_id"], "GET_HISDATA", resolved.endpoint or context["endpoint"], "time range exceeds 24 hours")
    if resolved.device_id or resolved.device_code:
        device_key = resolved.device_code or resolved.device_id or ""
        device_list = [device_key]
    elif resolved.all_devices:
        seed = context["device_list"][0] if context["device_list"] else context["fsu_code"]
        device_list = [build_all_devices_code(seed)]
    elif resolved.device_list:
        device_list = resolved.device_list
    else:
        device_list = context["device_list"]
    xml_data = build_get_hisdata_xml(
        context["fsu_id"],
        context["fsu_code"],
        device_list,
        _format_request_time(start_dt),
        _format_request_time(end_dt),
    )
    result = _run_fsu_action(fsu_id, "GET_HISDATA", xml_data, resolved)
    result["time_range"] = {"start_time": _format_request_time(start_dt), "end_time": _format_request_time(end_dt)}
    result["device_list"] = device_list
    result["max_records"] = resolved.max_records or 5000
    if not resolved.dry_run and result.get("ok") and result.get("invoke_return"):
        try:
            values = parse_get_hisdata_ack(str(result["invoke_return"]), max_records=resolved.max_records or 5000)
            saved = save_history_values(values, source_call_id=str(result.get("call_id") or ""))
            result["history_count"] = len(saved)
        except Exception as exc:
            result.update({"ok": False, "error_type": "parse_error", "error_message": str(exc)})
    return result


@router.post("/fsus/{fsu_id}/actions/time-check")
def fsu_action_time_check(fsu_id: str, dry_run: bool = Query(True), payload: FSUActionRequest | None = None):
    context = _fsu_action_context(fsu_id)
    xml_data = build_time_check_xml(context["fsu_id"], context["fsu_code"])
    return _run_fsu_action(fsu_id, "TIME_CHECK", xml_data, _merged_action_payload(dry_run, payload))


@router.post("/fsus/{fsu_id}/actions/get-fsuinfo")
def fsu_action_get_fsuinfo(fsu_id: str, dry_run: bool = Query(True), payload: FSUActionRequest | None = None):
    context = _fsu_action_context(fsu_id)
    xml_data = build_get_fsuinfo_xml(context["fsu_id"], context["fsu_code"])
    result = _run_fsu_action(fsu_id, "GET_FSUINFO", xml_data, _merged_action_payload(dry_run, payload))
    if not result.get("dry_run") and result.get("ok") and result.get("invoke_return"):
        try:
            parsed = parse_get_fsuinfo_ack(str(result["invoke_return"]))
            result["parsed"] = save_fsuinfo_ack(parsed)
        except Exception as exc:
            result.update({"ok": False, "error_type": "parse_error", "error_message": str(exc)})
    return result


@router.post("/fsus/{fsu_id}/actions/get-logininfo")
def fsu_action_get_logininfo(fsu_id: str, dry_run: bool = Query(True), payload: FSUActionRequest | None = None):
    context = _fsu_action_context(fsu_id)
    xml_data = build_get_logininfo_xml(context["fsu_id"], context["fsu_code"])
    result = _run_fsu_action(fsu_id, "GET_LOGININFO", xml_data, _merged_action_payload(dry_run, payload))
    if not result.get("dry_run") and result.get("ok") and result.get("invoke_return"):
        try:
            parsed = parse_get_logininfo_ack(str(result["invoke_return"]))
            result["parsed"] = save_logininfo_ack(parsed)
        except Exception as exc:
            result.update({"ok": False, "error_type": "parse_error", "error_message": str(exc)})
    return result


@router.get("/outbound-calls")
def outbound_calls(
    limit: int = Query(50, ge=1, le=500),
    fsu_id: str | None = Query(default=None),
    action: str | None = Query(default=None),
    error_type: str | None = Query(default=None),
):
    return list_outbound_calls(limit=limit, fsu_id=fsu_id, action=action, error_type=error_type)


@router.get("/outbound-calls/{call_id}")
def outbound_call_detail(call_id: str):
    row = get_outbound_call(call_id)
    if row is None:
        raise HTTPException(status_code=404, detail="outbound call not found")
    return row


@router.get("/fsus/{fsu_id}/realtime")
def fsu_realtime(fsu_id: str, limit: int = Query(100, ge=1, le=1000)):
    return list_realtime(limit=limit, fsu_id=fsu_id)


@router.get("/realtime")
def realtime(
    fsu_id: str | None = Query(default=None),
    device_id: str | None = Query(default=None),
    limit: int = Query(100, ge=1, le=1000),
):
    return list_realtime(limit=limit, fsu_id=fsu_id, device_id=device_id)


@router.get("/fsus/{fsu_id}/history")
def fsu_history(
    fsu_id: str,
    device_id: str | None = Query(default=None),
    semaphore_id: str | None = Query(default=None),
    start_time: str | None = Query(default=None),
    end_time: str | None = Query(default=None),
    mapping_status: str | None = Query(default=None),
    limit: int = Query(500, ge=1, le=5000),
):
    return list_history(
        limit=limit,
        fsu_id=fsu_id,
        device_id=device_id,
        semaphore_id=semaphore_id,
        mapping_status=mapping_status,
        start_time=_parse_request_time(start_time) if start_time else None,
        end_time=_parse_request_time(end_time) if end_time else None,
    )


@router.get("/history")
def history(
    fsu_id: str | None = Query(default=None),
    device_id: str | None = Query(default=None),
    semaphore_id: str | None = Query(default=None),
    start_time: str | None = Query(default=None),
    end_time: str | None = Query(default=None),
    mapping_status: str | None = Query(default=None),
    limit: int = Query(500, ge=1, le=5000),
):
    return list_history(
        limit=limit,
        fsu_id=fsu_id,
        device_id=device_id,
        semaphore_id=semaphore_id,
        mapping_status=mapping_status,
        start_time=_parse_request_time(start_time) if start_time else None,
        end_time=_parse_request_time(end_time) if end_time else None,
    )


@router.get("/alarms")
def latest_alarms(limit: int = Query(100, ge=1, le=500)):
    return list_recent_alarms(limit)


@router.get("/alarms/current")
def current_alarms(limit: int = Query(100, ge=1, le=500)):
    return list_current_alarms(limit)


@router.get("/alarms/history")
def history_alarms(limit: int = Query(100, ge=1, le=500)):
    return list_alarm_history(limit)


@router.get("/samples")
def list_samples():
    samples_dir = _samples_dir()
    if not samples_dir.exists():
        return []
    rows: list[dict[str, Any]] = []
    for item in sorted(samples_dir.iterdir(), key=lambda path: path.stat().st_mtime, reverse=True):
        if not item.is_file() or item.suffix.lower() != ".xml":
            continue
        parts = item.stem.split("-", 3)
        message_name = parts[3] if len(parts) >= 4 else ""
        rows.append(
            {
                "filename": item.name,
                "modified_at": datetime.fromtimestamp(item.stat().st_mtime).isoformat(),
                "size": item.stat().st_size,
                "message_name": message_name,
            }
        )
    return rows


@router.get("/samples/{filename:path}")
def get_sample(filename: str):
    sample_name = Path(filename).name
    if sample_name != filename or Path(filename).suffix.lower() != ".xml":
        raise HTTPException(status_code=400, detail="invalid sample filename")
    target = (_samples_dir() / sample_name).resolve()
    samples_root = _samples_dir().resolve()
    if target.parent != samples_root:
        raise HTTPException(status_code=400, detail="invalid sample path")
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="sample not found")
    return PlainTextResponse(target.read_text(encoding="utf-8", errors="replace"), media_type="application/xml")
