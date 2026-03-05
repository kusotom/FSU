from datetime import datetime

from pydantic import BaseModel


class NotifyChannelCreate(BaseModel):
    name: str
    channel_type: str
    endpoint: str
    secret: str | None = None
    is_enabled: bool = True


class NotifyChannelResponse(BaseModel):
    id: int
    name: str
    channel_type: str
    endpoint: str
    is_enabled: bool
    created_at: datetime

    class Config:
        from_attributes = True


class NotifyPolicyCreate(BaseModel):
    name: str
    channel_id: int
    min_alarm_level: int = 2
    event_types: str = "trigger,recover"
    is_enabled: bool = True


class NotifyPolicyResponse(BaseModel):
    id: int
    name: str
    channel_id: int
    min_alarm_level: int
    event_types: str
    is_enabled: bool
    created_at: datetime

    class Config:
        from_attributes = True

