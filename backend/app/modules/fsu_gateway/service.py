from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.modules.fsu_gateway.dsc_class47 import (
    Class47BuildResult,
    build_class47_response_from_request,
    evaluate_guarded_policy,
)

LOGGER = logging.getLogger("fsu-gateway")
SOAP_PATH = "/services/SCService"
SOAP_RESPONSE = """<?xml version="1.0" encoding="UTF-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <ns1:invokeResponse xmlns:ns1="http://SCService.chinatowercom.com">
      <out>&lt;Response&gt;&lt;Result&gt;OK&lt;/Result&gt;&lt;/Response&gt;</out>
    </ns1:invokeResponse>
  </soap:Body>
</soap:Envelope>"""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_now_text() -> str:
    return _utc_now().isoformat()


def _safe_text(payload: bytes) -> str:
    return payload.decode("utf-8", errors="replace")


def _startup_log(message: str) -> None:
    print(message, flush=True)
    LOGGER.info(message)


def _checksum16(payload: bytes) -> int:
    if len(payload) < 24:
        return 0
    return sum(payload[2:22] + payload[24:]) & 0xFFFF


def _classify_udp_frame(protocol: str, payload: bytes) -> str:
    total_length = len(payload)
    type_a = payload[4:8].hex() if total_length >= 8 else ""
    if protocol == "UDP_DSC" and total_length == 24 and type_a == "1f00d2ff":
        return "DSC_SHORT_24_TYPE_1F00_D2FF"
    if protocol == "UDP_DSC" and total_length == 209 and type_a == "110046ff":
        return "DSC_CONFIG_209_TYPE_1100_46FF"
    if protocol == "UDP_DSC" and total_length == 245 and type_a == "110046ff":
        return "DSC_CONFIG_245_TYPE_1100_46FF"
    if protocol == "UDP_RDS" and total_length == 30 and type_a == "1180d2ff":
        return "RDS_SHORT_30_TYPE_1180_D2FF"
    return "UNKNOWN"


def _extract_debug_uris(payload: bytes) -> list[str]:
    text = "".join(chr(byte) if 0x20 <= byte <= 0x7E else "." for byte in payload)
    return sorted(set(re.findall(r"\b(?:udp|ftp)://[A-Za-z0-9._~:/?#[\]@!$&'()*+,;=%-]+", text)))


def _parse_udp_debug_summary(protocol: str, payload: bytes) -> dict[str, Any]:
    return {
        "protocol": protocol,
        "frameClass": _classify_udp_frame(protocol, payload),
        "seqLE": int.from_bytes(payload[2:4], "little") if len(payload) >= 4 else None,
        "typeA": payload[4:8].hex() if len(payload) >= 8 else "",
        "payloadLengthCandidate": int.from_bytes(payload[20:22], "little") if len(payload) >= 22 else None,
        "uris": _extract_debug_uris(payload),
    }


def build_basic_udp_ack(payload: bytes) -> bytes:
    if len(payload) >= 24 and payload[:2] == b"m~":
        header = bytearray(payload[:24])
        command_id = int.from_bytes(header[4:6], "little")
        if command_id == 0x8010:
            header[4:6] = (0x001F).to_bytes(2, "little")
        header[20:22] = (0).to_bytes(2, "little")
        header[22:24] = b"\x00\x00"
        header[22:24] = _checksum16(bytes(header)).to_bytes(2, "little")
        return bytes(header)
    return b"OK"


class RawPacketStore:
    def __init__(self, log_dir: str):
        self.log_dir = Path(log_dir)

    def write(self, record: dict[str, Any]) -> Path:
        self.log_dir.mkdir(parents=True, exist_ok=True)
        log_file = self.log_dir / f"{datetime.now().strftime('%Y-%m-%d')}.jsonl"
        with log_file.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
        return log_file


class Class47ExperimentStore:
    def __init__(self, log_dir: str):
        self.log_dir = Path(log_dir)

    def write(self, record: dict[str, Any]) -> Path:
        self.log_dir.mkdir(parents=True, exist_ok=True)
        log_file = self.log_dir / f"class47-experiment-{datetime.now().strftime('%Y-%m-%d')}.jsonl"
        with log_file.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
        return log_file


class FsuGatewayService:
    def __init__(self):
        self.store = RawPacketStore(settings.fsu_raw_log_dir)
        self.class47_store = Class47ExperimentStore(settings.fsu_raw_log_dir)
        self._transports: list[asyncio.DatagramTransport] = []
        self._started = False
        self._class47_send_count = 0
        self._class47_guarded_window_started_at: datetime | None = None
        self._class47_guarded_last_send_at: datetime | None = None
        self._class47_guarded_seen_245_in_window = False

    @property
    def enabled(self) -> bool:
        return settings.fsu_gateway_enabled

    async def start(self) -> None:
        _startup_log(f"FSU gateway enabled: {str(self.enabled).lower()}")
        _startup_log(f"SOAP endpoint: {SOAP_PATH}")
        _startup_log(f"raw log dir: {settings.fsu_raw_log_dir}")
        if not self.enabled:
            LOGGER.info("fsu-gateway disabled; UDP listeners not started")
            return
        if self._started:
            return

        loop = asyncio.get_running_loop()
        for protocol, port in (("UDP_DSC", settings.fsu_dsc_port), ("UDP_RDS", settings.fsu_rds_port)):
            try:
                transport, _ = await loop.create_datagram_endpoint(
                    lambda protocol=protocol: _FsuUdpProtocol(protocol, self),
                    local_addr=(settings.fsu_udp_bind_host, port),
                )
            except OSError:
                LOGGER.exception(
                    "fsu-gateway %s failed to bind UDP %s:%s",
                    protocol,
                    settings.fsu_udp_bind_host,
                    port,
                )
                continue
            self._transports.append(transport)
            label = "DSC" if protocol == "UDP_DSC" else "RDS"
            _startup_log(f"UDP {label} listening on {settings.fsu_udp_bind_host}:{port}")
        self._started = True

    async def stop(self) -> None:
        for transport in self._transports:
            transport.close()
        if self._transports:
            LOGGER.info("fsu-gateway UDP listeners stopped")
        self._transports.clear()
        self._started = False

    def record_udp_packet(
        self,
        *,
        protocol: str,
        payload: bytes,
        remote: tuple[str, int],
        local_port: int,
        ack: bytes,
    ) -> None:
        received_at = _utc_now_text()
        record = {
            "protocol": protocol,
            "remoteAddress": remote[0],
            "remotePort": remote[1],
            "localPort": local_port,
            "method": None,
            "requestPath": None,
            "headers": None,
            "length": len(payload),
            "rawHex": payload.hex(),
            "rawText": _safe_text(payload),
            "ackHex": ack.hex(),
            "ackLength": len(ack),
            "receivedAt": received_at,
            "createdAt": received_at,
        }
        log_file = self.store.write(record)
        if settings.fsu_parse_debug:
            debug_summary = _parse_udp_debug_summary(protocol, payload)
            debug_line = "fsu-gateway parse-debug " + json.dumps(
                debug_summary,
                ensure_ascii=False,
                separators=(",", ":"),
            )
            print(debug_line, flush=True)
            LOGGER.info(debug_line)
        LOGGER.info(
            "fsu-gateway %s packet remote=%s:%s localPort=%s length=%s rawHex=%s ackLength=%s log=%s",
            protocol,
            remote[0],
            remote[1],
            local_port,
            len(payload),
            payload.hex(),
            len(ack),
            log_file,
        )

    def _record_class47_experiment(
        self,
        *,
        action: str,
        mode: str,
        protocol: str,
        remote: tuple[str, int],
        local_port: int,
        request: bytes,
        result: Class47BuildResult | None,
        reason: str,
        max_sends: int | None = None,
        seconds_since_last_send: float | None = None,
        seen_245_in_window: bool | None = None,
    ) -> None:
        record = {
            "ts": _utc_now_text(),
            "action": action,
            "mode": mode,
            "protocol": protocol,
            "remoteIp": remote[0],
            "remotePort": remote[1],
            "localPort": local_port,
            "requestLength": len(request),
            "requestTypeBytes": request[4:8].hex() if len(request) >= 8 else "",
            "requestSeqLE": str(int.from_bytes(request[2:4], "little")) if len(request) >= 4 else "",
            "responseTypeBytes": result.response_type_bytes if result else "110047ff",
            "responseLength": result.total_length if result else None,
            "payloadLength": result.payload_length if result else None,
            "checksumLE": result.checksum_le if result else "",
            "reason": reason,
            "sendCount": self._class47_send_count,
            "maxSends": max_sends,
            "secondsSinceLastSend": seconds_since_last_send,
            "seen245InWindow": seen_245_in_window,
        }
        log_file = self.class47_store.write(record)
        LOGGER.info("fsu-gateway class47 action=%s reason=%s log=%s", action, reason, log_file)

    def handle_class47_candidate(
        self,
        *,
        protocol: str,
        payload: bytes,
        remote: tuple[str, int],
        local_port: int,
        transport: asyncio.DatagramTransport,
    ) -> None:
        mode = (settings.fsu_class47_mode or "off").strip().lower()
        if mode == "off":
            return
        if mode not in {"dryrun", "oneshot", "guarded"}:
            self._record_class47_experiment(
                action="skipped",
                mode=mode,
                protocol=protocol,
                remote=remote,
                local_port=local_port,
                request=payload,
                result=None,
                reason=f"invalid_mode:{mode}",
            )
            return
        if protocol != "UDP_DSC":
            return
        if remote[0] != settings.fsu_class47_allowed_device_ip:
            self._record_class47_experiment(
                action="skipped",
                mode=mode,
                protocol=protocol,
                remote=remote,
                local_port=local_port,
                request=payload,
                result=None,
                reason="remote_ip_not_allowed",
            )
            return

        result = build_class47_response_from_request(
            payload,
            settings.fsu_class47_platform_ip,
            settings.fsu_class47_dsc_port,
            settings.fsu_class47_rds_port,
        )
        if not result.ok or result.response is None:
            self._record_class47_experiment(
                action="skipped",
                mode=mode,
                protocol=protocol,
                remote=remote,
                local_port=local_port,
                request=payload,
                result=result,
                reason=result.reason,
            )
            return

        if mode == "dryrun":
            self._record_class47_experiment(
                action="dryrun_build_only",
                mode=mode,
                protocol=protocol,
                remote=remote,
                local_port=local_port,
                request=payload,
                result=result,
                reason="ok",
            )
            return

        if mode == "oneshot":
            max_sends = settings.fsu_class47_max_sends
            if self._class47_send_count >= max_sends:
                self._record_class47_experiment(
                    action="skipped",
                    mode=mode,
                    protocol=protocol,
                    remote=remote,
                    local_port=local_port,
                    request=payload,
                    result=result,
                    reason="max_sends_reached",
                    max_sends=max_sends,
                )
                return

            transport.sendto(result.response, remote)
            self._class47_send_count += 1
            self._record_class47_experiment(
                action="oneshot_sent",
                mode=mode,
                protocol=protocol,
                remote=remote,
                local_port=local_port,
                request=payload,
                result=result,
                reason="ok",
                max_sends=max_sends,
            )
            return

        # guarded mode
        now = _utc_now()
        if self._class47_guarded_window_started_at is None:
            self._class47_guarded_window_started_at = now
        if result.request_length == 245:
            self._class47_guarded_seen_245_in_window = True

        elapsed_window_seconds = (now - self._class47_guarded_window_started_at).total_seconds()
        seconds_since_last_send: float | None = None
        if self._class47_guarded_last_send_at is not None:
            seconds_since_last_send = (now - self._class47_guarded_last_send_at).total_seconds()

        decision = evaluate_guarded_policy(
            request_length=result.request_length or len(payload),
            send_count=self._class47_send_count,
            max_sends=settings.fsu_class47_guarded_max_sends,
            seconds_since_last_send=seconds_since_last_send,
            min_interval_seconds=settings.fsu_class47_guarded_min_interval_seconds,
            elapsed_window_seconds=elapsed_window_seconds,
            window_seconds=settings.fsu_class47_guarded_window_seconds,
            prefer_request_length=settings.fsu_class47_prefer_request_length,
            skip_209_when_245_seen=settings.fsu_class47_skip_209_when_245_seen,
            seen_245_in_window=self._class47_guarded_seen_245_in_window,
        )
        if not decision.send:
            self._record_class47_experiment(
                action=decision.action,
                mode=mode,
                protocol=protocol,
                remote=remote,
                local_port=local_port,
                request=payload,
                result=result,
                reason=decision.reason,
                max_sends=settings.fsu_class47_guarded_max_sends,
                seconds_since_last_send=seconds_since_last_send,
                seen_245_in_window=self._class47_guarded_seen_245_in_window,
            )
            return

        transport.sendto(result.response, remote)
        self._class47_send_count += 1
        self._class47_guarded_last_send_at = now
        self._record_class47_experiment(
            action=decision.action,
            mode=mode,
            protocol=protocol,
            remote=remote,
            local_port=local_port,
            request=payload,
            result=result,
            reason=decision.reason,
            max_sends=settings.fsu_class47_guarded_max_sends,
            seconds_since_last_send=seconds_since_last_send,
            seen_245_in_window=self._class47_guarded_seen_245_in_window,
        )

    def record_soap_request(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes,
        remote_ip: str | None,
        local_port: int | None,
        request_path: str,
    ) -> Path:
        received_at = _utc_now_text()
        record = {
            "protocol": "HTTP_SOAP",
            "remoteAddress": remote_ip or "",
            "remotePort": None,
            "localPort": local_port,
            "requestPath": request_path,
            "method": method,
            "url": url,
            "headers": headers,
            "headersJson": json.dumps(headers, ensure_ascii=False, separators=(",", ":")),
            "length": len(body),
            "rawHex": body.hex(),
            "rawText": _safe_text(body),
            "receivedAt": received_at,
            "createdAt": received_at,
        }
        log_file = self.store.write(record)
        LOGGER.info(
            "fsu-gateway HTTP_SOAP request remote=%s method=%s path=%s length=%s bodyHex=%s log=%s",
            remote_ip or "",
            method,
            request_path,
            len(body),
            body.hex(),
            log_file,
        )
        return log_file

    def health(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "udpDscPort": settings.fsu_dsc_port,
            "udpRdsPort": settings.fsu_rds_port,
            "udpBindHost": settings.fsu_udp_bind_host,
            "soapPath": SOAP_PATH,
            "rawLogDir": settings.fsu_raw_log_dir,
            "status": "ok",
        }


class _FsuUdpProtocol(asyncio.DatagramProtocol):
    def __init__(self, protocol: str, gateway: FsuGatewayService):
        self.protocol = protocol
        self.gateway = gateway
        self.transport: asyncio.DatagramTransport | None = None

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.transport = transport  # type: ignore[assignment]

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        if self.transport is None:
            return
        local = self.transport.get_extra_info("sockname") or ("", 0)
        local_port = int(local[1]) if len(local) >= 2 else 0
        ack = build_basic_udp_ack(data)
        self.gateway.record_udp_packet(
            protocol=self.protocol,
            payload=data,
            remote=addr,
            local_port=local_port,
            ack=ack,
        )
        self.gateway.handle_class47_candidate(
            protocol=self.protocol,
            payload=data,
            remote=addr,
            local_port=local_port,
            transport=self.transport,
        )
        self.transport.sendto(ack, addr)

    def error_received(self, exc: Exception) -> None:
        LOGGER.warning("fsu-gateway %s UDP error: %s", self.protocol, exc)


_gateway = FsuGatewayService()


def get_fsu_gateway() -> FsuGatewayService:
    return _gateway
