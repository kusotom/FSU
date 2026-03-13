from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class SmsSendCodeRequest(BaseModel):
    phone_country_code: str = Field(default="+86", max_length=8)
    phone: str = Field(min_length=6, max_length=20)


class SmsSendCodeResponse(BaseModel):
    ok: bool = True
    message: str = "如账号存在，验证码已发送"
    request_id: str | None = None
    resend_after_seconds: int = 60


class SmsLoginRequest(BaseModel):
    phone_country_code: str = Field(default="+86", max_length=8)
    phone: str = Field(min_length=6, max_length=20)
    code: str = Field(min_length=4, max_length=8)


class SmsLoginUserSummary(BaseModel):
    id: int
    username: str
    phone: str
    full_name: str | None = None
    status: str
    role: str
    tenant_id: int | None = None
    tenant_code: str | None = None
    first_login_activated: bool = False


class SmsLoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: SmsLoginUserSummary


class UniSmsDlrPayload(BaseModel):
    id: str
    status: str
    to: str
    regionCode: str | None = None
    countryCode: str | None = None
    messageCount: int | None = None
    price: str | None = None
    currency: str | None = None
    errorCode: str | None = None
    errorMessage: str | None = None
    submitDate: datetime | None = None
    doneDate: datetime | None = None


class UniSmsDlrAck(BaseModel):
    ok: bool = True


# Backward-compatible aliases for the current route module.
class SmsSendRequest(SmsSendCodeRequest):
    scene: str = Field(default="LOGIN")

    @field_validator("scene")
    @classmethod
    def validate_scene(cls, value: str) -> str:
        if value != "LOGIN":
            raise ValueError("仅支持登录验证码")
        return value


class SmsSendResponse(SmsSendCodeResponse):
    debug_code: str | None = None
