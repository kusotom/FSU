from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
MODULE_PATH = BACKEND_DIR / "app" / "modules" / "fsu_gateway" / "dsc_class47.py"

spec = importlib.util.spec_from_file_location("dsc_class47_standalone", MODULE_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError(f"Unable to load dsc_class47 module from {MODULE_PATH}")
dsc_class47 = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = dsc_class47
spec.loader.exec_module(dsc_class47)

CLASS47_TYPE_BYTES = dsc_class47.CLASS47_TYPE_BYTES
build_class47_payload = dsc_class47.build_class47_payload
build_class47_response_from_request = dsc_class47.build_class47_response_from_request
calc_fsu_checksum = dsc_class47.calc_fsu_checksum
checksum_valid = dsc_class47.checksum_valid
write_le16 = dsc_class47.write_le16
evaluate_guarded_policy = dsc_class47.evaluate_guarded_policy


def build_mock_class46_request() -> bytes:
    payload = bytearray(221)
    payload[: len(b"udp://192.168.100.100:6005")] = b"udp://192.168.100.100:6005"
    packet = bytearray()
    packet += bytes.fromhex("6d7e")
    packet += bytes.fromhex("6909")
    packet += bytes.fromhex("110046ff")
    packet += bytes.fromhex("00000000c162002d00000000")
    packet += write_le16(len(payload))
    packet += b"\x00\x00"
    packet += payload
    packet[22:24] = write_le16(calc_fsu_checksum(packet))
    return bytes(packet)


def test_payload() -> None:
    payload = build_class47_payload("192.168.100.123", 9000, 7000)
    assert payload[0] == 0
    assert int.from_bytes(payload[1:3], "little") == 6
    assert b"udp://192.168.100.123:7000" in payload
    assert b"udp://192.168.100.123:9000" in payload
    cursor = 3
    channels: list[int] = []
    for _ in range(6):
        channel = payload[cursor]
        length = payload[cursor + 1]
        value = payload[cursor + 2 : cursor + 2 + length]
        assert value.startswith(b"udp://")
        channels.append(channel)
        cursor += 2 + length
    assert channels == [0, 5, 6, 7, 8, 9]
    assert cursor == len(payload)


def test_response() -> None:
    request = build_mock_class46_request()
    result = build_class47_response_from_request(request, "192.168.100.123", 9000, 7000)
    assert result.ok, result.reason
    assert result.response is not None
    response = result.response
    assert response[0:2] == bytes.fromhex("6d7e")
    assert response[2:4] == request[2:4]
    assert response[4:8] == CLASS47_TYPE_BYTES
    assert response[8:20] == request[8:20]
    assert int.from_bytes(response[20:22], "little") == len(response) - 24
    assert result.payload_length == 171
    assert result.total_length == 195
    assert checksum_valid(response)
    assert calc_fsu_checksum(response) == int.from_bytes(response[22:24], "little")


def test_guarded_policy() -> None:
    decision = evaluate_guarded_policy(
        request_length=245,
        send_count=0,
        max_sends=5,
        seconds_since_last_send=None,
        min_interval_seconds=20,
        elapsed_window_seconds=10.0,
        window_seconds=600,
        prefer_request_length=245,
        skip_209_when_245_seen=True,
        seen_245_in_window=False,
    )
    assert decision.send is True
    assert decision.reason == "ok"

    decision = evaluate_guarded_policy(
        request_length=209,
        send_count=0,
        max_sends=5,
        seconds_since_last_send=None,
        min_interval_seconds=20,
        elapsed_window_seconds=10.0,
        window_seconds=600,
        prefer_request_length=245,
        skip_209_when_245_seen=False,
        seen_245_in_window=False,
    )
    assert decision.send is False
    assert decision.reason == "prefer_245_skip_209"

    decision = evaluate_guarded_policy(
        request_length=209,
        send_count=0,
        max_sends=5,
        seconds_since_last_send=None,
        min_interval_seconds=20,
        elapsed_window_seconds=10.0,
        window_seconds=600,
        prefer_request_length=209,
        skip_209_when_245_seen=True,
        seen_245_in_window=True,
    )
    assert decision.send is False
    assert decision.reason == "prefer_245_skip_209"

    decision = evaluate_guarded_policy(
        request_length=245,
        send_count=1,
        max_sends=5,
        seconds_since_last_send=3.0,
        min_interval_seconds=20,
        elapsed_window_seconds=10.0,
        window_seconds=600,
        prefer_request_length=245,
        skip_209_when_245_seen=True,
        seen_245_in_window=True,
    )
    assert decision.send is False
    assert decision.reason == "min_interval_not_elapsed"

    decision = evaluate_guarded_policy(
        request_length=245,
        send_count=5,
        max_sends=5,
        seconds_since_last_send=30.0,
        min_interval_seconds=20,
        elapsed_window_seconds=10.0,
        window_seconds=600,
        prefer_request_length=245,
        skip_209_when_245_seen=True,
        seen_245_in_window=True,
    )
    assert decision.send is False
    assert decision.reason == "max_sends_reached"

    decision = evaluate_guarded_policy(
        request_length=245,
        send_count=0,
        max_sends=5,
        seconds_since_last_send=30.0,
        min_interval_seconds=20,
        elapsed_window_seconds=601.0,
        window_seconds=600,
        prefer_request_length=245,
        skip_209_when_245_seen=True,
        seen_245_in_window=True,
    )
    assert decision.send is False
    assert decision.reason == "guarded_window_expired"


def main() -> int:
    test_payload()
    test_response()
    test_guarded_policy()
    print("class47 builder tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
