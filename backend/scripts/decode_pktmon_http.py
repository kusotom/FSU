from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


HTTP_POST_MARKER = "HTTP: POST /cgi-bin/web_main.cgi HTTP/1.1"
HTTP_RESPONSE_MARKER = "HTTP: HTTP/1.1 200 OK"
HEX_LINE_RE = re.compile(r"0x[0-9A-Fa-f]+:\s+(.+)$")
HEX_WORD_RE = re.compile(r"^[0-9A-Fa-f]{4}$")


@dataclass
class Frame:
    kind: str
    raw: bytes
    text: str


def _read_text(path: Path) -> str:
    for encoding in ("utf-16", "utf-8", "gbk", "latin1"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeError:
            continue
    return path.read_text(encoding="latin1", errors="ignore")


def _iter_frames(text: str, marker: str, kind: str) -> Iterable[Frame]:
    current: list[str] | None = None
    for line in text.splitlines():
        if marker in line:
            current = []
            continue
        if current is None:
            continue
        match = HEX_LINE_RE.search(line)
        if match:
            tokens: list[str] = []
            for token in match.group(1).strip().split():
                if HEX_WORD_RE.fullmatch(token):
                    tokens.append(token)
                else:
                    break
            if tokens:
                current.extend(tokens)
                continue
        if line.startswith("["):
            if current:
                raw = bytes.fromhex("".join(current))
                http_offset = raw.find(b"POST ") if kind == "request" else raw.find(b"HTTP/1.1 ")
                if http_offset >= 0:
                    payload = raw[http_offset:]
                    yield Frame(kind=kind, raw=payload, text=payload.decode("latin1", errors="ignore"))
            current = None


def _extract_response_body(response_text: str) -> str:
    if "\r\n\r\n" not in response_text:
        return ""
    body = response_text.split("\r\n\r\n", 1)[1]
    if "Transfer-Encoding: chunked" not in response_text:
        return body

    cursor = 0
    chunks: list[str] = []
    while cursor < len(body):
        line_end = body.find("\r\n", cursor)
        if line_end < 0:
            break
        size_text = body[cursor:line_end].strip()
        cursor = line_end + 2
        if not size_text:
            continue
        try:
            chunk_size = int(size_text, 16)
        except ValueError:
            break
        if chunk_size == 0:
            break
        chunk = body[cursor : cursor + chunk_size]
        chunks.append(chunk)
        cursor += chunk_size + 2
    return "".join(chunks)


def _extract_request_summary(request_text: str) -> dict[str, str]:
    head, body = (request_text.split("\r\n\r\n", 1) + [""])[:2]
    cookie = ""
    for line in head.split("\r\n"):
        if line.lower().startswith("cookie: "):
            cookie = line[8:]
            break
    result = {
        "commandid": "",
        "resultCode": "",
        "sessionid": "",
        "port": "",
        "msgBody": "",
        "page": "",
        "referer": "",
    }
    for key in ("commandid", "resultCode", "sessionid", "port", "msgBody"):
        match = re.search(rf"{re.escape(key)}=([^&]*)", body)
        if match:
            result[key] = match.group(1)
    page_match = re.search(r"pShowPage=([^;]+)", cookie)
    if page_match:
        result["page"] = page_match.group(1)
    referer_match = re.search(r"^Referer:\s*(.+)$", head, flags=re.MULTILINE)
    if referer_match:
        result["referer"] = referer_match.group(1)
    return result


def _safe_text(value: str) -> str:
    return value.encode("unicode_escape").decode("ascii")


def _pairs(requests: list[Frame], responses: list[Frame]) -> list[dict[str, str]]:
    pairs: list[dict[str, str]] = []
    for index in range(min(len(requests), len(responses))):
        request = requests[index]
        response = responses[index]
        summary = _extract_request_summary(request.text)
        response_body = _extract_response_body(response.text)
        pairs.append(
            {
                "index": str(index + 1),
                "commandid": summary["commandid"],
                "resultCode": summary["resultCode"],
                "sessionid": summary["sessionid"],
                "port": summary["port"],
                "page": summary["page"],
                "referer": summary["referer"],
                "msgBody": summary["msgBody"],
                "response_body": response_body,
            }
        )
    return pairs


def main() -> None:
    parser = argparse.ArgumentParser(description="从 pktmon 十六进制文本中提取 FSU CGI HTTP 请求/响应。")
    parser.add_argument("input", help="pktmon format 输出的文本文件，例如 backend/logs/pktmon-fsu/fsu-hex.txt")
    parser.add_argument("--json", action="store_true", help="输出 JSON 而不是表格")
    args = parser.parse_args()

    text = _read_text(Path(args.input))
    requests = list(_iter_frames(text, HTTP_POST_MARKER, "request"))
    responses = list(_iter_frames(text, HTTP_RESPONSE_MARKER, "response"))
    pairs = _pairs(requests, responses)

    if args.json:
        print(json.dumps(pairs, ensure_ascii=False, indent=2))
        return

    for item in pairs:
        print(
            f"{item['index']:>2} "
            f"cmd={item['commandid'] or '-':<7} "
            f"rc={item['resultCode'] or '-':<3} "
            f"port={item['port'] or '-':<5} "
            f"page={item['page'] or '-':<20} "
            f"msg={_safe_text(item['msgBody'])[:80]} "
            f"resp={_safe_text(item['response_body'])[:140]}"
        )


if __name__ == "__main__":
    main()
