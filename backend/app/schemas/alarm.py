from datetime import datetime

from pydantic import BaseModel


class AlarmResponse(BaseModel):
    id: int
    site_id: int
    device_id: int
    point_id: int
    alarm_code: str
    alarm_name: str
    alarm_level: int
    status: str
    trigger_value: float
    content: str
    started_at: datetime
    recovered_at: datetime | None
    acknowledged_at: datetime | None
    closed_at: datetime | None

    class Config:
        from_attributes = True

