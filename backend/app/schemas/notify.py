from datetime import datetime

from pydantic import BaseModel, field_validator, model_validator

VALID_CHANNEL_TYPES = {"wechat_robot", "webhook"}
VALID_EVENT_TYPES = {"trigger", "recover", "ack", "close"}
WECHAT_ROBOT_ENDPOINT_PREFIX = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send"


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
            raise ValueError("通知通道名称不能为空")
        if len(value) > 64:
            raise ValueError("通知通道名称长度不能超过64")
        return value

    @field_validator("channel_type")
    @classmethod
    def validate_channel_type(cls, value: str) -> str:
        value = value.strip()
        if value not in VALID_CHANNEL_TYPES:
            raise ValueError("不支持的通知通道类型")
        return value

    @field_validator("endpoint")
    @classmethod
    def normalize_endpoint(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("通知地址不能为空")
        if not value.startswith(("http://", "https://")):
            raise ValueError("通知地址必须以 http:// 或 https:// 开头")
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
                raise ValueError("企业微信机器人地址格式不正确")
            if "key=" not in self.endpoint:
                raise ValueError("企业微信机器人地址缺少 key 参数")
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
            raise ValueError("策略名称不能为空")
        if len(value) > 64:
            raise ValueError("策略名称长度不能超过64")
        return value

    @field_validator("event_types")
    @classmethod
    def normalize_event_types(cls, value: str) -> str:
        items = [item.strip() for item in value.split(",") if item.strip()]
        if not items:
            raise ValueError("至少需要一个事件类型")
        deduped = []
        seen = set()
        for item in items:
            if item not in VALID_EVENT_TYPES:
                raise ValueError(f"不支持的事件类型: {item}")
            if item in seen:
                continue
            seen.add(item)
            deduped.append(item)
        return ",".join(deduped)

    @field_validator("min_alarm_level")
    @classmethod
    def validate_min_alarm_level(cls, value: int) -> int:
        if value < 1 or value > 4:
            raise ValueError("告警级别需在1到4之间")
        return value


class NotifyChannelTestRequest(BaseModel):
    content: str | None = None


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
