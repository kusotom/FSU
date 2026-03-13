from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.core.config import settings


@dataclass
class UniSmsMessage:
    provider_message_id: str
    to: str
    status: str
    upstream: str | None = None
    region_code: str | None = None
    country_code: str | None = None
    message_count: int | None = None
    price: Decimal | None = None
    currency: str | None = None


@dataclass
class UniSmsSendResult:
    code: str
    message: str
    raw: dict[str, Any]
    messages: list[UniSmsMessage]


class UniSmsClientError(Exception):
    def __init__(self, code: str, message: str, raw: dict[str, Any] | None = None):
        self.code = code
        self.message = message
        self.raw = raw or {}
        super().__init__(f"{code}: {message}")


class UniSmsClient:
    def __init__(self) -> None:
        self._sdk = self._build_sdk()

    def send_login_code(self, *, to_e164: str, code: str) -> UniSmsSendResult:
        payload = {
            "to": to_e164,
            "signature": settings.unisms_sms_signature,
            "templateId": settings.unisms_login_template_id,
            "templateData": {
                "code": code,
                "ttl": str(max(settings.sms_code_expire_seconds // 60, 1)),
            },
        }
        try:
            result = self._sdk.send(payload)
        except Exception as exc:
            raw = getattr(exc, "result", None) or {}
            raise UniSmsClientError(
                code=str(getattr(exc, "code", "UNISMS_SDK_ERROR")),
                message=str(exc),
                raw=raw if isinstance(raw, dict) else {},
            ) from exc

        raw = {
            "code": str(getattr(result, "code", "0")),
            "message": str(getattr(result, "message", "Ok")),
            "data": getattr(result, "data", None),
        }
        if raw["code"] != "0":
            raise UniSmsClientError(code=raw["code"], message=raw["message"], raw=raw)

        data = raw.get("data") or {}
        messages: list[UniSmsMessage] = []
        for item in data.get("messages", []):
            messages.append(
                UniSmsMessage(
                    provider_message_id=str(item["id"]),
                    to=str(item["to"]),
                    status=str(item.get("status", "")),
                    upstream=item.get("upstream"),
                    region_code=item.get("regionCode"),
                    country_code=item.get("countryCode"),
                    message_count=item.get("messageCount"),
                    price=Decimal(str(item["price"])) if item.get("price") is not None else None,
                    currency=item.get("currency"),
                )
            )
        return UniSmsSendResult(code=raw["code"], message=raw["message"], raw=raw, messages=messages)

    def _build_sdk(self):
        if not settings.unisms_enabled:
            raise UniSmsClientError("UNISMS_DISABLED", "UniSMS 未启用")
        try:
            from unisdk.sms import UniSMS
        except ImportError as exc:
            raise UniSmsClientError("UNISMS_SDK_MISSING", "缺少 unisms SDK，请先安装依赖") from exc

        secret = settings.unisms_access_key_secret if settings.unisms_hmac_enabled else None
        return UniSMS(settings.unisms_access_key_id, secret)
