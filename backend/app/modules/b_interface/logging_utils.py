from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re

from app.core.config import settings


SENSITIVE_TAGS = (
    "PaSCword",
    "PaSCWord",
    "PassWord",
    "Password",
    "passwd",
    "pwd",
    "token",
    "secret",
    "authorization",
    "FTPPwd",
    "ftp_password",
    "ftpPassword",
    "IPSecPwd",
    "IPSecUser",
    "IPSecIP",
)
SENSITIVE_PATTERN = re.compile(
    r"<(?P<tag>PaSCword|PaSCWord|PassWord|Password|passwd|pwd|token|secret|authorization|FTPPwd|ftp_password|ftpPassword|IPSecPwd|IPSecUser|IPSecIP)>(?P<value>.*?)</(?P=tag)>",
    re.IGNORECASE | re.DOTALL,
)
ESCAPED_SENSITIVE_PATTERN = re.compile(
    r"&lt;(?P<tag>PaSCword|PaSCWord|PassWord|Password|passwd|pwd|token|secret|authorization|FTPPwd|ftp_password|ftpPassword|IPSecPwd|IPSecUser|IPSecIP)&gt;(?P<value>.*?)&lt;/(?P=tag)&gt;",
    re.IGNORECASE | re.DOTALL,
)


def utc_now_text() -> str:
    return datetime.now(timezone.utc).isoformat()


def sanitize_xml_text(xml_text: str) -> str:
    if not xml_text:
        return xml_text

    def _replace(match: re.Match[str]) -> str:
        tag = match.group("tag")
        return f"<{tag}>***</{tag}>"

    def _replace_escaped(match: re.Match[str]) -> str:
        tag = match.group("tag")
        return f"&lt;{tag}&gt;***&lt;/{tag}&gt;"

    sanitized = SENSITIVE_PATTERN.sub(_replace, xml_text)
    sanitized = ESCAPED_SENSITIVE_PATTERN.sub(_replace_escaped, sanitized)
    for tag in SENSITIVE_TAGS:
        sanitized = re.sub(
            rf"({re.escape(tag)}\s*=\s*)([^<\s]+)",
            rf"\1***",
            sanitized,
            flags=re.IGNORECASE,
        )
        sanitized = re.sub(
            rf"(&lt;{re.escape(tag)}&gt;)(.*?)(&lt;/{re.escape(tag)}&gt;)",
            rf"\1***\3",
            sanitized,
            flags=re.IGNORECASE | re.DOTALL,
        )
    return sanitized


@dataclass
class InvokeLogRecord:
    timestamp: str
    remote_addr: str
    service_name: str
    soap_action: str
    message_name: str
    message_code: str
    fsu_id: str
    fsu_code: str
    alarm_count: int
    raw_soap_request_sanitized: str
    extracted_xmlData_sanitized: str
    response_xml: str
    parse_ok: bool
    direction: str = ""
    command_name: str = ""
    policy_allowed: bool | None = None
    blocked: bool | None = None
    dry_run: bool | None = None
    executed: bool | None = None
    reason: str | None = None
    correlation_id: str | None = None
    error: str | None = None


class BInterfaceInvokeLogger:
    def __init__(self, log_dir: str | None = None):
        base_dir = Path(log_dir or settings.b_interface_log_dir)
        if not base_dir.is_absolute():
            backend_root = Path(__file__).resolve().parents[3]
            base_dir = backend_root / base_dir
        self.log_dir = base_dir
        self.samples_dir = self.log_dir / "samples"

    def write(self, record: InvokeLogRecord) -> Path:
        self.log_dir.mkdir(parents=True, exist_ok=True)
        target = self.log_dir / f"soap-invoke-{datetime.now().strftime('%Y-%m-%d')}.jsonl"
        with target.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(asdict(record), ensure_ascii=False, separators=(",", ":")) + "\n")
        return target

    def save_sample(self, *, timestamp: str, message_name: str, xml_text: str) -> Path | None:
        if not message_name or not xml_text:
            return None
        safe_name = re.sub(r"[^A-Za-z0-9_-]+", "_", message_name.upper()).strip("_")
        if not safe_name:
            return None
        self.samples_dir.mkdir(parents=True, exist_ok=True)
        date_stem = timestamp[:10] if len(timestamp) >= 10 else datetime.now().strftime("%Y-%m-%d")
        target = self.samples_dir / f"{date_stem}-{safe_name}.xml"
        target.write_text(sanitize_xml_text(xml_text), encoding="utf-8")
        return target
