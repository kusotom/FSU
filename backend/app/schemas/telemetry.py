from datetime import datetime

from pydantic import BaseModel


class MetricItem(BaseModel):
    key: str
    name: str
    value: float
    unit: str | None = None
    category: str = "power"


class TelemetryIngestRequest(BaseModel):
    site_code: str
    site_name: str
    fsu_code: str
    fsu_name: str
    collected_at: datetime
    metrics: list[MetricItem]


class TelemetryLatestItem(BaseModel):
    site_code: str
    site_name: str
    device_code: str
    device_name: str
    point_key: str
    point_name: str
    category: str
    value: float
    unit: str | None
    collected_at: datetime


class TelemetryHistoryItem(BaseModel):
    point_key: str
    point_name: str | None = None
    unit: str | None = None
    value: float
    collected_at: datetime


class TelemetrySiteOverviewItem(BaseModel):
    site_code: str
    site_name: str
    site_status: str | None = None
    active_alarm_count: int = 0
    mains_voltage: float | None = None
    dc_voltage: float | None = None
    dc_current: float | None = None
    collected_at: datetime | None = None


class ImportantPointKeysUpdate(BaseModel):
    point_keys: list[str]
