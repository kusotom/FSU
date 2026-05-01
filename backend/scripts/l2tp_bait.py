from __future__ import annotations

import argparse
import json
import logging
import socket
import struct
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests


LOGGER = logging.getLogger("l2tp-bait")
L2TP_PORT = 1701
PROTOCOL_VERSION = 2
FLAG_TYPE = 0x8000
FLAG_LENGTH = 0x4000
FLAG_SEQUENCE = 0x0800
CONTROL_FLAGS = FLAG_TYPE | FLAG_LENGTH | FLAG_SEQUENCE | PROTOCOL_VERSION
DATA_FLAGS = FLAG_LENGTH | PROTOCOL_VERSION

MSG_SCCRQ = 1
MSG_SCCRP = 2
MSG_SCCCN = 3
MSG_HELLO = 6
MSG_STOPCCN = 4
MSG_ICRQ = 10
MSG_ICRP = 11
MSG_ICCN = 12

AVP_MESSAGE_TYPE = 0
AVP_RESULT_CODE = 1
AVP_PROTOCOL_VERSION = 2
AVP_FRAMING_CAPABILITIES = 3
AVP_HOST_NAME = 7
AVP_ASSIGNED_TUNNEL_ID = 9
AVP_RECEIVE_WINDOW_SIZE = 10
AVP_ASSIGNED_SESSION_ID = 14
AVP_CALL_SERIAL_NUMBER = 15

PPP_LCP = 0xC021
PPP_IPCP = 0x8021
IPCP_OPT_IPADDRESSES = 1
IPCP_OPT_IPADDRESS = 3
LOCAL_PPP_IP = bytes([10, 10, 10, 1])
PEER_PPP_IP = bytes([10, 10, 10, 2])
HTTP_PORTS = {80, 8080, 8000}


@dataclass
class ParsedPacket:
    flags: int
    length: int
    tunnel_id: int
    session_id: int
    ns: int | None
    nr: int | None
    is_control: bool
    message_type: int | None
    avps: list[dict[str, Any]]
    ppp_protocol: int | None = None
    payload_hex: str | None = None
    payload_info: dict[str, Any] | None = None
    payload_bytes: bytes | None = None


@dataclass(frozen=True)
class ReplayConfig:
    enabled: bool
    target_base_url: str
    timeout_seconds: int


class HttpReplayStore:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, payload: dict[str, Any]) -> None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        target = self.root / f"{stamp}.json"
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


@dataclass
class TcpFlowBuffer:
    src_ip: str
    src_port: int
    dst_ip: str
    dst_port: int
    next_sequence: int | None = None
    buffer: bytearray | None = None
    pending_segments: dict[int, bytes] | None = None

    def __post_init__(self) -> None:
        if self.buffer is None:
            self.buffer = bytearray()
        if self.pending_segments is None:
            self.pending_segments = {}


class CaptureStore:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, addr: tuple[str, int], raw: bytes, parsed: ParsedPacket | None, direction: str = "recv"):
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        base = f"{stamp}_{direction}_{addr[0]}_{addr[1]}"
        (self.root / f"{base}.bin").write_bytes(raw)
        meta = {
            "remote_ip": addr[0],
            "remote_port": addr[1],
            "size": len(raw),
            "captured_at": stamp,
            "direction": direction,
            "parsed": {
                "flags": parsed.flags,
                "length": parsed.length,
                "tunnel_id": parsed.tunnel_id,
                "session_id": parsed.session_id,
                "ns": parsed.ns,
                "nr": parsed.nr,
                "is_control": parsed.is_control,
                "message_type": parsed.message_type,
                "avps": parsed.avps,
                "ppp_protocol": parsed.ppp_protocol,
                "payload_hex": parsed.payload_hex,
                "payload_info": parsed.payload_info,
            } if parsed else None,
        }
        (self.root / f"{base}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def build_avp(attr_type: int, value: bytes, mandatory: bool = True) -> bytes:
    flags = 0x8000 if mandatory else 0
    length = 6 + len(value)
    header = struct.pack("!HHH", flags | length, 0, attr_type)
    return header + value


def build_u16(value: int) -> bytes:
    return struct.pack("!H", value)


def build_u32(value: int) -> bytes:
    return struct.pack("!I", value)


def parse_packet(data: bytes) -> ParsedPacket | None:
    if len(data) < 6:
        return None
    flags = struct.unpack_from("!H", data, 0)[0]
    has_length = bool(flags & FLAG_LENGTH)
    is_control = bool(flags & FLAG_TYPE)
    has_sequence = bool(flags & FLAG_SEQUENCE)
    offset = 2
    length = len(data)
    if has_length:
        if len(data) < 8:
            return None
        length = struct.unpack_from("!H", data, offset)[0]
        offset += 2
    if len(data) < offset + 4:
        return None
    tunnel_id, session_id = struct.unpack_from("!HH", data, offset)
    offset += 4
    ns = nr = None
    if has_sequence:
        if len(data) < offset + 4:
            return None
        ns, nr = struct.unpack_from("!HH", data, offset)
        offset += 4

    avps: list[dict[str, Any]] = []
    message_type: int | None = None
    if is_control:
        while offset + 6 <= len(data):
            avp_flags_length, vendor_id, attr_type = struct.unpack_from("!HHH", data, offset)
            avp_len = avp_flags_length & 0x03FF
            if avp_len < 6 or offset + avp_len > len(data):
                break
            value = data[offset + 6 : offset + avp_len]
            record: dict[str, Any] = {
                "vendor_id": vendor_id,
                "attr_type": attr_type,
                "length": avp_len,
            }
            if attr_type == AVP_MESSAGE_TYPE and len(value) >= 2:
                message_type = struct.unpack("!H", value[:2])[0]
                record["decoded"] = message_type
            elif attr_type == AVP_RESULT_CODE and len(value) >= 4:
                record["decoded"] = {
                    "result": struct.unpack("!H", value[:2])[0],
                    "error": struct.unpack("!H", value[2:4])[0],
                    "message": value[4:].decode("utf-8", errors="ignore"),
                }
            elif attr_type in {AVP_ASSIGNED_TUNNEL_ID, AVP_RECEIVE_WINDOW_SIZE, AVP_ASSIGNED_SESSION_ID} and len(value) >= 2:
                record["decoded"] = struct.unpack("!H", value[:2])[0]
            elif attr_type == AVP_CALL_SERIAL_NUMBER and len(value) >= 4:
                record["decoded"] = struct.unpack("!I", value[:4])[0]
            elif attr_type == AVP_PROTOCOL_VERSION and len(value) >= 2:
                record["decoded"] = list(value[:2])
            elif attr_type == AVP_FRAMING_CAPABILITIES and len(value) >= 4:
                record["decoded"] = struct.unpack("!I", value[:4])[0]
            else:
                try:
                    record["decoded"] = value.decode("utf-8")
                except UnicodeDecodeError:
                    record["decoded_hex"] = value.hex()
            avps.append(record)
            offset += avp_len
        return ParsedPacket(
            flags=flags,
            length=length,
            tunnel_id=tunnel_id,
            session_id=session_id,
            ns=ns,
            nr=nr,
            is_control=is_control,
            message_type=message_type,
            avps=avps,
        )

    payload = data[offset:]
    ppp_protocol: int | None = None
    payload_info: dict[str, Any] | None = None
    if len(payload) >= 4 and payload[0] == 0xFF and payload[1] == 0x03:
        ppp_protocol = struct.unpack("!H", payload[2:4])[0]
        payload_info = parse_ppp_payload(ppp_protocol, payload[4:])

    return ParsedPacket(
        flags=flags,
        length=length,
        tunnel_id=tunnel_id,
        session_id=session_id,
        ns=ns,
        nr=nr,
        is_control=is_control,
        message_type=message_type,
        avps=avps,
        ppp_protocol=ppp_protocol,
        payload_hex=payload.hex(),
        payload_info=payload_info,
        payload_bytes=payload,
    )


def parse_ppp_payload(protocol: int, payload: bytes) -> dict[str, Any] | None:
    if protocol == 0x0021:
        return parse_ipv4_packet(payload)
    return None


def parse_ipv4_packet(packet: bytes) -> dict[str, Any] | None:
    if len(packet) < 20:
        return None
    version_ihl = packet[0]
    version = version_ihl >> 4
    ihl = (version_ihl & 0x0F) * 4
    if version != 4 or ihl < 20 or len(packet) < ihl:
        return None

    total_length = struct.unpack("!H", packet[2:4])[0]
    protocol = packet[9]
    src_ip = socket.inet_ntoa(packet[12:16])
    dst_ip = socket.inet_ntoa(packet[16:20])
    info: dict[str, Any] = {
        "ip_version": version,
        "header_length": ihl,
        "total_length": total_length,
        "protocol": protocol,
        "src_ip": src_ip,
        "dst_ip": dst_ip,
    }

    if len(packet) < total_length:
        total_length = len(packet)
        info["truncated"] = True

    payload = packet[ihl:total_length]
    if protocol == 1:
        icmp = parse_icmp_packet(payload)
        if icmp:
            info["icmp"] = icmp
    elif protocol == 6:
        tcp = parse_tcp_segment(payload)
        if tcp:
            info["tcp"] = tcp
    elif protocol == 17:
        udp = parse_udp_datagram(payload)
        if udp:
            info["udp"] = udp
    return info


def parse_icmp_packet(packet: bytes) -> dict[str, Any] | None:
    if len(packet) < 8:
        return None
    return {
        "type": packet[0],
        "code": packet[1],
        "identifier": struct.unpack("!H", packet[4:6])[0],
        "sequence": struct.unpack("!H", packet[6:8])[0],
    }


def parse_udp_datagram(packet: bytes) -> dict[str, Any] | None:
    if len(packet) < 8:
        return None
    return {
        "src_port": struct.unpack("!H", packet[0:2])[0],
        "dst_port": struct.unpack("!H", packet[2:4])[0],
        "length": struct.unpack("!H", packet[4:6])[0],
    }


def parse_tcp_segment(packet: bytes) -> dict[str, Any] | None:
    if len(packet) < 20:
        return None
    data_offset = (packet[12] >> 4) * 4
    if data_offset < 20 or len(packet) < data_offset:
        return None
    flags = packet[13]
    return {
        "src_port": struct.unpack("!H", packet[0:2])[0],
        "dst_port": struct.unpack("!H", packet[2:4])[0],
        "sequence": struct.unpack("!I", packet[4:8])[0],
        "acknowledgment": struct.unpack("!I", packet[8:12])[0],
        "data_offset": data_offset,
        "flags": {
            "fin": bool(flags & 0x01),
            "syn": bool(flags & 0x02),
            "rst": bool(flags & 0x04),
            "psh": bool(flags & 0x08),
            "ack": bool(flags & 0x10),
            "urg": bool(flags & 0x20),
        },
    }


def build_control_packet(
    tunnel_id: int,
    session_id: int,
    ns: int,
    nr: int,
    avps: list[bytes],
) -> bytes:
    body = b"".join(avps)
    length = 12 + len(body)
    header = struct.pack("!HHHHHH", CONTROL_FLAGS, length, tunnel_id, session_id, ns, nr)
    return header + body


def build_data_packet(tunnel_id: int, session_id: int, payload: bytes) -> bytes:
    length = 8 + len(payload)
    return struct.pack("!HHHH", DATA_FLAGS, length, tunnel_id, session_id) + payload


def build_lcp_config_request(identifier: int) -> bytes:
    options = b"".join(
        [
            b"\x01\x04" + struct.pack("!H", 1400),
            b"\x05\x06" + struct.pack("!I", 0x12345678),
        ]
    )
    lcp = struct.pack("!BBH", 1, identifier, 4 + len(options)) + options
    return b"\xFF\x03" + struct.pack("!H", PPP_LCP) + lcp


def build_ppp_config_ack(protocol: int, identifier: int, options: bytes) -> bytes:
    packet = struct.pack("!BBH", 2, identifier, 4 + len(options)) + options
    return b"\xFF\x03" + struct.pack("!H", protocol) + packet


def build_ppp_config_nak(protocol: int, identifier: int, options: bytes) -> bytes:
    packet = struct.pack("!BBH", 3, identifier, 4 + len(options)) + options
    return b"\xFF\x03" + struct.pack("!H", protocol) + packet


def build_ipcp_config_request(identifier: int, ip_address: bytes) -> bytes:
    options = bytes([IPCP_OPT_IPADDRESS, 6]) + ip_address
    packet = struct.pack("!BBH", 1, identifier, 4 + len(options)) + options
    return b"\xFF\x03" + struct.pack("!H", PPP_IPCP) + packet


class L2TPBaitServer:
    def __init__(self, host: str, port: int, output_dir: Path, replay_config: ReplayConfig):
        self.host = host
        self.port = port
        self.store = CaptureStore(output_dir)
        self.replay_config = replay_config
        self.http_replay_store = HttpReplayStore(output_dir / "http-replay")
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.bind((host, port))
        if hasattr(socket, "SIO_UDP_CONNRESET"):
            try:
                self.socket.ioctl(socket.SIO_UDP_CONNRESET, False)
            except OSError:
                LOGGER.warning("failed to disable UDP connreset handling on this platform")
        self.running = True
        self.local_tunnel_id = 5000
        self.local_session_id = 6000
        self.ns_by_peer: dict[tuple[str, int], int] = {}
        self.peer_tunnel_id: dict[tuple[str, int], int] = {}
        self.peer_session_id: dict[tuple[str, int], int] = {}
        self.lcp_identifier = 1
        self.ipcp_identifier = 1
        self.lcp_seen: set[tuple[str, int]] = set()
        self.ipcp_seen: set[tuple[str, int]] = set()
        self.tcp_flows: dict[tuple[str, int, str, int], TcpFlowBuffer] = {}

    def _next_ns(self, peer: tuple[str, int]) -> int:
        current = self.ns_by_peer.get(peer, 0)
        self.ns_by_peer[peer] = current + 1
        return current

    def _send(self, packet: bytes, peer: tuple[str, int]):
        self.socket.sendto(packet, peer)
        self.store.save(peer, packet, parse_packet(packet), direction="send")
        LOGGER.info("sent %s bytes to %s:%s", len(packet), peer[0], peer[1])

    def _current_ns(self, peer: tuple[str, int]) -> int:
        return self.ns_by_peer.get(peer, 0)

    def _send_zlb_ack(self, peer: tuple[str, int], nr: int, session_scoped: bool = False):
        packet = build_control_packet(
            tunnel_id=self._peer_control_tunnel_id(peer),
            session_id=self.peer_session_id.get(peer, 0) if session_scoped else 0,
            ns=self._current_ns(peer),
            nr=nr,
            avps=[],
        )
        self._send(packet, peer)

    def _peer_control_tunnel_id(self, peer: tuple[str, int]) -> int:
        return self.peer_tunnel_id.get(peer, self.local_tunnel_id)

    def _send_lcp_config_request(self, peer: tuple[str, int]):
        peer_session_id = self.peer_session_id.get(peer)
        if peer_session_id is None:
            LOGGER.info("skip LCP Configure-Request for %s:%s because peer session id is unknown", peer[0], peer[1])
            return
        packet = build_data_packet(
            tunnel_id=self._peer_control_tunnel_id(peer),
            session_id=peer_session_id,
            payload=build_lcp_config_request(self.lcp_identifier),
        )
        self.lcp_identifier = (self.lcp_identifier + 1) % 256 or 1
        self._send(packet, peer)

    def _handle_control(self, parsed: ParsedPacket, peer: tuple[str, int]):
        if parsed.message_type == MSG_SCCRQ:
            # A fresh SCCRQ starts a new control connection for this peer.
            self.ns_by_peer[peer] = 0
            self.peer_session_id.pop(peer, None)
            self.lcp_seen.discard(peer)
            self.ipcp_seen.discard(peer)
            peer_tunnel_id = next(
                (
                    int(avp.get("decoded"))
                    for avp in parsed.avps
                    if avp.get("attr_type") == AVP_ASSIGNED_TUNNEL_ID and isinstance(avp.get("decoded"), int)
                ),
                parsed.tunnel_id,
            )
            self.peer_tunnel_id[peer] = peer_tunnel_id
            avps = [
                build_avp(AVP_MESSAGE_TYPE, build_u16(MSG_SCCRP)),
                build_avp(AVP_PROTOCOL_VERSION, bytes([1, 0])),
                build_avp(AVP_FRAMING_CAPABILITIES, build_u32(3)),
                build_avp(AVP_HOST_NAME, b"fsu-platform-l2tp"),
                build_avp(AVP_ASSIGNED_TUNNEL_ID, build_u16(self.local_tunnel_id)),
                build_avp(AVP_RECEIVE_WINDOW_SIZE, build_u16(4)),
            ]
            packet = build_control_packet(
                tunnel_id=peer_tunnel_id,
                session_id=0,
                ns=self._next_ns(peer),
                nr=(parsed.ns or 0) + 1,
                avps=avps,
            )
            self._send(packet, peer)
        elif parsed.message_type == MSG_ICRQ:
            peer_session_id = next(
                (
                    int(avp.get("decoded"))
                    for avp in parsed.avps
                    if avp.get("attr_type") == AVP_ASSIGNED_SESSION_ID and isinstance(avp.get("decoded"), int)
                ),
                None,
            )
            if peer_session_id is not None:
                self.peer_session_id[peer] = peer_session_id
            avps = [
                build_avp(AVP_MESSAGE_TYPE, build_u16(MSG_ICRP)),
                build_avp(AVP_ASSIGNED_SESSION_ID, build_u16(self.local_session_id)),
            ]
            packet = build_control_packet(
                tunnel_id=self._peer_control_tunnel_id(peer),
                session_id=peer_session_id or 0,
                ns=self._next_ns(peer),
                nr=(parsed.ns or 0) + 1,
                avps=avps,
            )
            self._send(packet, peer)
        elif parsed.message_type in {MSG_SCCCN, MSG_ICCN, MSG_HELLO}:
            self._send_zlb_ack(
                peer,
                (parsed.ns or 0) + 1,
                session_scoped=(parsed.message_type == MSG_ICCN),
            )
            if parsed.message_type == MSG_ICCN:
                LOGGER.info("session connected for %s:%s, waiting for PPP frames from peer", peer[0], peer[1])
        elif parsed.message_type == MSG_STOPCCN:
            LOGGER.info("peer requested stop control connection: %s:%s", peer[0], peer[1])
            self._send_zlb_ack(peer, (parsed.ns or 0) + 1)

    def _handle_data(self, parsed: ParsedPacket, peer: tuple[str, int]):
        if parsed.ppp_protocol == 0x0021:
            self._handle_ipv4_payload(parsed, peer)
            return

        if parsed.ppp_protocol not in {PPP_LCP, PPP_IPCP}:
            return

        payload = bytes.fromhex(parsed.payload_hex or "")
        if len(payload) < 8 or payload[0] != 0xFF or payload[1] != 0x03:
            return

        protocol = struct.unpack("!H", payload[2:4])[0]
        code = payload[4]
        identifier = payload[5]
        length = struct.unpack("!H", payload[6:8])[0]
        options = payload[8 : 4 + length]

        if code == 1:
            response_payload: bytes
            response_label = "acknowledged"

            if protocol == PPP_IPCP and options.endswith(b"\x00\x00\x00\x00"):
                nak_options = bytes([IPCP_OPT_IPADDRESS, 6]) + PEER_PPP_IP
                response_payload = build_ppp_config_nak(protocol, identifier, nak_options)
                response_label = "naked"
            else:
                response_payload = build_ppp_config_ack(protocol, identifier, options)

            response = build_data_packet(
                tunnel_id=self._peer_control_tunnel_id(peer),
                session_id=self.peer_session_id.get(peer, 0),
                payload=response_payload,
            )
            self._send(response, peer)
            LOGGER.info(
                "%s PPP Configure-Request protocol=0x%04X id=%s from %s:%s",
                response_label,
                protocol,
                identifier,
                peer[0],
                peer[1],
            )

            if protocol == PPP_LCP and peer not in self.lcp_seen:
                self.lcp_seen.add(peer)
                self._send_lcp_config_request(peer)
            elif protocol == PPP_IPCP and peer not in self.ipcp_seen:
                self.ipcp_seen.add(peer)
                packet = build_data_packet(
                    tunnel_id=self._peer_control_tunnel_id(peer),
                    session_id=self.peer_session_id.get(peer, 0),
                    payload=build_ipcp_config_request(self.ipcp_identifier, LOCAL_PPP_IP),
                )
                self.ipcp_identifier = (self.ipcp_identifier + 1) % 256 or 1
                self._send(packet, peer)
        elif code == 2:
            LOGGER.info(
                "peer acknowledged PPP Configure-Request protocol=0x%04X id=%s from %s:%s",
                protocol,
                identifier,
                peer[0],
                peer[1],
            )

    def _handle_ipv4_payload(self, parsed: ParsedPacket, peer: tuple[str, int]) -> None:
        if not self.replay_config.enabled or not parsed.payload_info or not parsed.payload_bytes:
            return

        ip_info = parsed.payload_info
        if ip_info.get("protocol") != 6:
            return

        tcp_info = ip_info.get("tcp") or {}
        dst_port = tcp_info.get("dst_port")
        if dst_port not in HTTP_PORTS:
            return

        packet = parsed.payload_bytes[4:]
        ip_header_length = int(ip_info.get("header_length", 0))
        tcp_header_length = int(tcp_info.get("data_offset", 0))
        payload_offset = ip_header_length + tcp_header_length
        if payload_offset > len(packet):
            return

        tcp_payload = packet[payload_offset:]
        flow_key = (
            str(ip_info.get("src_ip")),
            int(tcp_info.get("src_port", 0)),
            str(ip_info.get("dst_ip")),
            int(dst_port),
        )
        if tcp_info.get("flags", {}).get("syn") and not tcp_payload:
            self.tcp_flows[flow_key] = TcpFlowBuffer(
                src_ip=flow_key[0],
                src_port=flow_key[1],
                dst_ip=flow_key[2],
                dst_port=flow_key[3],
                next_sequence=int(tcp_info.get("sequence", 0)) + 1,
            )
            return

        flow = self.tcp_flows.setdefault(
            flow_key,
            TcpFlowBuffer(
                src_ip=flow_key[0],
                src_port=flow_key[1],
                dst_ip=flow_key[2],
                dst_port=flow_key[3],
            ),
        )

        sequence = int(tcp_info.get("sequence", 0))
        if flow.next_sequence is None:
            flow.next_sequence = sequence

        if tcp_payload:
            self._append_tcp_payload(flow, sequence, tcp_payload)
        self._drain_http_requests(flow, peer)

        if tcp_info.get("flags", {}).get("fin") or tcp_info.get("flags", {}).get("rst"):
            self.tcp_flows.pop(flow_key, None)

    def _append_tcp_payload(self, flow: TcpFlowBuffer, sequence: int, payload: bytes) -> None:
        next_sequence = flow.next_sequence
        if next_sequence is None:
            flow.next_sequence = sequence + len(payload)
            flow.buffer.extend(payload)
            self._flush_pending_segments(flow)
            return

        if sequence < next_sequence:
            overlap = next_sequence - sequence
            if overlap >= len(payload):
                LOGGER.info(
                    "drop duplicate tcp payload %s:%s -> %s:%s seq=%s len=%s",
                    flow.src_ip,
                    flow.src_port,
                    flow.dst_ip,
                    flow.dst_port,
                    sequence,
                    len(payload),
                )
                return
            payload = payload[overlap:]
            sequence = next_sequence

        if sequence == next_sequence:
            flow.buffer.extend(payload)
            flow.next_sequence = next_sequence + len(payload)
            self._flush_pending_segments(flow)
            return

        existing = flow.pending_segments.get(sequence)
        if existing is None or len(payload) > len(existing):
            flow.pending_segments[sequence] = payload
        LOGGER.info(
            "buffer out-of-order tcp payload %s:%s -> %s:%s expected_seq=%s got=%s len=%s",
            flow.src_ip,
            flow.src_port,
            flow.dst_ip,
            flow.dst_port,
            next_sequence,
            sequence,
            len(payload),
        )

    def _flush_pending_segments(self, flow: TcpFlowBuffer) -> None:
        while flow.next_sequence in flow.pending_segments:
            sequence = flow.next_sequence
            payload = flow.pending_segments.pop(sequence)
            flow.buffer.extend(payload)
            flow.next_sequence = sequence + len(payload)

    def _drain_http_requests(self, flow: TcpFlowBuffer, peer: tuple[str, int]) -> None:
        while True:
            request = self._pop_http_request(flow)
            if request is None:
                return
            self._replay_http_request(flow, peer, request)

    def _pop_http_request(self, flow: TcpFlowBuffer) -> bytes | None:
        header_end = flow.buffer.find(b"\r\n\r\n")
        if header_end == -1:
            return None

        header_bytes = bytes(flow.buffer[: header_end + 4])
        content_length = 0
        for line in header_bytes.decode("iso-8859-1", errors="ignore").split("\r\n"):
            if line.lower().startswith("content-length:"):
                try:
                    content_length = int(line.split(":", 1)[1].strip())
                except ValueError:
                    content_length = 0
                break

        total_length = header_end + 4 + content_length
        if len(flow.buffer) < total_length:
            return None

        request = bytes(flow.buffer[:total_length])
        del flow.buffer[:total_length]
        return request

    def _replay_http_request(self, flow: TcpFlowBuffer, peer: tuple[str, int], raw_request: bytes) -> None:
        header_blob, body = raw_request.split(b"\r\n\r\n", 1)
        lines = header_blob.decode("iso-8859-1", errors="ignore").split("\r\n")
        if not lines:
            return

        parts = lines[0].split()
        if len(parts) < 2:
            return
        method, path = parts[0], parts[1]
        headers: dict[str, str] = {}
        for line in lines[1:]:
            if ":" not in line:
                continue
            name, value = line.split(":", 1)
            lowered = name.strip().lower()
            if lowered in {"host", "connection", "proxy-connection", "content-length"}:
                continue
            headers[name.strip()] = value.strip()

        target_url = f"{self.replay_config.target_base_url.rstrip('/')}{path}"
        replay_result: dict[str, Any] = {
            "peer_ip": peer[0],
            "peer_port": peer[1],
            "src_ip": flow.src_ip,
            "src_port": flow.src_port,
            "dst_ip": flow.dst_ip,
            "dst_port": flow.dst_port,
            "method": method,
            "path": path,
            "target_url": target_url,
            "request_headers": headers,
            "request_body_preview": body[:4000].decode("utf-8", errors="replace"),
            "request_body_size": len(body),
        }

        try:
            response = requests.request(
                method=method,
                url=target_url,
                headers=headers,
                data=body,
                timeout=self.replay_config.timeout_seconds,
            )
            replay_result["response_status"] = response.status_code
            replay_result["response_headers"] = dict(response.headers)
            replay_result["response_body_preview"] = response.text[:4000]
            LOGGER.info(
                "replayed HTTP %s %s from %s:%s to %s status=%s",
                method,
                path,
                flow.src_ip,
                flow.src_port,
                target_url,
                response.status_code,
            )
        except Exception as exc:
            replay_result["error"] = str(exc)
            LOGGER.exception(
                "failed replaying HTTP %s %s from %s:%s to %s",
                method,
                path,
                flow.src_ip,
                flow.src_port,
                target_url,
            )

        self.http_replay_store.save(replay_result)

    def serve_forever(self):
        LOGGER.info("L2TP bait listening on %s:%s", self.host, self.port)
        while self.running:
            try:
                data, addr = self.socket.recvfrom(65535)
            except ConnectionResetError:
                LOGGER.warning("ignored UDP connreset notification from peer")
                continue
            except OSError as exc:
                if getattr(exc, "winerror", None) == 10054:
                    LOGGER.warning("ignored Windows UDP port unreachable notification")
                    continue
                raise
            parsed = parse_packet(data)
            self.store.save(addr, data, parsed, direction="recv")
            LOGGER.info(
                "captured %s bytes from %s:%s type=%s control=%s",
                len(data),
                addr[0],
                addr[1],
                parsed.message_type if parsed else None,
                parsed.is_control if parsed else None,
            )
            if parsed:
                if parsed.is_control:
                    self._handle_control(parsed, addr)
                else:
                    self._handle_data(parsed, addr)

    def shutdown(self):
        self.running = False
        try:
            self.socket.close()
        except OSError:
            pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Minimal L2TP UDP 1701 bait server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=L2TP_PORT)
    parser.add_argument(
        "--output-dir",
        default=str(Path(__file__).resolve().parents[1] / "logs" / "l2tp-bait"),
    )
    parser.add_argument("--http-replay-base-url", default="")
    parser.add_argument("--http-replay-timeout-seconds", type=int, default=10)
    return parser.parse_args()


def main():
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    server = L2TPBaitServer(
        args.host,
        args.port,
        Path(args.output_dir),
        ReplayConfig(
            enabled=bool(args.http_replay_base_url),
            target_base_url=args.http_replay_base_url,
            timeout_seconds=args.http_replay_timeout_seconds,
        ),
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        LOGGER.info("stopping")
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()
