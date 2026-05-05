from __future__ import annotations

from dataclasses import dataclass
import html
import xml.etree.ElementTree as ET


SOAP_ENV_NS = "http://schemas.xmlsoap.org/soap/envelope/"
SOAP_ENC_NS = "http://schemas.xmlsoap.org/soap/encoding/"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"
XSD_NS = "http://www.w3.org/2001/XMLSchema"
SOAP_11_MEDIA_TYPES = {"text/xml", "application/xml", "application/soap+xml"}


class SoapParseError(ValueError):
    pass


@dataclass(frozen=True)
class SoapRequest:
    xml_data: str
    soap_action: str
    content_type: str


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    if ":" in tag:
        return tag.rsplit(":", 1)[1]
    return tag


def _find_first(root: ET.Element, name: str) -> ET.Element | None:
    for elem in root.iter():
        if _local_name(elem.tag) == name:
            return elem
    return None


def _decode_xml_body(body: bytes) -> str:
    for encoding in ("utf-8", "gb18030", "gbk", "latin1"):
        try:
            return body.decode(encoding)
        except UnicodeDecodeError:
            continue
    return body.decode("utf-8", errors="replace")


def parse_soap_request(body: bytes, content_type: str | None, soap_action: str | None) -> SoapRequest:
    if not body:
        raise SoapParseError("empty request body")

    content_type_value = (content_type or "").split(";", 1)[0].strip().lower()
    if content_type_value and content_type_value not in SOAP_11_MEDIA_TYPES:
        raise SoapParseError(f"unsupported content-type: {content_type_value}")

    body_text = _decode_xml_body(body).strip()
    try:
        root = ET.fromstring(body_text)
    except ET.ParseError as exc:
        raise SoapParseError(f"invalid SOAP XML: {exc}") from exc

    if _local_name(root.tag) != "Envelope":
        raise SoapParseError("SOAP envelope root is required")
    body_elem = _find_first(root, "Body")
    if body_elem is None:
        raise SoapParseError("SOAP Body is missing")
    invoke_elem = _find_first(body_elem, "invoke")
    if invoke_elem is None:
        raise SoapParseError("SOAP invoke operation is missing")
    xml_data_elem = _find_first(invoke_elem, "xmlData")
    xml_data = html.unescape((xml_data_elem.text or "").strip()) if xml_data_elem is not None else ""
    if not xml_data:
        raise SoapParseError("SOAP invoke/xmlData is missing")
    return SoapRequest(
        xml_data=xml_data,
        soap_action=(soap_action or "").strip(),
        content_type=content_type_value or "text/xml",
    )


def make_invoke_response(namespace: str, invoke_return_xml: str) -> str:
    escaped = html.escape(invoke_return_xml, quote=False)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<SOAP-ENV:Envelope xmlns:SOAP-ENV="{SOAP_ENV_NS}" xmlns:SOAP-ENC="{SOAP_ENC_NS}" xmlns:soapenc="{SOAP_ENC_NS}" xmlns:xsi="{XSI_NS}" xmlns:xsd="{XSD_NS}" xmlns:ns1="{namespace}">\n'
        f'  <SOAP-ENV:Body SOAP-ENV:encodingStyle="{SOAP_ENC_NS}">\n'
        "    <ns1:invokeResponse>\n"
        f'      <invokeReturn xsi:type="soapenc:string">{escaped}</invokeReturn>\n'
        "    </ns1:invokeResponse>\n"
        "  </SOAP-ENV:Body>\n"
        "</SOAP-ENV:Envelope>\n"
    )


def make_soap_fault(message: str, fault_code: str = "Client") -> str:
    escaped = html.escape(message, quote=False)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<soapenv:Envelope xmlns:soapenv="{SOAP_ENV_NS}">\n'
        "  <soapenv:Body>\n"
        "    <soapenv:Fault>\n"
        f"      <faultcode>{fault_code}</faultcode>\n"
        f"      <faultstring>{escaped}</faultstring>\n"
        "    </soapenv:Fault>\n"
        "  </soapenv:Body>\n"
        "</soapenv:Envelope>\n"
    )
