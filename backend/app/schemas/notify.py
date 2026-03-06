from datetime import datetime

from pydantic import BaseModel, field_validator, model_validator

SMS_TENCENT_CHANNEL_TYPE = "sms_tencent"
VALID_CHANNEL_TYPES = {"wechat_robot", "webhook", SMS_TENCENT_CHANNEL_TYPE}
VALID_EVENT_TYPES = {"trigger", "recover", "ack", "close"}
WECHAT_ROBOT_ENDPOINT_PREFIX = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send"


def _is_valid_phone_token(token: str) -> bool:
    raw = token.strip().replace(" ", "").replace("-", "")
    if not raw:
        return False
    if raw.startswith("+"):
        return raw[1:].isdigit() and 6 <= len(raw[1:]) <= 20
    if raw.isdigit():
        return 6 <= len(raw) <= 20
    return False


class NotifyChannelCreate(BaseModel):
    name: str
    channel_type: str
    endpoint: str
    secret: str | None = None
    is_enabled: bool = True

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("channel name cannot be empty")
        if len(value) > 64:
            raise ValueError("channel name length cannot exceed 64")
        return value

    @field_validator("channel_type")
    @classmethod
    def validate_channel_type(cls, value: str) -> str:
        value = value.strip()
        if value not in VALID_CHANNEL_TYPES:
            raise ValueError("unsupported channel type")
        return value

    @field_validator("endpoint")
    @classmethod
    def normalize_endpoint(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("endpoint cannot be empty")
        return value

    @field_validator("secret")
    @classmethod
    def normalize_secret(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @model_validator(mode="after")
    def validate_by_channel_type(self):
        if self.channel_type == "wechat_robot":
            if not self.endpoint.startswith(WECHAT_ROBOT_ENDPOINT_PREFIX):
                raise ValueError("invalid wechat robot endpoint")
            if "key=" not in self.endpoint:
                raise ValueError("wechat robot endpoint missing key")
            return self

        if self.channel_type == SMS_TENCENT_CHANNEL_TYPE:
            tokens = [item.strip() for item in self.endpoint.split(",") if item.strip()]
            if not tokens:
                raise ValueError("sms endpoint must contain at least one phone number")
            invalid = [item for item in tokens if not _is_valid_phone_token(item)]
            if invalid:
                raise ValueError(f"invalid phone numbers: {','.join(invalid[:3])}")
        else:
            if not self.endpoint.startswith(("http://", "https://")):
                raise ValueError("endpoint must start with http:// or https://")
        return self


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

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("policy name cannot be empty")
        if len(value) > 64:
            raise ValueError("policy name length cannot exceed 64")
        return value

    @field_validator("event_types")
    @classmethod
    def normalize_event_types(cls, value: str) -> str:
        items = [item.strip() for item in value.split(",") if item.strip()]
        if not items:
            raise ValueError("at least one event type is required")
        deduped = []
        seen = set()
        for item in items:
            if item not in VALID_EVENT_TYPES:
                raise ValueError(f"unsupported event type: {item}")
            if item in seen:
                continue
            seen.add(item)
            deduped.append(item)
        return ",".join(deduped)

    @field_validator("min_alarm_level")
    @classmethod
    def validate_min_alarm_level(cls, value: int) -> int:
        if value < 1 or value > 4:
            raise ValueError("min_alarm_level must be between 1 and 4")
        return value


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


class NotifyChannelTestRequest(BaseModel):
    content: str | None = None
