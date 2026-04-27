from __future__ import annotations

import argparse
import json
import logging
import socket
import threading
import time
import html
import xml.etree.ElementTree as ET
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from socketserver import BaseRequestHandler, ThreadingMixIn, TCPServer
from typing import Any
from urllib.parse import urlparse


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_now_text() -> str:
    return _utc_now().strftime("%Y%m%dT%H%M%S.%fZ")


def _sanitize_path(value: str) -> str:
    cleaned = value.strip().replace("\\", "/")
    parts = [part for part in cleaned.split("/") if part not in {"", ".", ".."}]
    return "/".join(parts)


def _ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def _decode_text(raw: bytes) -> str | None:
    for encoding in ("utf-8", "gbk", "latin1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return None


def _extract_pk_name(raw: bytes) -> str | None:
    root = _extract_protocol_root(raw)
    if root is None:
        return None
    return root.findtext("./PK_Type/Name")


def _extract_pk_code(raw: bytes) -> str | None:
    root = _extract_protocol_root(raw)
    if root is None:
        return None
    return root.findtext("./PK_Type/Code")


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    if ":" in tag:
        return tag.rsplit(":", 1)[1]
    return tag


def _first_text_by_local_name(root: ET.Element, name: str) -> str:
    for elem in root.iter():
        if _local_name(elem.tag) == name and elem.text:
            return elem.text.strip()
    return ""


def _extract_protocol_text(raw: bytes) -> str | None:
    text = _decode_text(raw)
    if not text:
        return None
    try:
        outer = ET.fromstring(text.strip("\ufeff\r\n\t "))
    except ET.ParseError:
        return text

    if _local_name(outer.tag) != "Envelope":
        return text

    xml_data = _first_text_by_local_name(outer, "xmlData") or _first_text_by_local_name(outer, "return")
    if not xml_data:
        return None
    return html.unescape(xml_data)


def _extract_protocol_root(raw: bytes) -> ET.Element | None:
    protocol_text = _extract_protocol_text(raw)
    if not protocol_text:
        return None
    try:
        return ET.fromstring(protocol_text.strip("\ufeff\r\n\t "))
    except ET.ParseError:
        return None


def _default_poll_body(name: str, code: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Request>
    <PK_Type>
        <Name>{name}</Name>
        <Code>{code}</Code>
    </PK_Type>
    <Info>
        <Result>1</Result>
    </Info>
</Request>
"""


@dataclass(frozen=True)
class HoneypotConfig:
    host: str
    http_port: int
    ftp_port: int
    tcp_port: int
    output_dir: Path
    ftp_user: str
    ftp_password: str
    http_enabled: bool
    ftp_enabled: bool
    tcp_enabled: bool
    poll_target_url: str
    poll_interval_seconds: int
    poll_timeout_seconds: int
    poll_enabled: bool
    poll_get_fsuinfo_body: str
    poll_get_data_body: str


class CaptureStore:
    def __init__(self, root: Path):
        self.root = root
        self.http_dir = _ensure_dir(root / "http")
        self.ftp_dir = _ensure_dir(root / "ftp")
        self.ftp_upload_dir = _ensure_dir(self.ftp_dir / "uploads")
        self.tcp_dir = _ensure_dir(root / "tcp")
        self.poll_dir = _ensure_dir(root / "poller")
        self.lock = threading.Lock()

    def save_http_request(
        self,
        *,
        client_ip: str,
        method: str,
        path: str,
        headers: dict[str, str],
        body: bytes,
    ) -> dict[str, Any]:
        request_id = _utc_now_text()
        stem = f"{request_id}_{method}"
        body_path = self.http_dir / f"{stem}.bin"
        meta_path = self.http_dir / f"{stem}.json"
        with self.lock:
            body_path.write_bytes(body)
            payload = {
                "request_id": request_id,
                "client_ip": client_ip,
                "method": method,
                "path": path,
                "headers": headers,
                "body_file": body_path.name,
                "body_size": len(body),
                "packet_name": _extract_pk_name(body),
                "packet_code": _extract_pk_code(body),
                "body_text_preview": (_decode_text(body) or "")[:4000],
                "received_at": _utc_now().isoformat(),
            }
            meta_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return payload

    def save_ftp_file(
        self,
        *,
        client_ip: str,
        remote_path: str,
        content: bytes,
    ) -> dict[str, Any]:
        request_id = _utc_now_text()
        normalized = _sanitize_path(remote_path) or "upload.bin"
        target = self.ftp_upload_dir / normalized
        _ensure_dir(target.parent)
        meta_path = self.ftp_dir / f"{request_id}_upload.json"
        with self.lock:
            target.write_bytes(content)
            payload = {
                "request_id": request_id,
                "client_ip": client_ip,
                "remote_path": remote_path,
                "saved_file": str(target.relative_to(self.root)),
                "size": len(content),
                "received_at": _utc_now().isoformat(),
            }
            meta_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return payload

    def append_ftp_command(
        self,
        *,
        client_ip: str,
        command: str,
        argument: str,
        response_code: int,
        response_text: str,
    ):
        payload = {
            "time": _utc_now().isoformat(),
            "client_ip": client_ip,
            "command": command,
            "argument": argument,
            "response_code": response_code,
            "response_text": response_text,
        }
        command_log = self.ftp_dir / "commands.jsonl"
        with self.lock:
            with command_log.open("a", encoding="utf-8") as fp:
                fp.write(json.dumps(payload, ensure_ascii=False))
                fp.write("\n")

    def save_poll_exchange(
        self,
        *,
        request_name: str,
        target_url: str,
        request_body: bytes,
        response_status: int | None,
        response_body: bytes,
        error_text: str | None,
    ) -> dict[str, Any]:
        request_id = _utc_now_text()
        request_file = self.poll_dir / f"{request_id}_{request_name}_request.xml"
        response_file = self.poll_dir / f"{request_id}_{request_name}_response.xml"
        meta_file = self.poll_dir / f"{request_id}_{request_name}.json"
        with self.lock:
            request_file.write_bytes(request_body)
            response_file.write_bytes(response_body)
            payload = {
                "request_id": request_id,
                "request_name": request_name,
                "target_url": target_url,
                "response_status": response_status,
                "response_packet_name": _extract_pk_name(response_body),
                "response_packet_code": _extract_pk_code(response_body),
                "error_text": error_text,
                "request_file": request_file.name,
                "response_file": response_file.name,
                "created_at": _utc_now().isoformat(),
            }
            meta_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return payload

    def save_tcp_session(
        self,
        *,
        client_ip: str,
        client_port: int,
        local_port: int,
        payload: bytes,
    ) -> dict[str, Any]:
        request_id = _utc_now_text()
        body_file = self.tcp_dir / f"{request_id}_{client_ip}_{client_port}.bin"
        meta_file = self.tcp_dir / f"{request_id}_{client_ip}_{client_port}.json"
        with self.lock:
            body_file.write_bytes(payload)
            result = {
                "request_id": request_id,
                "client_ip": client_ip,
                "client_port": client_port,
                "local_port": local_port,
                "payload_file": body_file.name,
                "payload_size": len(payload),
                "packet_name": _extract_pk_name(payload),
                "packet_code": _extract_pk_code(payload),
                "payload_text_preview": (_decode_text(payload) or "")[:4000],
                "received_at": _utc_now().isoformat(),
            }
            meta_file.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return result


def build_alarm_ack_response() -> bytes:
    body = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <PK_Type>
        <Name>SEND_ALARM_ACK</Name>
        <Code>502</Code>
    </PK_Type>
    <Info>
        <Result>1</Result>
    </Info>
</Response>
"""
    return body.encode("utf-8")


def build_login_ack_response(sc_ip: str) -> bytes:
    body = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <PK_Type>
        <Name>LOGIN_ACK</Name>
        <Code>102</Code>
    </PK_Type>
    <Info>
        <RightLevel>2</RightLevel>
        <SCIP>{sc_ip}</SCIP>
        <DataSCIP>{sc_ip}</DataSCIP>
    </Info>
</Response>
"""
    return body.encode("utf-8")


def build_logout_ack_response() -> bytes:
    body = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <PK_Type>
        <Name>LOGOUT_ACK</Name>
        <Code>104</Code>
    </PK_Type>
    <Info>
        <Result>1</Result>
    </Info>
</Response>
"""
    return body.encode("utf-8")


def build_generic_ok_response(packet_name: str | None) -> bytes:
    ack_name = f"{packet_name}_ACK" if packet_name else "GENERIC_ACK"
    body = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <PK_Type>
        <Name>{ack_name}</Name>
        <Code>200</Code>
    </PK_Type>
    <Info>
        <Result>1</Result>
    </Info>
</Response>
"""
    return body.encode("utf-8")


def maybe_soap_response(request_body: bytes, response_body: bytes) -> bytes:
    text = _decode_text(request_body) or ""
    try:
        outer = ET.fromstring(text.strip("\ufeff\r\n\t "))
    except ET.ParseError:
        return response_body
    if _local_name(outer.tag) != "Envelope":
        return response_body
    escaped = html.escape(response_body.decode("utf-8", errors="replace"), quote=False)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/" '
        'xmlns:ns1="http://SCService.chinatowercom.com">'
        "<SOAP-ENV:Body><ns1:invokeResponse>"
        f"<return>{escaped}</return>"
        "</ns1:invokeResponse></SOAP-ENV:Body></SOAP-ENV:Envelope>\n"
    ).encode("utf-8")


def build_http_handler(config: HoneypotConfig, store: CaptureStore):
    class HoneypotHTTPRequestHandler(BaseHTTPRequestHandler):
        server_version = "SCBaitHTTP/2.0"

        def _read_body(self) -> bytes:
            length = int(self.headers.get("Content-Length", "0") or "0")
            if length <= 0:
                return b""
            return self.rfile.read(length)

        def _capture(self, body: bytes) -> dict[str, Any]:
            capture = store.save_http_request(
                client_ip=self.client_address[0],
                method=self.command,
                path=self.path,
                headers={key: value for key, value in self.headers.items()},
                body=body,
            )
            logging.info(
                "HTTP captured: client=%s method=%s path=%s bytes=%s packet=%s",
                self.client_address[0],
                self.command,
                self.path,
                capture["body_size"],
                capture["packet_name"] or "-",
            )
            return capture

        def _reply(self, status_code: int, content_type: str, body: bytes):
            self.send_response(status_code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            parsed = urlparse(self.path)
            self._capture(b"")
            if parsed.query.lower() == "wsdl" or parsed.path.lower().endswith(".wsdl"):
                wsdl_body = f"""<?xml version="1.0" encoding="utf-8"?>
<definitions name="SCBaitService"
             targetNamespace="urn:scbait"
             xmlns:soap="http://schemas.xmlsoap.org/wsdl/soap/"
             xmlns:tns="urn:scbait"
             xmlns:xsd="http://www.w3.org/2001/XMLSchema"
             xmlns="http://schemas.xmlsoap.org/wsdl/">
  <documentation>Minimal WSDL placeholder for capture only.</documentation>
</definitions>
""".encode("utf-8")
                self._reply(200, "text/xml; charset=utf-8", wsdl_body)
                return
            info_body = (
                "SC B-interface honeypot is running.\n"
                f"http_port={config.http_port}\n"
                f"ftp_port={config.ftp_port}\n"
                f"tcp_port={config.tcp_port}\n"
                f"poll_enabled={config.poll_enabled}\n"
            ).encode("utf-8")
            self._reply(200, "text/plain; charset=utf-8", info_body)

        def do_POST(self):
            body = self._read_body()
            capture = self._capture(body)
            packet_name = capture["packet_name"]
            if packet_name == "LOGIN":
                response = build_login_ack_response(config.host if config.host != "0.0.0.0" else "192.168.100.123")
            elif packet_name == "LOGOUT":
                response = build_logout_ack_response()
            elif packet_name == "SEND_ALARM":
                response = build_alarm_ack_response()
            else:
                response = build_generic_ok_response(packet_name)
            response = maybe_soap_response(body, response)
            self._reply(200, "text/xml; charset=utf-8", response)

        def do_PUT(self):
            self.do_POST()

        def log_message(self, _format: str, *_args):
            return

    return HoneypotHTTPRequestHandler


class ThreadedTCPServer(ThreadingMixIn, TCPServer):
    allow_reuse_address = True
    daemon_threads = True


def build_raw_tcp_handler(store: CaptureStore):
    class RawTCPHandler(BaseRequestHandler):
        def handle(self):
            self.request.settimeout(2)
            chunks: list[bytes] = []
            while True:
                try:
                    block = self.request.recv(8192)
                except socket.timeout:
                    break
                if not block:
                    break
                chunks.append(block)
                if len(block) < 8192:
                    break

            payload = b"".join(chunks)
            capture = store.save_tcp_session(
                client_ip=self.client_address[0],
                client_port=self.client_address[1],
                local_port=self.request.getsockname()[1],
                payload=payload,
            )
            logging.info(
                "TCP session captured: client=%s:%s local_port=%s bytes=%s packet=%s",
                self.client_address[0],
                self.client_address[1],
                capture["local_port"],
                capture["payload_size"],
                capture["packet_name"] or "-",
            )

    return RawTCPHandler


def build_ftp_handler(store: CaptureStore, config: HoneypotConfig):
    class MinimalFTPHandler(BaseRequestHandler):
        def setup(self):
            self.cwd = "/"
            self.username = ""
            self.logged_in = False
            self.passive_server: socket.socket | None = None
            self.data_conn: socket.socket | None = None
            self.remote_ip = self.client_address[0]

        def handle(self):
            self._send(220, "SC bait FTP ready")
            file = self.request.makefile("rb")
            while True:
                line = file.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="ignore").rstrip("\r\n")
                if not text:
                    continue
                parts = text.split(" ", 1)
                command = parts[0].upper()
                argument = parts[1] if len(parts) > 1 else ""
                if command == "USER":
                    self.username = argument
                    self._send(331, "User name okay, need password.", command=command, argument=argument)
                elif command == "PASS":
                    self.logged_in = True
                    self._send(230, "User logged in.", command=command, argument="***")
                elif command == "SYST":
                    self._send(215, "UNIX Type: L8", command=command, argument=argument)
                elif command == "FEAT":
                    self._send_raw("211-Features\r\n PASV\r\n UTF8\r\n211 End\r\n")
                    store.append_ftp_command(
                        client_ip=self.remote_ip,
                        command=command,
                        argument=argument,
                        response_code=211,
                        response_text="Features",
                    )
                elif command == "OPTS":
                    self._send(200, "Option okay.", command=command, argument=argument)
                elif command == "PWD":
                    self._send(257, f"\"{self.cwd}\" is current directory.", command=command, argument=argument)
                elif command == "CWD":
                    normalized = "/" + _sanitize_path(argument)
                    self.cwd = normalized if normalized != "/" else "/"
                    self._send(250, "Directory changed.", command=command, argument=argument)
                elif command == "TYPE":
                    self._send(200, "Type set.", command=command, argument=argument)
                elif command == "NOOP":
                    self._send(200, "NOOP ok.", command=command, argument=argument)
                elif command == "MKD":
                    target = config.output_dir / "ftp" / "uploads" / _sanitize_path(argument)
                    _ensure_dir(target)
                    self._send(257, f"\"/{_sanitize_path(argument)}\" created.", command=command, argument=argument)
                elif command in {"PASV", "EPSV"}:
                    self._enter_passive_mode(command=command, argument=argument)
                elif command == "LIST":
                    self._handle_list(command=command, argument=argument)
                elif command == "STOR":
                    self._handle_stor(argument)
                elif command == "QUIT":
                    self._send(221, "Goodbye.", command=command, argument=argument)
                    break
                else:
                    self._send(502, "Command not implemented.", command=command, argument=argument)

        def finish(self):
            self._close_data_channel()

        def _send_raw(self, text: str):
            self.request.sendall(text.encode("utf-8"))

        def _send(self, code: int, text: str, *, command: str = "", argument: str = ""):
            self.request.sendall(f"{code} {text}\r\n".encode("utf-8"))
            if command:
                store.append_ftp_command(
                    client_ip=self.remote_ip,
                    command=command,
                    argument=argument,
                    response_code=code,
                    response_text=text,
                )
            logging.info("FTP command: client=%s cmd=%s arg=%s code=%s", self.remote_ip, command or "-", argument, code)

        def _enter_passive_mode(self, *, command: str, argument: str):
            self._close_data_channel()
            self.passive_server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.passive_server.bind((config.host, 0))
            self.passive_server.listen(1)
            ip_text = self.request.getsockname()[0]
            port = self.passive_server.getsockname()[1]
            ip_parts = ip_text.split(".")
            port_high = port // 256
            port_low = port % 256
            response = f"Entering Passive Mode ({','.join(ip_parts)},{port_high},{port_low})."
            self._send(227, response, command=command, argument=argument)

        def _accept_data(self) -> socket.socket:
            if self.passive_server is None:
                raise RuntimeError("PASV not initialized")
            self.passive_server.settimeout(20)
            conn, _addr = self.passive_server.accept()
            self.data_conn = conn
            return conn

        def _close_data_channel(self):
            if self.data_conn is not None:
                with closing(self.data_conn):
                    pass
                self.data_conn = None
            if self.passive_server is not None:
                with closing(self.passive_server):
                    pass
                self.passive_server = None

        def _handle_list(self, *, command: str, argument: str):
            try:
                self._send(150, "Opening ASCII mode data connection for file list.", command=command, argument=argument)
                conn = self._accept_data()
                conn.sendall(b"")
                self._send(226, "Transfer complete.", command=command, argument=argument)
            except Exception:
                self._send(425, "Can't open data connection.", command=command, argument=argument)
            finally:
                self._close_data_channel()

        def _handle_stor(self, argument: str):
            try:
                self._send(150, "Opening binary mode data connection.", command="STOR", argument=argument)
                conn = self._accept_data()
                chunks: list[bytes] = []
                while True:
                    block = conn.recv(8192)
                    if not block:
                        break
                    chunks.append(block)
                content = b"".join(chunks)
                capture = store.save_ftp_file(
                    client_ip=self.remote_ip,
                    remote_path=self._resolve_path(argument),
                    content=content,
                )
                logging.info(
                    "FTP upload captured: client=%s path=%s bytes=%s",
                    self.remote_ip,
                    capture["remote_path"],
                    capture["size"],
                )
                self._send(226, "Transfer complete.", command="STOR", argument=argument)
            except Exception:
                logging.exception("FTP upload failed")
                self._send(451, "Requested action aborted.", command="STOR", argument=argument)
            finally:
                self._close_data_channel()

        def _resolve_path(self, argument: str) -> str:
            normalized = _sanitize_path(argument)
            if self.cwd == "/":
                return f"/{normalized}" if normalized else "/upload.bin"
            prefix = self.cwd.rstrip("/")
            return f"{prefix}/{normalized}" if normalized else f"{prefix}/upload.bin"

    return MinimalFTPHandler


class BInterfacePoller:
    def __init__(self, config: HoneypotConfig, store: CaptureStore):
        self.config = config
        self.store = store
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.session = None

    def start(self):
        if not self.config.poll_enabled:
            return
        try:
            import requests
        except ModuleNotFoundError as exc:
            raise RuntimeError("poll mode requires the requests package") from exc
        self.session = requests.Session()
        self.thread = threading.Thread(target=self._run_loop, name="sc-bait-poller", daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=5)
        if self.session is not None:
            self.session.close()

    def _run_loop(self):
        while not self.stop_event.is_set():
            self._post_command("GET_FSUINFO", self.config.poll_get_fsuinfo_body)
            self._post_command("GET_DATA", self.config.poll_get_data_body)
            self.stop_event.wait(max(self.config.poll_interval_seconds, 5))

    def _post_command(self, request_name: str, body_text: str):
        request_body = body_text.encode("utf-8")
        response_body = b""
        response_status: int | None = None
        error_text: str | None = None
        if self.session is None:
            return
        try:
            response = self.session.post(
                self.config.poll_target_url,
                data=request_body,
                headers={"Content-Type": "text/xml; charset=UTF-8"},
                timeout=self.config.poll_timeout_seconds,
            )
            response_status = response.status_code
            response_body = response.content
            logging.info(
                "poll command sent: name=%s status=%s target=%s",
                request_name,
                response_status,
                self.config.poll_target_url,
            )
        except Exception as exc:
            error_text = str(exc)
            logging.warning("poll command failed: name=%s target=%s error=%s", request_name, self.config.poll_target_url, exc)
        self.store.save_poll_exchange(
            request_name=request_name,
            target_url=self.config.poll_target_url,
            request_body=request_body,
            response_status=response_status,
            response_body=response_body,
            error_text=error_text,
        )


def start_http_server(config: HoneypotConfig, store: CaptureStore) -> tuple[ThreadingHTTPServer, threading.Thread]:
    handler = build_http_handler(config, store)
    server = ThreadingHTTPServer((config.host, config.http_port), handler)
    thread = threading.Thread(target=server.serve_forever, name="sc-bait-http", daemon=True)
    thread.start()
    return server, thread


def start_ftp_server(config: HoneypotConfig, store: CaptureStore) -> tuple[ThreadedTCPServer, threading.Thread]:
    handler = build_ftp_handler(store, config)
    server = ThreadedTCPServer((config.host, config.ftp_port), handler)
    thread = threading.Thread(target=server.serve_forever, name="sc-bait-ftp", daemon=True)
    thread.start()
    return server, thread


def start_tcp_server(config: HoneypotConfig, store: CaptureStore) -> tuple[ThreadedTCPServer, threading.Thread]:
    handler = build_raw_tcp_handler(store)
    server = ThreadedTCPServer((config.host, config.tcp_port), handler)
    thread = threading.Thread(target=server.serve_forever, name="sc-bait-tcp", daemon=True)
    thread.start()
    return server, thread


def parse_args() -> HoneypotConfig:
    parser = argparse.ArgumentParser(description="Capture and emulate China Tower B-interface SC traffic.")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--http-port", type=int, default=80)
    parser.add_argument("--ftp-port", type=int, default=21)
    parser.add_argument("--tcp-port", type=int, default=10378)
    parser.add_argument("--output-dir", default="logs/sc-bait")
    parser.add_argument("--ftp-user", default="anonymous")
    parser.add_argument("--ftp-password", default="anonymous")
    parser.add_argument("--http-only", action="store_true")
    parser.add_argument("--ftp-only", action="store_true")
    parser.add_argument("--disable-tcp", action="store_true")
    parser.add_argument("--poll-target-url", default="")
    parser.add_argument("--poll-interval-seconds", type=int, default=300)
    parser.add_argument("--poll-timeout-seconds", type=int, default=10)
    parser.add_argument("--poll-get-fsuinfo-body-file", default="")
    parser.add_argument("--poll-get-data-body-file", default="")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = Path(__file__).resolve().parent.parent / output_dir

    http_enabled = not args.ftp_only
    ftp_enabled = not args.http_only
    tcp_enabled = not args.disable_tcp and args.tcp_port > 0
    if not http_enabled and not ftp_enabled and not tcp_enabled:
        raise SystemExit("At least one of HTTP, FTP, or raw TCP must be enabled.")

    poll_enabled = bool(args.poll_target_url.strip())
    get_fsuinfo_body = (
        Path(args.poll_get_fsuinfo_body_file).read_text(encoding="utf-8")
        if args.poll_get_fsuinfo_body_file
        else _default_poll_body("GET_FSUINFO", "101")
    )
    get_data_body = (
        Path(args.poll_get_data_body_file).read_text(encoding="utf-8")
        if args.poll_get_data_body_file
        else _default_poll_body("GET_DATA", "401")
    )

    return HoneypotConfig(
        host=args.host,
        http_port=args.http_port,
        ftp_port=args.ftp_port,
        tcp_port=args.tcp_port,
        output_dir=output_dir,
        ftp_user=args.ftp_user,
        ftp_password=args.ftp_password,
        http_enabled=http_enabled,
        ftp_enabled=ftp_enabled,
        tcp_enabled=tcp_enabled,
        poll_target_url=args.poll_target_url.strip(),
        poll_interval_seconds=args.poll_interval_seconds,
        poll_timeout_seconds=args.poll_timeout_seconds,
        poll_enabled=poll_enabled,
        poll_get_fsuinfo_body=get_fsuinfo_body,
        poll_get_data_body=get_data_body,
    )


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [sc-bait] %(message)s",
    )
    config = parse_args()
    store = CaptureStore(_ensure_dir(config.output_dir))
    servers: list[Any] = []
    poller = BInterfacePoller(config, store)
    try:
        if config.http_enabled:
            http_server, _http_thread = start_http_server(config, store)
            servers.append(http_server)
            logging.info("HTTP honeypot listening: %s:%s", config.host, config.http_port)
        if config.ftp_enabled:
            ftp_server, _ftp_thread = start_ftp_server(config, store)
            servers.append(ftp_server)
            logging.info("FTP honeypot listening: %s:%s", config.host, config.ftp_port)
        if config.tcp_enabled:
            tcp_server, _tcp_thread = start_tcp_server(config, store)
            servers.append(tcp_server)
            logging.info("raw TCP honeypot listening: %s:%s", config.host, config.tcp_port)
        if config.poll_enabled:
            poller.start()
            logging.info(
                "B-interface poller enabled: target=%s interval=%ss",
                config.poll_target_url,
                config.poll_interval_seconds,
            )
        logging.info("capture output directory: %s", config.output_dir)
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logging.info("received shutdown signal")
    finally:
        poller.stop()
        for server in servers:
            server.shutdown()
            server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
