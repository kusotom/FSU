from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator


VALID_RECEIVER_TYPES = {"USER", "PHONE", "WECHAT", "EMAIL", "PUSHPLUS"}
VALID_SCOPE_TYPES = {"TENANT", "PROJECT", "SITE", "DEVICE_GROUP", "CUSTOM"}
VALID_EVENT_TYPES = {"trigger", "recover", "ack", "close"}
VALID_CHANNEL_TYPES = {"wechat", "sms", "pushplus", "email", "webhook"}


class NotifyReceiverCreate(BaseModel):
    receiver_type: str
    name: str
    user_id: int | None = None
    mobile: str | None = None
    wechat_openid: str | None = None
    email: str | None = None
    pushplus_token: str | None = None
    is_enabled: bool = True

    @field_validator("receiver_type")
    @classmethod
    def validate_receiver_type(cls, value: str) -> str:
        value = str(value or "").strip().upper()
        if value not in VALID_RECEIVER_TYPES:
            raise ValueError("invalid receiver_type")
        return value

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        value = str(value or "").strip()
        if not value:
            raise ValueError("name cannot be empty")
        if len(value) > 128:
            raise ValueError("name too long")
        return value


class NotifyReceiverResponse(BaseModel):
    id: int
    tenant_code: str
    user_id: int | None = None
    receiver_type: str
    name: str
    mobile: str | None = None
    wechat_openid: str | None = None
    email: str | None = None
    pushplus_token: str | None = None
    is_enabled: bool
    created_at: datetime


class NotifyGroupCreate(BaseModel):
    name: str
    description: str | None = None
    member_ids: list[int] = Field(default_factory=list)
    is_enabled: bool = True

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        value = str(value or "").strip()
        if not value:
            raise ValueError("name cannot be empty")
        if len(value) > 128:
            raise ValueError("name too long")
        return value


class NotifyGroupResponse(BaseModel):
    id: int
    tenant_code: str
    name: str
    description: str | None = None
    member_ids: list[int] = Field(default_factory=list)
    member_names: list[str] = Field(default_factory=list)
    member_count: int = 0
    is_enabled: bool
    created_at: datetime


class NotifyRuleCreate(BaseModel):
    name: str
    alarm_level_min: int = 2
    event_types: list[str] = Field(default_factory=lambda: ["trigger", "recover"])
    channel_types: list[str] = Field(default_factory=lambda: ["pushplus"])
    notify_group_id: int | None = None
    scope_type: str = "TENANT"
    project_id: int | None = None
    site_id: int | None = None
    device_group_id: int | None = None
    custom_scope_set_id: int | None = None
    content_template: str | None = None
    is_enabled: bool = True

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        value = str(value or "").strip()
        if not value:
            raise ValueError("name cannot be empty")
        if len(value) > 128:
            raise ValueError("name too long")
        return value

    @field_validator("alarm_level_min")
    @classmethod
    def validate_alarm_level_min(cls, value: int) -> int:
        if value < 1 or value > 4:
            raise ValueError("alarm_level_min must between 1 and 4")
        return value

    @field_validator("event_types")
    @classmethod
    def validate_event_types(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("event_types cannot be empty")
        result: list[str] = []
        for item in value:
            token = str(item or "").strip()
            if token not in VALID_EVENT_TYPES:
                raise ValueError(f"invalid event type: {token}")
            if token not in result:
                result.append(token)
        return result

    @field_validator("channel_types")
    @classmethod
    def validate_channel_types(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("channel_types cannot be empty")
        result: list[str] = []
        for item in value:
            token = str(item or "").strip()
            if token not in VALID_CHANNEL_TYPES:
                raise ValueError(f"invalid channel type: {token}")
            if token not in result:
                result.append(token)
        return result

    @field_validator("scope_type")
    @classmethod
    def validate_scope_type(cls, value: str) -> str:
        value = str(value or "").strip().upper()
        if value not in VALID_SCOPE_TYPES:
            raise ValueError("invalid scope_type")
        return value

    @model_validator(mode="after")
    def validate_scope_fields(self):
        if self.scope_type == "PROJECT" and not self.project_id:
            raise ValueError("PROJECT scope requires project_id")
        if self.scope_type == "SITE" and not self.site_id:
            raise ValueError("SITE scope requires site_id")
        if self.scope_type == "DEVICE_GROUP" and not self.device_group_id:
            raise ValueError("DEVICE_GROUP scope requires device_group_id")
        if self.scope_type == "CUSTOM" and not self.custom_scope_set_id:
            raise ValueError("CUSTOM scope requires custom_scope_set_id")
        return self


class NotifyRuleResponse(BaseModel):
    id: int
    tenant_code: str
    name: str
    alarm_level_min: int
    event_types: list[str] = Field(default_factory=list)
    channel_types: list[str] = Field(default_factory=list)
    notify_group_id: int | None = None
    scope_type: str
    project_id: int | None = None
    site_id: int | None = None
    device_group_id: int | None = None
    custom_scope_set_id: int | None = None
    content_template: str | None = None
    is_enabled: bool
    created_at: datetime

