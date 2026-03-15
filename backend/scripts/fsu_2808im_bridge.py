from __future__ import annotations

import argparse
import logging
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.schemas.telemetry import MetricItem, TelemetryIngestRequest


LOGGER = logging.getLogger("fsu-2808im-bridge")
LOCAL_TZ = datetime.now().astimezone().tzinfo or timezone.utc


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class BridgeConfig:
    device_base_url: str
    username: str
    password: str
    backend_ingest_url: str
    backend_timeout_seconds: float
    device_timeout_seconds: float
    poll_interval_seconds: float
    login_refresh_seconds: float
    site_code_override: str | None
    site_name_override: str | None
    fsu_code_override: str | None
    fsu_name_override: str | None
    include_raw_signals: bool
    dry_run: bool
    internal_device_ids: list[str]


STATUS_TRUE_TEXT = {
    "异常",
    "通讯异常",
    "有告警",
    "开门",
    "得电",
    "不平衡",
    "故障",
    "停电",
    "开启",
    "开",
}

STATUS_FALSE_TEXT = {
    "正常",
    "通讯正常",
    "无告警",
    "关机",
    "关",
    "失电",
    "平衡",
    "待命",
    "浮充",
    "送风",
}


CANONICAL_SIGNAL_RULES: list[dict[str, Any]] = [
    {"match": "回风温度", "key": "room_temp", "name": "机房温度", "unit": "C", "category": "env", "mode": "numeric", "priority": 70},
    {"match": "串行温度", "key": "room_temp", "name": "机房温度", "unit": "C", "category": "env", "mode": "numeric", "priority": 60},
    {"match": "串行湿度", "key": "room_humidity", "name": "机房湿度", "unit": "%", "category": "env", "mode": "numeric", "priority": 60},
    {"match": "第1路输入线/相电压AB/A", "key": "mains_voltage", "name": "市电电压", "unit": "V", "category": "power", "mode": "numeric", "priority": 100},
    {"match": "第1路输入线/相电压BC/B", "key": "mains_voltage", "name": "市电电压", "unit": "V", "category": "power", "mode": "numeric", "priority": 90},
    {"match": "第1路输入线/相电压CA/C", "key": "mains_voltage", "name": "市电电压", "unit": "V", "category": "power", "mode": "numeric", "priority": 90},
    {"match": "第1路输入频率", "key": "mains_frequency", "name": "市电频率", "unit": "HZ", "category": "power", "mode": "numeric", "priority": 100},
    {"match": "交流输入停电告警", "key": "mains_power_state", "name": "市电状态", "unit": None, "category": "power", "mode": "normal_is_one", "priority": 100},
    {"match": "整流模块输出电压", "key": "rectifier_output_voltage", "name": "整流输出电压", "unit": "V", "category": "power", "mode": "numeric", "priority": 100},
    {"match": "总负载电流", "key": "dc_current", "name": "直流负载电流", "unit": "A", "category": "power", "mode": "numeric", "priority": 100},
    {"match": "直流输出电压", "key": "dc_bus_voltage", "name": "直流母线电压", "unit": "V", "category": "power", "mode": "numeric", "priority": 100},
    {"match": "电池总电流", "key": "battery_group_current", "name": "电池组电流", "unit": "A", "category": "power", "mode": "numeric", "priority": 100},
    {"match": "水浸1-DI13", "key": "water_leak_status", "name": "水浸状态", "unit": None, "category": "env", "mode": "alarm", "priority": 100},
    {"match": "烟雾1-DI1", "key": "smoke_status", "name": "烟雾状态", "unit": None, "category": "env", "mode": "alarm", "priority": 100},
    {"match": "门磁DI5", "key": "door_access_status", "name": "门禁状态", "unit": None, "category": "smart", "mode": "alarm", "priority": 100},
    {"match": "空调状态", "key": "ac_running_status", "name": "空调运行状态", "unit": None, "category": "env", "mode": "run", "priority": 100, "device_name": "空调01"},
    {"match": "工作异常告警", "key": "ac_fault_status", "name": "空调故障状态", "unit": None, "category": "env", "mode": "alarm", "priority": 100, "device_name": "空调01"},
    {"match": "制冷状态异常告警", "key": "ac_fault_status", "name": "空调故障状态", "unit": None, "category": "env", "mode": "alarm", "priority": 90, "device_name": "空调01"},
    {"match": "设备通讯状态", "key": "ac_comm_status", "name": "空调通讯状态", "unit": None, "category": "env", "mode": "normal_is_one", "priority": 100, "device_name": "空调01"},
    {"match": "设备通讯状态", "key": "rectifier_fault_status", "name": "整流故障状态", "unit": None, "category": "power", "mode": "alarm", "priority": 80, "device_name": "开关电源01"},
    {"match": "第1路交流防雷器断", "key": "spd_failure", "name": "防雷器失效", "unit": None, "category": "power", "mode": "alarm", "priority": 100},
    {"match": "直流防雷器告警", "key": "spd_failure", "name": "防雷器失效", "unit": None, "category": "power", "mode": "alarm", "priority": 100},
    {"match": "油机发电状态", "key": "gen_running_status", "name": "油机运行状态", "unit": None, "category": "power", "mode": "alarm", "priority": 80},
]

TEMP_CHANNEL_RE = re.compile(r"^温度\d+-CH\d+$")
HUMIDITY_CHANNEL_RE = re.compile(r"^湿度\d+-CH\d+$")
MAINS_CURRENT_RE = re.compile(r"^交流屏输出电流[ABC]$")
RECTIFIER_MODULE_CURRENT_RE = re.compile(r"^模块\d+整流模块输出电流$")
RECTIFIER_MODULE_FAULT_RE = re.compile(r"^模块\d+(整流模块故障|模块通讯中断|模块保护|模块过温|模块不均流|模块直流过压关机)$")
BATTERY_GROUP_VOLTAGE_RE = re.compile(r"^电池组\d+电压$")
BATTERY_TEMP_RE = re.compile(r"^(电池柜温度|电池仓\d+温度)$")
BATTERY_FUSE_RE = re.compile(r"^电池组\d+熔丝断$")
BATTERY_FAULT_RE = re.compile(r"^(电池组\d+保护|电池测试告警|电池短测试告警)$")
DC_BREAKER_RE = re.compile(r"^直流熔丝/开关\d+$")


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return slug[:54] if slug else "signal"


def _normalize_unit(unit: str | None) -> str | None:
    if not unit:
        return None
    unit = unit.strip()
    if unit == "℃":
        return "C"
    return unit


def _parse_float(value: str | None) -> float | None:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _parse_timestamp(value: str | None) -> datetime:
    if value:
        text = value.strip()
        if text:
            try:
                return datetime.strptime(text, "%Y-%m-%d %H:%M:%S").replace(tzinfo=LOCAL_TZ)
            except ValueError:
                pass
    return datetime.now(LOCAL_TZ)


def _status_value(signal: dict[str, Any]) -> float | None:
    str_value = str(signal.get("strvalue") or "").strip()
    if str_value in STATUS_TRUE_TEXT:
        return 1.0
    if str_value in STATUS_FALSE_TEXT:
        return 0.0
    return _parse_float(signal.get("floatvalue"))


def _signal_numeric_value(signal: dict[str, Any], key: str) -> float | None:
    if key.endswith("_status"):
        return _status_value(signal)
    if key == "ac_running_status":
        str_value = str(signal.get("strvalue") or "").strip()
        if str_value in {"开机", "开", "运行"}:
            return 1.0
        if str_value in {"关机", "关"}:
            return 0.0
    if key == "ac_fault_status":
        str_value = str(signal.get("strvalue") or "").strip()
        if str_value == "异常":
            return 1.0
        if str_value == "正常":
            return 0.0
    return _parse_float(signal.get("floatvalue"))


def _normal_is_one_value(signal: dict[str, Any]) -> float | None:
    str_value = str(signal.get("strvalue") or "").strip()
    if str_value in STATUS_FALSE_TEXT:
        return 1.0
    if str_value in STATUS_TRUE_TEXT:
        return 0.0
    raw = _parse_float(signal.get("floatvalue"))
    if raw is None:
        return None
    return 1.0 if raw == 0 else 0.0


def _alarm_value(signal: dict[str, Any]) -> float | None:
    str_value = str(signal.get("strvalue") or "").strip()
    if str_value in STATUS_TRUE_TEXT:
        return 1.0
    if str_value in STATUS_FALSE_TEXT:
        return 0.0
    raw = _parse_float(signal.get("floatvalue"))
    if raw is None:
        return None
    return 1.0 if raw > 0 else 0.0


def _run_value(signal: dict[str, Any]) -> float | None:
    str_value = str(signal.get("strvalue") or "").strip()
    if str_value in {"开机", "开", "运行", "制冷", "制热", "送风", "得电"}:
        return 1.0
    if str_value in {"关机", "关", "停止", "失电"}:
        return 0.0
    raw = _parse_float(signal.get("floatvalue"))
    if raw is None:
        return None
    return 1.0 if raw > 0 else 0.0


def _metric_value_from_rule(signal: dict[str, Any], rule: dict[str, Any]) -> float | None:
    mode = rule.get("mode", "numeric")
    if mode == "numeric":
        return _parse_float(signal.get("floatvalue"))
    if mode == "alarm":
        return _alarm_value(signal)
    if mode == "normal_is_one":
        return _normal_is_one_value(signal)
    if mode == "run":
        return _run_value(signal)
    return _signal_numeric_value(signal, rule["key"])


def _is_reasonable_metric_value(key: str, value: float) -> bool:
    if key == "room_temp":
        return -30.0 <= value <= 100.0
    if key == "room_humidity":
        return 0.0 <= value <= 100.0
    if key in {"mains_voltage", "rectifier_output_voltage", "dc_bus_voltage", "battery_group_voltage"}:
        return 0.0 <= value <= 1000.0
    if key in {"mains_frequency"}:
        return 0.0 <= value <= 100.0
    if key.endswith("_status") or key in {
        "mains_power_state",
        "rectifier_fault_status",
        "battery_fault_status",
        "battery_fuse_status",
        "spd_failure",
        "dc_breaker_status",
        "gen_running_status",
    }:
        return value in {0.0, 1.0}
    return True


def _choose_metric(
    metrics_by_key: dict[str, tuple[int, datetime, MetricItem]],
    metric: MetricItem,
    *,
    priority: int,
    signal_time: datetime,
):
    existing = metrics_by_key.get(metric.key)
    if existing is None:
        metrics_by_key[metric.key] = (priority, signal_time, metric)
        return
    existing_priority, existing_time, existing_metric = existing
    if priority > existing_priority:
        metrics_by_key[metric.key] = (priority, signal_time, metric)
        return
    if priority == existing_priority and signal_time >= existing_time and metric.value != existing_metric.value:
        metrics_by_key[metric.key] = (priority, signal_time, metric)


def _append_sample(samples: dict[str, list[tuple[float, datetime]]], key: str, value: float, signal_time: datetime):
    samples.setdefault(key, []).append((value, signal_time))


def _aggregate_numeric_metric(
    samples: dict[str, list[tuple[float, datetime]]],
    key: str,
    name: str,
    unit: str | None,
    category: str,
    mode: str,
) -> tuple[MetricItem, datetime] | None:
    values = samples.get(key, [])
    if not values:
        return None
    ts = max(item[1] for item in values)
    numbers = [item[0] for item in values]
    if mode == "avg":
        value = sum(numbers) / len(numbers)
    elif mode == "sum":
        value = sum(numbers)
    else:
        value = max(numbers)
    return MetricItem(key=key, name=name, value=round(value, 4), unit=unit, category=category), ts


def _aggregate_binary_metric(
    samples: dict[str, list[tuple[float, datetime]]],
    key: str,
    name: str,
    unit: str | None,
    category: str,
) -> tuple[MetricItem, datetime] | None:
    values = samples.get(key, [])
    if not values:
        return None
    ts = max(item[1] for item in values)
    value = 1.0 if any(item[0] >= 1.0 for item in values) else 0.0
    return MetricItem(key=key, name=name, value=value, unit=unit, category=category), ts


class FSU2808IMClient:
    def __init__(self, config: BridgeConfig):
        self.config = config
        self.http = requests.Session()
        self.http.headers.update({"User-Agent": "fsu-2808im-bridge/1.0"})
        self.session_id: str | None = None
        self.user_level: str | None = None
        self.logged_in_at = 0.0

    @property
    def cgi_url(self) -> str:
        return f"{self.config.device_base_url.rstrip('/')}/cgi-bin/web_main.cgi"

    def _post(self, command_id: str, result_code: str | int, port: str | int, msg_body: str) -> str:
        response = self.http.post(
            self.cgi_url,
            data={
                "commandid": str(command_id),
                "resultCode": str(result_code),
                "sessionid": self.session_id or "",
                "port": str(port),
                "msgBody": msg_body,
            },
            timeout=self.config.device_timeout_seconds,
        )
        response.raise_for_status()
        return response.text.replace("\r", "").replace("\n", "").strip()

    def ensure_session(self):
        if self.session_id and time.time() - self.logged_in_at < self.config.login_refresh_seconds:
            heartbeat = self._post("0x0002", "0", "9528", "")
            if heartbeat == "0":
                return
            LOGGER.warning("heartbeat failed, relogin: %s", heartbeat)
        self.login()

    def login(self):
        response = self.http.post(
            self.cgi_url,
            data={
                "commandid": "0x0001",
                "resultCode": "0",
                "sessionid": "",
                "port": "9528",
                "msgBody": f"{self.config.username}`{self.config.password}`0",
            },
            timeout=self.config.device_timeout_seconds,
        )
        response.raise_for_status()
        text = response.text.replace("\r", "").replace("\n", "").strip()
        parts = text.split("`")
        if len(parts) != 3:
            raise RuntimeError(f"unexpected login response: {text}")
        self.session_id = parts[1]
        self.user_level = parts[2]
        self.logged_in_at = time.time()
        LOGGER.info("device login ok: user=%s level=%s", self.config.username, self.user_level)

    def fetch_station_config(self) -> dict[str, str]:
        self.ensure_session()
        text = self._post("0x0060", "0", "9528", "")
        site_part = text.split("^", 1)[0]
        result: dict[str, str] = {}
        for item in site_part.split("`"):
            if "=" not in item:
                continue
            key, value = item.split("=", 1)
            result[key] = value
        return result

    def fetch_internal_devices(self) -> list[dict[str, str]]:
        self.ensure_session()
        text = self._post("0x0010", "0", "9527", "")
        devices: list[dict[str, str]] = []
        for item in text.split("|"):
            parts = item.split("`")
            if len(parts) < 3:
                continue
            devices.append({"id": parts[0], "type": parts[1], "name": parts[2]})
        return devices

    def fetch_signals(self, internal_device_id: str) -> list[dict[str, Any]]:
        self.ensure_session()
        text = self._post("0x0011", "0", "9527", internal_device_id)
        signals: list[dict[str, Any]] = []
        if not text:
            return signals
        for item in text.split("|"):
            parts = item.split("`")
            if not parts or not parts[0]:
                continue
            signals.append(
                {
                    "sigid": parts[0] if len(parts) >= 1 else "",
                    "severityid": parts[1] if len(parts) >= 2 else "",
                    "valuetype": parts[2] if len(parts) >= 3 else "",
                    "signame": parts[3] if len(parts) >= 4 else "",
                    "floatvalue": parts[4] if len(parts) >= 5 else "",
                    "strvalue": parts[5] if len(parts) >= 6 else "",
                    "unit": parts[6] if len(parts) >= 7 else "",
                    "time": parts[7] if len(parts) >= 8 else "",
                    "portid": parts[8] if len(parts) >= 9 else "",
                    "spunitid": parts[9] if len(parts) >= 10 else "",
                    "ch": parts[10] if len(parts) >= 11 else "",
                    "valid": parts[11] if len(parts) >= 12 else "",
                    "basetypeid": parts[12] if len(parts) >= 13 else "",
                    "tietasigid": parts[13] if len(parts) >= 14 else "",
                    "internal_device_id": internal_device_id,
                }
            )
        return signals


def _metric_from_signal(signal: dict[str, Any], rule: dict[str, Any]) -> MetricItem | None:
    value = _metric_value_from_rule(signal, rule)
    if value is None:
        return None
    if not _is_reasonable_metric_value(rule["key"], value):
        return None
    return MetricItem(
        key=rule["key"],
        name=rule["name"],
        value=value,
        unit=rule["unit"],
        category=rule["category"],
    )


def _raw_metric_from_signal(signal: dict[str, Any]) -> MetricItem | None:
    numeric = _parse_float(signal.get("floatvalue"))
    if numeric is None:
        numeric = _status_value(signal)
    if numeric is None:
        return None
    signame = str(signal.get("signame") or "").strip() or f"signal_{signal['sigid']}"
    raw_key = f"raw_{_slugify(signame)[:44]}_{str(signal['sigid'])[-8:]}"
    return MetricItem(
        key=raw_key[:64],
        name=signame,
        value=numeric,
        unit=_normalize_unit(signal.get("unit")),
        category="raw",
    )


def build_payload(
    config: BridgeConfig,
    station: dict[str, str],
    internal_devices: list[dict[str, str]],
    signals_by_device: dict[str, list[dict[str, Any]]],
) -> TelemetryIngestRequest:
    metrics_by_key: dict[str, tuple[int, datetime, MetricItem]] = {}
    aggregate_samples: dict[str, list[tuple[float, datetime]]] = {}
    collected_at = datetime.now(LOCAL_TZ)

    for device in internal_devices:
        for signal in signals_by_device.get(device["id"], []):
            signal_time = _parse_timestamp(signal.get("time"))
            if signal_time > collected_at:
                collected_at = signal_time

            signal["device_name"] = device["name"]
            signame = str(signal.get("signame") or "").strip()
            for rule in CANONICAL_SIGNAL_RULES:
                if rule.get("device_name") and rule["device_name"] != device["name"]:
                    continue
                if signame != rule["match"]:
                    continue
                metric = _metric_from_signal(signal, rule)
                if metric is None:
                    continue
                _choose_metric(
                    metrics_by_key,
                    metric,
                    priority=int(rule.get("priority", 50)),
                    signal_time=signal_time,
                )
                break

            float_value = _parse_float(signal.get("floatvalue"))
            if float_value is not None:
                if TEMP_CHANNEL_RE.match(signame) and _is_reasonable_metric_value("room_temp", float_value):
                    _append_sample(aggregate_samples, "room_temp", float_value, signal_time)
                if HUMIDITY_CHANNEL_RE.match(signame) and _is_reasonable_metric_value("room_humidity", float_value):
                    _append_sample(aggregate_samples, "room_humidity", float_value, signal_time)
                if MAINS_CURRENT_RE.match(signame):
                    _append_sample(aggregate_samples, "mains_current", float_value, signal_time)
                if RECTIFIER_MODULE_CURRENT_RE.match(signame):
                    _append_sample(aggregate_samples, "rectifier_output_current", float_value, signal_time)
                if BATTERY_GROUP_VOLTAGE_RE.match(signame):
                    _append_sample(aggregate_samples, "battery_group_voltage", float_value, signal_time)
                if BATTERY_TEMP_RE.match(signame):
                    _append_sample(aggregate_samples, "battery_temp", float_value, signal_time)

            if RECTIFIER_MODULE_FAULT_RE.match(signame):
                fault_value = _alarm_value(signal)
                if fault_value is not None:
                    _append_sample(aggregate_samples, "rectifier_fault_status", fault_value, signal_time)
            if BATTERY_FUSE_RE.match(signame):
                fuse_value = _alarm_value(signal)
                if fuse_value is not None:
                    _append_sample(aggregate_samples, "battery_fuse_status", fuse_value, signal_time)
            if BATTERY_FAULT_RE.match(signame):
                battery_fault_value = _alarm_value(signal)
                if battery_fault_value is not None:
                    _append_sample(aggregate_samples, "battery_fault_status", battery_fault_value, signal_time)
            if DC_BREAKER_RE.match(signame):
                breaker_value = _alarm_value(signal)
                if breaker_value is not None:
                    _append_sample(aggregate_samples, "dc_breaker_status", breaker_value, signal_time)

            if config.include_raw_signals:
                raw_metric = _raw_metric_from_signal(signal)
                if raw_metric is not None:
                    _choose_metric(metrics_by_key, raw_metric, priority=10, signal_time=signal_time)

    aggregate_defs = [
        ("room_temp", "机房温度", "C", "env", "avg", 120),
        ("room_humidity", "机房湿度", "%", "env", "avg", 120),
        ("mains_current", "市电电流", "A", "power", "max", 100),
        ("rectifier_output_current", "整流输出电流", "A", "power", "sum", 100),
        ("battery_group_voltage", "电池组电压", "V", "power", "max", 100),
        ("battery_temp", "电池温度", "C", "power", "max", 100),
    ]
    for key, name, unit, category, mode, priority in aggregate_defs:
        aggregated = _aggregate_numeric_metric(aggregate_samples, key, name, unit, category, mode)
        if aggregated is None:
            continue
        metric, ts = aggregated
        if _is_reasonable_metric_value(metric.key, metric.value):
            _choose_metric(metrics_by_key, metric, priority=priority, signal_time=ts)

    aggregate_binary_defs = [
        ("rectifier_fault_status", "整流故障状态", None, "power", 110),
        ("battery_fuse_status", "电池熔丝状态", None, "power", 110),
        ("battery_fault_status", "电池故障状态", None, "power", 110),
        ("dc_breaker_status", "空开状态", None, "power", 100),
    ]
    for key, name, unit, category, priority in aggregate_binary_defs:
        aggregated = _aggregate_binary_metric(aggregate_samples, key, name, unit, category)
        if aggregated is None:
            continue
        metric, ts = aggregated
        _choose_metric(metrics_by_key, metric, priority=priority, signal_time=ts)

    if not metrics_by_key:
        raise RuntimeError("no metrics resolved from FSU-2808IM signal response")

    site_code = config.site_code_override or station.get("FSUID") or "UNKNOWN-SITE"
    site_name = config.site_name_override or station.get("StationName") or site_code
    fsu_code = config.fsu_code_override or station.get("FSUCode") or station.get("FSUID") or "UNKNOWN-FSU"
    fsu_name = config.fsu_name_override or station.get("HWType") or "FSU-2808IM"

    return TelemetryIngestRequest(
        site_code=site_code,
        site_name=site_name,
        fsu_code=fsu_code,
        fsu_name=fsu_name,
        collected_at=collected_at,
        metrics=[item[2] for item in metrics_by_key.values()],
    )


def _select_devices(all_devices: list[dict[str, str]], internal_device_ids: list[str]) -> list[dict[str, str]]:
    if not internal_device_ids:
        return all_devices
    wanted = set(internal_device_ids)
    return [item for item in all_devices if item["id"] in wanted]


def _post_payload(config: BridgeConfig, payload: TelemetryIngestRequest):
    response = requests.post(
        config.backend_ingest_url,
        json=payload.model_dump(mode="json"),
        timeout=config.backend_timeout_seconds,
    )
    response.raise_for_status()
    LOGGER.info("backend accepted payload: status=%s body=%s", response.status_code, response.text[:200])


def _build_config_from_args(args: argparse.Namespace) -> BridgeConfig:
    internal_ids = [item.strip() for item in args.internal_device_ids.split(",") if item.strip()]
    return BridgeConfig(
        device_base_url=args.device_base_url.rstrip("/"),
        username=args.username,
        password=args.password,
        backend_ingest_url=args.backend_ingest_url,
        backend_timeout_seconds=args.backend_timeout_seconds,
        device_timeout_seconds=args.device_timeout_seconds,
        poll_interval_seconds=args.poll_interval_seconds,
        login_refresh_seconds=args.login_refresh_seconds,
        site_code_override=args.site_code,
        site_name_override=args.site_name,
        fsu_code_override=args.fsu_code,
        fsu_name_override=args.fsu_name,
        include_raw_signals=args.include_raw_signals,
        dry_run=args.dry_run,
        internal_device_ids=internal_ids,
    )


def main():
    parser = argparse.ArgumentParser(description="Poll Vertiv/Emerson FSU-2808IM and forward telemetry to fsu-platform.")
    parser.add_argument("--device-base-url", default=os.getenv("FSU2808IM_BASE_URL", "http://192.168.100.100"))
    parser.add_argument("--username", default=os.getenv("FSU2808IM_USERNAME", "operator"))
    parser.add_argument("--password", default=os.getenv("FSU2808IM_PASSWORD", ""))
    parser.add_argument(
        "--backend-ingest-url",
        default=os.getenv("BACKEND_INGEST_URL", "http://127.0.0.1:8000/api/v1/ingest/telemetry"),
    )
    parser.add_argument("--poll-interval-seconds", type=float, default=float(os.getenv("FSU2808IM_POLL_INTERVAL", "15")))
    parser.add_argument("--login-refresh-seconds", type=float, default=float(os.getenv("FSU2808IM_LOGIN_REFRESH", "300")))
    parser.add_argument("--backend-timeout-seconds", type=float, default=float(os.getenv("BACKEND_TIMEOUT_SECONDS", "10")))
    parser.add_argument("--device-timeout-seconds", type=float, default=float(os.getenv("FSU2808IM_DEVICE_TIMEOUT", "10")))
    parser.add_argument("--site-code", default=os.getenv("FSU2808IM_SITE_CODE"))
    parser.add_argument("--site-name", default=os.getenv("FSU2808IM_SITE_NAME"))
    parser.add_argument("--fsu-code", default=os.getenv("FSU2808IM_FSU_CODE"))
    parser.add_argument("--fsu-name", default=os.getenv("FSU2808IM_FSU_NAME"))
    parser.add_argument("--internal-device-ids", default=os.getenv("FSU2808IM_INTERNAL_DEVICE_IDS", ""))
    parser.add_argument("--include-raw-signals", action="store_true", default=_env_bool("FSU2808IM_INCLUDE_RAW_SIGNALS", False))
    parser.add_argument("--dry-run", action="store_true", default=_env_bool("FSU2808IM_DRY_RUN", False))
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--log-level", default=os.getenv("LOG_LEVEL", "INFO"))
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s [fsu-2808im-bridge] %(message)s",
    )

    config = _build_config_from_args(args)
    if not config.password:
        raise SystemExit("FSU2808IM_PASSWORD or --password is required.")

    client = FSU2808IMClient(config)

    while True:
        try:
            station = client.fetch_station_config()
            all_devices = client.fetch_internal_devices()
            selected_devices = _select_devices(all_devices, config.internal_device_ids)
            if not selected_devices:
                raise RuntimeError("no internal devices selected from 0x0010 device list")

            signals_by_device = {device["id"]: client.fetch_signals(device["id"]) for device in selected_devices}
            payload = build_payload(config, station, selected_devices, signals_by_device)

            if config.dry_run:
                print(payload.model_dump_json(indent=2))
            else:
                _post_payload(config, payload)
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            LOGGER.exception("bridge cycle failed: %s", exc)

        if args.once:
            break
        time.sleep(max(config.poll_interval_seconds, 1.0))


if __name__ == "__main__":
    main()
