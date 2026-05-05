from __future__ import annotations

from configparser import ConfigParser
from dataclasses import dataclass, field
from pathlib import Path
import xml.etree.ElementTree as ET


@dataclass(frozen=True)
class DeviceRecord:
    name: str
    type: str
    id: str
    code: str
    siteweb_id: str = ""


@dataclass(frozen=True)
class MonitorSignalRecord:
    signal_id: str
    signal_name: str
    base_type_id: str
    unit: str
    signal_category: str
    signal_type: str
    channel_no: str
    signal_meanings: str


@dataclass(frozen=True)
class MonitorUnitsSummary:
    source_path: str | None = None
    fsu_vendor: str | None = None
    fsu_type: str | None = None
    fsu_class: str | None = None
    signals_by_base_type: dict[str, tuple[MonitorSignalRecord, ...]] = field(default_factory=dict)
    signals_by_signal_id: dict[str, tuple[MonitorSignalRecord, ...]] = field(default_factory=dict)


@dataclass(frozen=True)
class BInterfaceConfig:
    sc_ip: str
    fsu_id: str
    fsu_code: str
    ftp_user: str = ""
    ftp_pwd: str = ""
    devices: tuple[DeviceRecord, ...] = field(default_factory=tuple)
    source_path: str | None = None
    monitor_units: MonitorUnitsSummary = field(default_factory=MonitorUnitsSummary)
    signal_id_map: dict[str, dict[str, tuple[str, ...]]] = field(default_factory=dict)
    signal_id_map_2g: dict[str, dict[str, tuple[str, ...]]] = field(default_factory=dict)


@dataclass(frozen=True)
class ResolvedSignalMapping:
    mapping_status: str
    device_type: str
    standard_signal_id: str
    mapped_ids: tuple[str, ...]
    base_type_id: str
    local_signal_id: str
    signal_name: str
    unit: str
    signal_category: str
    signal_type: str
    channel_no: str
    signal_meanings: str


FALLBACK_MONITOR_SIGNALS = (
    MonitorSignalRecord(
        signal_id="418101001",
        signal_name="I2C温度",
        base_type_id="1004001001",
        unit="℃",
        signal_category="analog",
        signal_type="AI",
        channel_no="1",
        signal_meanings="温度",
    ),
    MonitorSignalRecord(
        signal_id="418102001",
        signal_name="I2C湿度",
        base_type_id="1004001002",
        unit="%",
        signal_category="analog",
        signal_type="AI",
        channel_no="2",
        signal_meanings="湿度",
    ),
    MonitorSignalRecord(
        signal_id="418199999",
        signal_name="温湿度复合量",
        base_type_id="1004999001",
        unit="",
        signal_category="analog",
        signal_type="AI",
        channel_no="9",
        signal_meanings="候选一",
    ),
    MonitorSignalRecord(
        signal_id="418199999",
        signal_name="温湿度复合量候选",
        base_type_id="1004999002",
        unit="",
        signal_category="analog",
        signal_type="AI",
        channel_no="10",
        signal_meanings="候选二",
    ),
)

FALLBACK_SIGNAL_ID_MAP = {
    "406": {
        "406101001": ("1006001001",),
    },
    "407": {
        "407101001": ("1007001001",),
    },
    "418": {
        "418101001": ("1004001001",),
        "418102001": ("1004001002",),
        "418199999": ("1004999001", "1004999002"),
    },
    "419": {
        "419101001": ("1009001001",),
    },
}

FALLBACK_SIGNAL_ID_MAP_2G = {
    "418": {
        "418101001": ("1004001001",),
        "418102001": ("1004001002",),
    }
}

FALLBACK_MONITOR_UNITS = MonitorUnitsSummary(
    source_path=None,
    fsu_vendor="Unknown",
    fsu_type="PrototypeFSU",
    fsu_class="PrototypeClass",
    signals_by_base_type={
        "1004001001": (FALLBACK_MONITOR_SIGNALS[0],),
        "1004001002": (FALLBACK_MONITOR_SIGNALS[1],),
        "1004999001": (FALLBACK_MONITOR_SIGNALS[2],),
        "1004999002": (FALLBACK_MONITOR_SIGNALS[3],),
    },
    signals_by_signal_id={
        "418101001": (FALLBACK_MONITOR_SIGNALS[0],),
        "418102001": (FALLBACK_MONITOR_SIGNALS[1],),
        "418199999": (FALLBACK_MONITOR_SIGNALS[2], FALLBACK_MONITOR_SIGNALS[3]),
    },
)

FALLBACK_CONFIG = BInterfaceConfig(
    sc_ip="192.168.100.123",
    fsu_id="51051243812345",
    fsu_code="51051243812345",
    devices=(
        DeviceRecord(name="CommState", type="419", id="51051241900002", code="51051241900002"),
        DeviceRecord(name="Smoke", type="418", id="51051241820004", code="51051241820004"),
        DeviceRecord(name="TempHumidity", type="418", id="51051241830004", code="51051241830004"),
        DeviceRecord(name="WaterLeak", type="418", id="51051241840004", code="51051241840004"),
        DeviceRecord(name="Power", type="406", id="51051240600004", code="51051240600004"),
        DeviceRecord(name="Battery1", type="407", id="51051240700002", code="51051240700002"),
    ),
    monitor_units=FALLBACK_MONITOR_UNITS,
    signal_id_map=FALLBACK_SIGNAL_ID_MAP,
    signal_id_map_2g=FALLBACK_SIGNAL_ID_MAP_2G,
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _backend_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _search_roots() -> list[Path]:
    repo_root = _repo_root()
    backend_root = _backend_root()
    return [
        backend_root / "config",
        backend_root / "app" / "config",
        backend_root / "fixtures" / "fsu",
        repo_root / "runtime-data",
        repo_root / "snapshots",
        repo_root / "$dest",
    ]


def _candidate_paths(filename: str) -> list[Path]:
    roots = _search_roots()
    explicit = [root / filename for root in roots[:3]]
    discovered: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        if root.is_file() and root.name.lower() == filename.lower():
            discovered.append(root)
            continue
        if not root.is_dir():
            continue
        try:
            matches = sorted(root.rglob(filename))
        except OSError:
            continue
        discovered.extend(matches)
    ordered: list[Path] = []
    seen: set[str] = set()
    for path in explicit + discovered:
        key = str(path.resolve()) if path.exists() else str(path)
        if key in seen:
            continue
        seen.add(key)
        ordered.append(path)
    return ordered


def _safe_text(value: str | None, default: str = "") -> str:
    return (value or default).strip()


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    if ":" in tag:
        return tag.rsplit(":", 1)[1]
    return tag


def _parse_signal_id_map(path: Path) -> dict[str, dict[str, tuple[str, ...]]]:
    parser = ConfigParser()
    for encoding in ("utf-8", "gb18030", "gbk"):
        try:
            with path.open("r", encoding=encoding) as fh:
                parser.read_file(fh)
            break
        except UnicodeDecodeError:
            continue
    result: dict[str, dict[str, tuple[str, ...]]] = {}
    for section in parser.sections():
        device_type = _safe_text(section)
        if not device_type:
            continue
        items: dict[str, tuple[str, ...]] = {}
        for standard_signal_id, raw_value in parser.items(section):
            standard_id = _safe_text(standard_signal_id)
            values = tuple(item.strip() for item in raw_value.split(",") if item.strip())
            if standard_id and values:
                items[standard_id] = values
        if items:
            result[device_type] = items
    return result


def load_signal_id_map() -> dict[str, dict[str, tuple[str, ...]]]:
    for path in _candidate_paths("SignalIdMap.ini"):
        if path.exists():
            try:
                parsed = _parse_signal_id_map(path)
            except OSError:
                continue
            if parsed:
                return parsed
    return FALLBACK_SIGNAL_ID_MAP


def load_signal_id_map_2g() -> dict[str, dict[str, tuple[str, ...]]]:
    for path in _candidate_paths("SignalIdMap-2G.ini"):
        if path.exists():
            try:
                parsed = _parse_signal_id_map(path)
            except OSError:
                continue
            if parsed:
                return parsed
    return FALLBACK_SIGNAL_ID_MAP_2G


def _parse_monitor_units(path: Path) -> MonitorUnitsSummary:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        try:
            text = path.read_text(encoding="gb18030")
        except OSError:
            return MonitorUnitsSummary(source_path=str(path))
    except OSError:
        return MonitorUnitsSummary(source_path=str(path))
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return MonitorUnitsSummary(source_path=str(path))

    fields = {"fsu_vendor": None, "fsu_type": None, "fsu_class": None}
    signals_by_base_type: dict[str, list[MonitorSignalRecord]] = {}
    signals_by_signal_id: dict[str, list[MonitorSignalRecord]] = {}
    for elem in root.iter():
        tag = _local_name(elem.tag)
        text_value = _safe_text(elem.text)
        lowered = tag.lower()
        if text_value:
            if lowered in {"fsuvendor", "vendor", "manufactor"} and not fields["fsu_vendor"]:
                fields["fsu_vendor"] = text_value
            elif lowered in {"fsutype", "devicetype", "model"} and not fields["fsu_type"]:
                fields["fsu_type"] = text_value
            elif lowered in {"fsuclass", "deviceclass"} and not fields["fsu_class"]:
                fields["fsu_class"] = text_value

        if lowered != "signal":
            continue
        signal = MonitorSignalRecord(
            signal_id=_safe_text(elem.findtext("SignalId")),
            signal_name=_safe_text(elem.findtext("SignalName")),
            base_type_id=_safe_text(elem.findtext("BaseTypeId")),
            unit=_safe_text(elem.findtext("Unit")),
            signal_category=_safe_text(elem.findtext("SignalCategory")),
            signal_type=_safe_text(elem.findtext("SignalType")),
            channel_no=_safe_text(elem.findtext("ChannelNo")),
            signal_meanings=_safe_text(elem.findtext("SignalMeanings")),
        )
        if signal.base_type_id:
            signals_by_base_type.setdefault(signal.base_type_id, []).append(signal)
        if signal.signal_id:
            signals_by_signal_id.setdefault(signal.signal_id, []).append(signal)
    return MonitorUnitsSummary(
        source_path=str(path),
        fsu_vendor=fields["fsu_vendor"],
        fsu_type=fields["fsu_type"],
        fsu_class=fields["fsu_class"],
        signals_by_base_type={key: tuple(value) for key, value in signals_by_base_type.items()},
        signals_by_signal_id={key: tuple(value) for key, value in signals_by_signal_id.items()},
    )


def load_monitor_units_summary() -> MonitorUnitsSummary:
    for path in _candidate_paths("MonitorUnitsSample.xml") + _candidate_paths("MonitorUnitsStationName=1.xml"):
        if path.exists():
            summary = _parse_monitor_units(path)
            if summary.source_path:
                return summary
    monitor_candidates: list[Path] = []
    for root in _search_roots():
        if not root.exists() or not root.is_dir():
            continue
        try:
            monitor_candidates.extend(sorted(root.rglob("MonitorUnits*.xml")))
        except OSError:
            continue
    for path in monitor_candidates:
        summary = _parse_monitor_units(path)
        if summary.source_path:
            return summary
    return FALLBACK_MONITOR_UNITS


def _parse_init_list(path: Path, monitor_units: MonitorUnitsSummary) -> BInterfaceConfig:
    parser = ConfigParser()
    for encoding in ("utf-8", "gb18030", "gbk"):
        try:
            with path.open("r", encoding=encoding) as fh:
                parser.read_file(fh)
            break
        except UnicodeDecodeError:
            continue
    fsu_info = parser["FSUINFO"] if parser.has_section("FSUINFO") else {}
    device_num = 0
    if parser.has_section("DEVICE_NUM"):
        try:
            device_num = int(parser.get("DEVICE_NUM", "DeviceNum", fallback="0").strip() or "0")
        except ValueError:
            device_num = 0
    devices: list[DeviceRecord] = []
    for index in range(1, max(device_num, 0) + 1):
        section = f"DEVICE{index}"
        if not parser.has_section(section):
            continue
        devices.append(
            DeviceRecord(
                name=parser.get(section, "Name", fallback=""),
                type=parser.get(section, "Type", fallback=""),
                id=parser.get(section, "Id", fallback=""),
                code=parser.get(section, "Code", fallback=""),
                siteweb_id=parser.get(section, "SitewebID", fallback=""),
            )
        )
    return BInterfaceConfig(
        sc_ip=_safe_text(fsu_info.get("SCIP"), FALLBACK_CONFIG.sc_ip),
        fsu_id=_safe_text(fsu_info.get("FSUID"), FALLBACK_CONFIG.fsu_id),
        fsu_code=_safe_text(fsu_info.get("FSUCode"), FALLBACK_CONFIG.fsu_code),
        ftp_user=_safe_text(fsu_info.get("FTPUser")),
        ftp_pwd=_safe_text(fsu_info.get("FTPPwd")),
        devices=tuple(devices or FALLBACK_CONFIG.devices),
        source_path=str(path),
        monitor_units=monitor_units,
        signal_id_map=load_signal_id_map(),
        signal_id_map_2g=load_signal_id_map_2g(),
    )


def load_b_interface_config() -> BInterfaceConfig:
    monitor_units = load_monitor_units_summary()
    for path in _candidate_paths("init_list.ini"):
        if path.exists():
            try:
                return _parse_init_list(path, monitor_units)
            except OSError:
                continue
    return BInterfaceConfig(
        sc_ip=FALLBACK_CONFIG.sc_ip,
        fsu_id=FALLBACK_CONFIG.fsu_id,
        fsu_code=FALLBACK_CONFIG.fsu_code,
        ftp_user=FALLBACK_CONFIG.ftp_user,
        ftp_pwd=FALLBACK_CONFIG.ftp_pwd,
        devices=FALLBACK_CONFIG.devices,
        source_path=None,
        monitor_units=monitor_units,
        signal_id_map=load_signal_id_map(),
        signal_id_map_2g=load_signal_id_map_2g(),
    )


def resolve_signal_mapping(device_id: str, device_code: str, semaphore_id: str) -> ResolvedSignalMapping:
    config = load_b_interface_config()
    standard_signal_id = _safe_text(semaphore_id)
    matched_device = next(
        (
            device
            for device in config.devices
            if device.id == _safe_text(device_id) or device.code == _safe_text(device_code)
        ),
        None,
    )
    if matched_device is None:
        return ResolvedSignalMapping(
            mapping_status="unmapped",
            device_type="",
            standard_signal_id=standard_signal_id,
            mapped_ids=tuple(),
            base_type_id="",
            local_signal_id="",
            signal_name="",
            unit="",
            signal_category="",
            signal_type="",
            channel_no="",
            signal_meanings="",
        )
    device_type = _safe_text(matched_device.type)
    candidates = config.signal_id_map.get(device_type, {}).get(standard_signal_id)
    if not candidates:
        candidates = config.signal_id_map_2g.get(device_type, {}).get(standard_signal_id, tuple())
    if not candidates:
        return ResolvedSignalMapping(
            mapping_status="unmapped",
            device_type=device_type,
            standard_signal_id=standard_signal_id,
            mapped_ids=tuple(),
            base_type_id="",
            local_signal_id="",
            signal_name="",
            unit="",
            signal_category="",
            signal_type="",
            channel_no="",
            signal_meanings="",
        )

    signal_candidates: list[MonitorSignalRecord] = []
    for candidate in candidates:
        signal_candidates.extend(config.monitor_units.signals_by_base_type.get(candidate, tuple()))
        if not config.monitor_units.signals_by_base_type.get(candidate):
            signal_candidates.extend(config.monitor_units.signals_by_signal_id.get(candidate, tuple()))
    if not signal_candidates:
        signal_candidates = [MonitorSignalRecord(candidate, "", candidate, "", "", "", "", "") for candidate in candidates]

    first_signal = signal_candidates[0]
    mapping_status = "mapped" if len(candidates) == 1 and len(signal_candidates) == 1 else "ambiguous"
    return ResolvedSignalMapping(
        mapping_status=mapping_status,
        device_type=device_type,
        standard_signal_id=standard_signal_id,
        mapped_ids=tuple(candidates),
        base_type_id=first_signal.base_type_id or (candidates[0] if candidates else ""),
        local_signal_id=first_signal.signal_id or standard_signal_id,
        signal_name=first_signal.signal_name,
        unit=first_signal.unit,
        signal_category=first_signal.signal_category,
        signal_type=first_signal.signal_type,
        channel_no=first_signal.channel_no,
        signal_meanings=first_signal.signal_meanings,
    )
