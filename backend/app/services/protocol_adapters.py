import json
from collections.abc import Callable
from datetime import datetime, timezone

from app.schemas.telemetry import MetricItem, TelemetryIngestRequest

# Optional mapping for vendor specific point ids.
ESTONE_POINT_MAP: dict[str, tuple[str, str, str, str | None]] = {
    "A0101": ("mains_voltage", "\u5e02\u7535\u7535\u538b", "power", "V"),
    "E0001": ("room_temp", "\u673a\u623f\u6e29\u5ea6", "env", "C"),
    "E0002": ("room_humidity", "\u673a\u623f\u6e7f\u5ea6", "env", "%"),
}
PayloadAdapter = Callable[[dict], TelemetryIngestRequest]
DTU_PAYLOAD_ADAPTERS: dict[str, PayloadAdapter] = {}


def _pick(payload: dict, *keys: str):
    for key in keys:
        if key in payload and payload[key] is not None:
            return payload[key]
    return None


def _to_datetime(value) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            if value.endswith("Z"):
                value = value[:-1] + "+00:00"
            return datetime.fromisoformat(value)
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def _normalize_protocol_name(value: str) -> str:
    return value.strip().lower().replace("-", "_")


def _parse_metric_list(
    raw_metrics,
    *,
    point_map: dict[str, tuple[str, str, str, str | None]] | None = None,
    default_category: str = "power",
) -> list[MetricItem]:
    metrics: list[MetricItem] = []
    if not isinstance(raw_metrics, list):
        return metrics

    for item in raw_metrics:
        if not isinstance(item, dict):
            continue
        raw_key = str(_pick(item, "key", "metric_key", "point_key", "pointKey", "id") or "").strip()
        if not raw_key:
            continue
        value = _pick(item, "value", "v", "val")
        if value is None:
            continue
        try:
            metric_value = float(value)
        except (TypeError, ValueError):
            continue
        mapped = point_map.get(raw_key) if point_map else None
        metrics.append(
            MetricItem(
                key=mapped[0] if mapped else raw_key,
                name=str(
                    _pick(item, "name", "metric_name", "point_name", "pointName")
                    or (mapped[1] if mapped else raw_key)
                ),
                value=metric_value,
                unit=str(_pick(item, "unit", "u") or (mapped[3] if mapped else "") or "") or None,
                category=str(_pick(item, "category", "cat") or (mapped[2] if mapped else default_category)),
            )
        )
    return metrics


def _parse_point_dict(
    raw_points,
    *,
    point_map: dict[str, tuple[str, str, str, str | None]] | None = None,
    default_category: str = "power",
) -> list[MetricItem]:
    metrics: list[MetricItem] = []
    if not isinstance(raw_points, dict):
        return metrics

    for raw_key, raw_value in raw_points.items():
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            continue
        raw_key_text = str(raw_key).strip()
        mapped = point_map.get(raw_key_text) if point_map else None
        key = mapped[0] if mapped else raw_key_text.lower()
        if not key:
            continue
        metrics.append(
            MetricItem(
                key=key,
                name=mapped[1] if mapped else raw_key_text,
                value=value,
                unit=mapped[3] if mapped else None,
                category=mapped[2] if mapped else default_category,
            )
        )
    return metrics


def _normalize_generic_payload(
    payload: dict,
    *,
    default_site_code: str = "UNKNOWN-SITE",
    default_fsu_code: str = "UNKNOWN-FSU",
    default_category: str = "power",
) -> TelemetryIngestRequest:
    site_code = str(
        _pick(
            payload,
            "site_code",
            "siteCode",
            "station_code",
            "stationCode",
        )
        or default_site_code
    )
    site_name = str(
        _pick(
            payload,
            "site_name",
            "siteName",
            "station_name",
            "stationName",
        )
        or site_code
    )
    fsu_code = str(_pick(payload, "fsu_code", "fsuCode", "device_code", "deviceCode") or default_fsu_code)
    fsu_name = str(_pick(payload, "fsu_name", "fsuName", "device_name", "deviceName") or fsu_code)
    collected_at = _to_datetime(_pick(payload, "collected_at", "collectedAt", "timestamp", "ts", "received_at"))

    metrics = _parse_metric_list(_pick(payload, "metrics", "signals"), default_category=default_category)
    if not metrics:
        metrics = _parse_point_dict(
            _pick(payload, "points", "data", "point_values", "pointValues"),
            default_category=default_category,
        )

    if not metrics:
        raise ValueError("\u672a\u5728\u4e0a\u62a5\u6570\u636e\u4e2d\u627e\u5230\u53ef\u89e3\u6790\u7684\u76d1\u63a7\u9879")

    return TelemetryIngestRequest(
        site_code=site_code,
        site_name=site_name,
        fsu_code=fsu_code,
        fsu_name=fsu_name,
        collected_at=collected_at,
        metrics=metrics,
    )


def _extract_dtu_payload_object(payload: dict) -> dict:
    nested = _pick(payload, "data", "payload", "body")
    if isinstance(nested, dict):
        merged = dict(payload)
        merged.update(nested)
        return merged

    payload_text = _pick(payload, "payload_text", "payloadText", "text", "raw_text", "rawText")
    if isinstance(payload_text, str) and payload_text.strip():
        try:
            parsed = json.loads(payload_text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"DTU payload_text \u4e0d\u662f\u5408\u6cd5 JSON: {exc}") from exc
        if not isinstance(parsed, dict):
            raise ValueError("DTU payload_text \u89e3\u6790\u540e\u5fc5\u987b\u662f JSON \u5bf9\u8c61")
        return parsed

    payload_hex = _pick(payload, "payload_hex", "payloadHex", "hex", "raw_hex", "rawHex")
    if isinstance(payload_hex, str) and payload_hex.strip():
        try:
            raw = bytes.fromhex(payload_hex.strip())
        except ValueError as exc:
            raise ValueError(f"DTU payload_hex \u4e0d\u662f\u5408\u6cd5\u5341\u516d\u8fdb\u5236: {exc}") from exc
        try:
            payload_text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("DTU payload_hex \u4e0d\u662f UTF-8 JSON\uff0c\u8bf7\u4e3a\u8be5\u534f\u8bae\u6ce8\u518c\u5355\u72ec\u89e3\u6790\u5668") from exc
        try:
            parsed = json.loads(payload_text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"DTU payload_hex \u89e3\u7801\u540e\u4e0d\u662f\u5408\u6cd5 JSON: {exc}") from exc
        if not isinstance(parsed, dict):
            raise ValueError("DTU payload_hex \u89e3\u7801\u540e\u5fc5\u987b\u662f JSON \u5bf9\u8c61")
        return parsed

    return payload


def _normalize_json_line_payload(payload: dict) -> TelemetryIngestRequest:
    inner = _extract_dtu_payload_object(payload)
    adapter_hint = str(_pick(inner, "protocol", "adapter", "vendor", "vendor_protocol") or "").strip()
    normalized_hint = _normalize_protocol_name(adapter_hint) if adapter_hint else ""
    if normalized_hint in {"estone", "e_stone", "estone_json"}:
        return normalize_estone_payload(inner)
    if {"site_code", "site_name", "fsu_code", "fsu_name", "collected_at", "metrics"}.issubset(inner):
        return TelemetryIngestRequest.model_validate(inner)
    return _normalize_generic_payload(inner)


def _normalize_estone_json_payload(payload: dict) -> TelemetryIngestRequest:
    return normalize_estone_payload(_extract_dtu_payload_object(payload))


def register_dtu_payload_adapter(name: str, adapter: PayloadAdapter):
    DTU_PAYLOAD_ADAPTERS[_normalize_protocol_name(name)] = adapter


def get_dtu_payload_adapter_names() -> list[str]:
    return sorted(DTU_PAYLOAD_ADAPTERS)


def normalize_estone_payload(payload: dict) -> TelemetryIngestRequest:
    normalized = _normalize_generic_payload(payload)
    metric_names_by_key = {item.key: item.name for item in normalized.metrics}
    metrics = _parse_metric_list(_pick(payload, "metrics"), point_map=ESTONE_POINT_MAP)
    if not metrics:
        metrics = _parse_point_dict(_pick(payload, "points", "data", "point_values", "pointValues"), point_map=ESTONE_POINT_MAP)
    if not metrics:
        raise ValueError("\u672a\u5728e-stone\u4e0a\u62a5\u6570\u636e\u4e2d\u627e\u5230\u76d1\u63a7\u9879")
    return TelemetryIngestRequest(
        site_code=normalized.site_code,
        site_name=normalized.site_name,
        fsu_code=normalized.fsu_code,
        fsu_name=normalized.fsu_name,
        collected_at=normalized.collected_at,
        metrics=[
            MetricItem(
                key=item.key,
                name=item.name or metric_names_by_key.get(item.key, item.key),
                value=item.value,
                unit=item.unit,
                category=item.category,
            )
            for item in metrics
        ],
    )


def normalize_dtu_payload(payload: dict) -> TelemetryIngestRequest:
    protocol = str(_pick(payload, "protocol", "adapter", "parser", "dtu_protocol") or "json_line")
    adapter = DTU_PAYLOAD_ADAPTERS.get(_normalize_protocol_name(protocol))
    if adapter is None:
        supported = ", ".join(get_dtu_payload_adapter_names()) or "none"
        raise ValueError(f"\u4e0d\u652f\u6301\u7684 DTU \u534f\u8bae={protocol}\uff0c\u53ef\u7528\u89e3\u6790\u5668: {supported}")
    return adapter(payload)


register_dtu_payload_adapter("json_line", _normalize_json_line_payload)
register_dtu_payload_adapter("json", _normalize_json_line_payload)
register_dtu_payload_adapter("telemetry_json", _normalize_json_line_payload)
register_dtu_payload_adapter("estone_json", _normalize_estone_json_payload)
