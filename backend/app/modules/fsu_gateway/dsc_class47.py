from __future__ import annotations

from dataclasses import dataclass


MAGIC = bytes.fromhex("6d7e")
CLASS46_TYPE_BYTES = bytes.fromhex("110046ff")
CLASS47_TYPE_BYTES = bytes.fromhex("110047ff")
EXPECTED_CLASS46_LENGTHS = {209, 245}
HEADER_LENGTH = 24
CHECKSUM_OFFSET = 22


@dataclass(frozen=True)
class Class47BuildResult:
    ok: bool
    reason: str
    response: bytes | None = None
    payload: bytes | None = None
    seq_le: int | None = None
    seq_bytes_hex: str = ""
    request_length: int | None = None
    request_type_bytes: str = ""
    response_type_bytes: str = "110047ff"
    payload_length: int | None = None
    total_length: int | None = None
    checksum_le: str = ""
    header_context_hex: str = ""


@dataclass(frozen=True)
class GuardedDecision:
    send: bool
    action: str
    reason: str


def le16(buf: bytes | bytearray, offset: int) -> int:
    return int.from_bytes(buf[offset : offset + 2], "little")


def write_le16(value: int) -> bytes:
    return (value & 0xFFFF).to_bytes(2, "little")


def calc_fsu_checksum(packet: bytes | bytearray) -> int:
    if len(packet) < HEADER_LENGTH:
        return 0
    working = bytearray(packet)
    working[CHECKSUM_OFFSET : CHECKSUM_OFFSET + 2] = b"\x00\x00"
    return sum(working[2:]) & 0xFFFF


def checksum_valid(packet: bytes | bytearray) -> bool:
    if len(packet) < HEADER_LENGTH:
        return False
    return le16(packet, CHECKSUM_OFFSET) == calc_fsu_checksum(packet)


def payload_length_valid(packet: bytes | bytearray) -> bool:
    if len(packet) < HEADER_LENGTH:
        return False
    return le16(packet, 20) == len(packet) - HEADER_LENGTH


def validate_class46_register_request(packet: bytes | bytearray) -> Class47BuildResult:
    request = bytes(packet)
    if len(request) < HEADER_LENGTH:
        return Class47BuildResult(ok=False, reason="too_short", request_length=len(request))
    if request[0:2] != MAGIC:
        return Class47BuildResult(ok=False, reason="bad_magic", request_length=len(request))
    if request[4:8] != CLASS46_TYPE_BYTES:
        return Class47BuildResult(
            ok=False,
            reason="not_110046ff",
            request_length=len(request),
            request_type_bytes=request[4:8].hex(),
        )
    if len(request) not in EXPECTED_CLASS46_LENGTHS:
        return Class47BuildResult(
            ok=False,
            reason="unexpected_length",
            request_length=len(request),
            request_type_bytes=request[4:8].hex(),
        )
    if not payload_length_valid(request):
        return Class47BuildResult(
            ok=False,
            reason="payload_length_mismatch",
            request_length=len(request),
            request_type_bytes=request[4:8].hex(),
        )
    if not checksum_valid(request):
        return Class47BuildResult(
            ok=False,
            reason="checksum_invalid",
            request_length=len(request),
            request_type_bytes=request[4:8].hex(),
        )
    return Class47BuildResult(
        ok=True,
        reason="ok",
        seq_le=le16(request, 2),
        seq_bytes_hex=request[2:4].hex(),
        request_length=len(request),
        request_type_bytes=request[4:8].hex(),
        header_context_hex=request[8:20].hex(),
    )


def is_class46_register_request(packet: bytes | bytearray) -> bool:
    return validate_class46_register_request(packet).ok


def _entry(channel_type: int, uri: str) -> bytes:
    raw = uri.encode("ascii")
    if len(raw) > 255:
        raise ValueError(f"URI too long for class47 entry: channel={channel_type}")
    return bytes([channel_type & 0xFF, len(raw)]) + raw


def build_class47_payload(platform_ip: str, dsc_port: int, rds_port: int) -> bytes:
    entries = [
        _entry(0, f"udp://{platform_ip}:{dsc_port}"),
        _entry(5, f"udp://{platform_ip}:{dsc_port}"),
        _entry(6, f"udp://{platform_ip}:{dsc_port}"),
        _entry(7, f"udp://{platform_ip}:{rds_port}"),
        _entry(8, f"udp://{platform_ip}:{dsc_port}"),
        _entry(9, f"udp://{platform_ip}:{dsc_port}"),
    ]
    return b"\x00" + write_le16(len(entries)) + b"".join(entries)


def build_class47_response_from_request(
    request: bytes | bytearray,
    platform_ip: str,
    dsc_port: int,
    rds_port: int,
) -> Class47BuildResult:
    validation = validate_class46_register_request(request)
    if not validation.ok:
        return validation

    request_bytes = bytes(request)
    payload = build_class47_payload(platform_ip, dsc_port, rds_port)
    response = bytearray()
    response += MAGIC
    response += request_bytes[2:4]
    response += CLASS47_TYPE_BYTES
    response += request_bytes[8:20]
    response += write_le16(len(payload))
    response += b"\x00\x00"
    response += payload
    checksum = calc_fsu_checksum(response)
    response[CHECKSUM_OFFSET : CHECKSUM_OFFSET + 2] = write_le16(checksum)

    return Class47BuildResult(
        ok=True,
        reason="ok",
        response=bytes(response),
        payload=payload,
        seq_le=le16(request_bytes, 2),
        seq_bytes_hex=request_bytes[2:4].hex(),
        request_length=len(request_bytes),
        request_type_bytes=request_bytes[4:8].hex(),
        response_type_bytes=response[4:8].hex(),
        payload_length=len(payload),
        total_length=len(response),
        checksum_le=response[CHECKSUM_OFFSET : CHECKSUM_OFFSET + 2].hex(),
        header_context_hex=request_bytes[8:20].hex(),
    )


def evaluate_guarded_policy(
    *,
    request_length: int,
    send_count: int,
    max_sends: int,
    seconds_since_last_send: float | None,
    min_interval_seconds: int,
    elapsed_window_seconds: float,
    window_seconds: int,
    prefer_request_length: int,
    skip_209_when_245_seen: bool,
    seen_245_in_window: bool,
) -> GuardedDecision:
    if elapsed_window_seconds > float(window_seconds):
        return GuardedDecision(send=False, action="guarded_skipped", reason="guarded_window_expired")
    if send_count >= max_sends:
        return GuardedDecision(send=False, action="guarded_skipped", reason="max_sends_reached")
    if seconds_since_last_send is not None and seconds_since_last_send < float(min_interval_seconds):
        return GuardedDecision(send=False, action="guarded_skipped", reason="min_interval_not_elapsed")
    if prefer_request_length in EXPECTED_CLASS46_LENGTHS and request_length != prefer_request_length:
        return GuardedDecision(send=False, action="guarded_skipped", reason=f"prefer_{prefer_request_length}_skip_{request_length}")
    if skip_209_when_245_seen and seen_245_in_window and request_length == 209:
        return GuardedDecision(send=False, action="guarded_skipped", reason="prefer_245_skip_209")
    return GuardedDecision(send=True, action="guarded_sent", reason="ok")
