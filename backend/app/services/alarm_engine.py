from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable


@dataclass
class AlarmEvaluation:
    is_alarm: bool
    alarm_code: str | None = None
    alarm_name: str | None = None
    level: int = 2
    content: str | None = None


DEFAULT_THRESHOLDS: dict[str, tuple[float | None, float | None]] = {
    "room_temp": (35.0, 5.0),
    "room_humidity": (90.0, 10.0),
    "mains_voltage": (260.0, 170.0),
    "battery_temp": (55.0, 5.0),
}


def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _compare(value: float, comparison: str, threshold: float) -> bool:
    if comparison == "gt":
        return value > threshold
    if comparison == "ge":
        return value >= threshold
    if comparison == "lt":
        return value < threshold
    if comparison == "le":
        return value <= threshold
    if comparison == "eq":
        return value == threshold
    if comparison == "ne":
        return value != threshold
    return False


def rule_condition_met(comparison: str, threshold: float | None, value: float) -> bool:
    if threshold is None:
        return False
    return _compare(value, comparison, threshold)


def sustained_for(started_at: datetime, now: datetime, duration_seconds: int) -> bool:
    if duration_seconds <= 0:
        return True
    return (_to_utc(now) - _to_utc(started_at)).total_seconds() >= duration_seconds


def evaluate_metric(
    point_key: str,
    point_name: str,
    value: float,
    high_threshold: float | None,
    low_threshold: float | None,
    rules: Iterable | None = None,
) -> AlarmEvaluation:
    if rules is not None:
        has_rules = False
        for rule in rules:
            has_rules = True
            threshold = rule.threshold_value
            if not rule_condition_met(rule.comparison, threshold, value):
                continue
            return AlarmEvaluation(
                is_alarm=True,
                alarm_code=rule.alarm_code,
                alarm_name=rule.rule_name,
                level=rule.alarm_level,
                content=(
                    f"{point_name}\u89e6\u53d1\u89c4\u5219={rule.rule_key} "
                    f"\u5f53\u524d\u503c={value} \u6bd4\u8f83\u65b9\u5f0f={rule.comparison} "
                    f"\u9608\u503c={threshold}"
                ),
            )
        if has_rules:
            return AlarmEvaluation(is_alarm=False)

    default_high, default_low = DEFAULT_THRESHOLDS.get(point_key, (high_threshold, low_threshold))
    high = high_threshold if high_threshold is not None else default_high
    low = low_threshold if low_threshold is not None else default_low

    if high is not None and value > high:
        return AlarmEvaluation(
            is_alarm=True,
            alarm_code=f"{point_key}_high",
            alarm_name=f"{point_name}\u8fc7\u9ad8",
            level=2,
            content=f"{point_name}\u5f53\u524d\u503c={value} \u8d85\u8fc7\u4e0a\u9650={high}",
        )
    if low is not None and value < low:
        return AlarmEvaluation(
            is_alarm=True,
            alarm_code=f"{point_key}_low",
            alarm_name=f"{point_name}\u8fc7\u4f4e",
            level=2,
            content=f"{point_name}\u5f53\u524d\u503c={value} \u4f4e\u4e8e\u4e0b\u9650={low}",
        )
    return AlarmEvaluation(is_alarm=False)


def is_heartbeat_stale(
    last_seen_at: datetime | None,
    threshold_minutes: float,
    now: datetime | None = None,
) -> bool:
    if last_seen_at is None:
        return True
    current = _to_utc(now or datetime.now(timezone.utc))
    seen = _to_utc(last_seen_at)
    stale_before = current - timedelta(minutes=threshold_minutes)
    return seen < stale_before
