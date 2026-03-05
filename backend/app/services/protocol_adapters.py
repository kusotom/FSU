from datetime import datetime, timezone

from app.schemas.telemetry import MetricItem, TelemetryIngestRequest

# Optional mapping for vendor specific point ids.
ESTONE_POINT_MAP: dict[str, tuple[str, str, str, str | None]] = {
    "A0101": ("mains_voltage", "\u5e02\u7535\u7535\u538b", "power", "V"),
    "E0001": ("room_temp", "\u673a\u623f\u6e29\u5ea6", "env", "C"),
    "E0002": ("room_humidity", "\u673a\u623f\u6e7f\u5ea6", "env", "%"),
}


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


def normalize_estone_payload(payload: dict) -> TelemetryIngestRequest:
    site_code = str(
        _pick(
            payload,
            "site_code",
            "siteCode",
            "station_code",
            "stationCode",
        )
        or "UNKNOWN-SITE"
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
    fsu_code = str(_pick(payload, "fsu_code", "fsuCode", "device_code", "deviceCode") or "UNKNOWN-FSU")
    fsu_name = str(_pick(payload, "fsu_name", "fsuName", "device_name", "deviceName") or fsu_code)
    collected_at = _to_datetime(_pick(payload, "collected_at", "collectedAt", "timestamp", "ts"))

    metrics: list[MetricItem] = []
    raw_metrics = _pick(payload, "metrics")
    if isinstance(raw_metrics, list):
        for item in raw_metrics:
            if not isinstance(item, dict):
                continue
            key = str(_pick(item, "key", "metric_key", "point_key", "pointKey") or "").strip()
            if not key:
                continue
            value = _pick(item, "value", "v")
            if value is None:
                continue
            mapped = ESTONE_POINT_MAP.get(key)
            metrics.append(
                MetricItem(
                    key=mapped[0] if mapped else key,
                    name=str(_pick(item, "name", "metric_name", "point_name", "pointName") or (mapped[1] if mapped else key)),
                    value=float(value),
                    unit=str(_pick(item, "unit", "u") or (mapped[3] if mapped else "") or "") or None,
                    category=str(_pick(item, "category") or (mapped[2] if mapped else "power")),
                )
            )

    if not metrics:
        raw_points = _pick(payload, "points", "data", "point_values", "pointValues")
        if isinstance(raw_points, dict):
            for raw_key, raw_value in raw_points.items():
                try:
                    value = float(raw_value)
                except (TypeError, ValueError):
                    continue
                mapped = ESTONE_POINT_MAP.get(str(raw_key))
                key = mapped[0] if mapped else str(raw_key).strip().lower()
                if not key:
                    continue
                metrics.append(
                    MetricItem(
                        key=key,
                        name=mapped[1] if mapped else key,
                        value=value,
                        unit=mapped[3] if mapped else None,
                        category=mapped[2] if mapped else "power",
                    )
                )

    if not metrics:
        raise ValueError("\u672a\u5728e-stone\u4e0a\u62a5\u6570\u636e\u4e2d\u627e\u5230\u76d1\u63a7\u9879")

    return TelemetryIngestRequest(
        site_code=site_code,
        site_name=site_name,
        fsu_code=fsu_code,
        fsu_name=fsu_name,
        collected_at=collected_at,
        metrics=metrics,
    )
