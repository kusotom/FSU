from datetime import datetime

from pydantic import BaseModel


class AlarmRuleBase(BaseModel):
    rule_name: str
    category: str = "power"
    metric_key: str | None = None
    alarm_code: str
    comparison: str = "gt"
    threshold_value: float | None = None
    duration_seconds: int = 0
    alarm_level: int = 2
    is_enabled: bool = True
    description: str | None = None


class AlarmRuleCreate(AlarmRuleBase):
    rule_key: str


class AlarmRuleUpdate(AlarmRuleBase):
    pass


class AlarmRuleResponse(AlarmRuleBase):
    id: int
    rule_key: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class AlarmRuleTenantPolicyUpdate(BaseModel):
    tenant_code: str | None = None
    is_enabled_override: bool | None = None
    threshold_value_override: float | None = None
    duration_seconds_override: int | None = None
    alarm_level_override: int | None = None


class AlarmRuleTenantPolicyResponse(BaseModel):
    template_rule_id: int
    rule_key: str
    rule_name: str
    category: str
    metric_key: str | None = None
    alarm_code: str
    comparison: str

    tenant_code: str
    tenant_name: str

    template_is_enabled: bool
    template_threshold_value: float | None = None
    template_duration_seconds: int
    template_alarm_level: int

    is_enabled_override: bool | None = None
    threshold_value_override: float | None = None
    duration_seconds_override: int | None = None
    alarm_level_override: int | None = None

    effective_is_enabled: bool
    effective_threshold_value: float | None = None
    effective_duration_seconds: int
    effective_alarm_level: int
