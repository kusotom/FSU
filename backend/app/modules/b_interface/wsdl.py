from __future__ import annotations

from app.core.config import settings


SC_NAMESPACE = "http://SCService.chinatowercom.com"
FSU_NAMESPACE = "http://FSUService.chinatowercom.com"
SOAPENC_NS = "http://schemas.xmlsoap.org/soap/encoding/"
SOAP_HTTP_TRANSPORT = "http://schemas.xmlsoap.org/soap/http"
SOAP_ENCODING_STYLE = "http://schemas.xmlsoap.org/soap/encoding/"


def _build_wsdl(*, service_name: str, target_namespace: str, endpoint: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<definitions '
        'xmlns="http://schemas.xmlsoap.org/wsdl/" '
        'xmlns:impl="{target_namespace}" '
        'xmlns:intf="{target_namespace}" '
        'xmlns:wsdl="http://schemas.xmlsoap.org/wsdl/" '
        'xmlns:wsdlsoap="http://schemas.xmlsoap.org/wsdl/soap/" '
        'xmlns:soapenc="http://schemas.xmlsoap.org/soap/encoding/" '
        'xmlns:xsd="http://www.w3.org/2001/XMLSchema" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        'targetNamespace="{target_namespace}">\n'
        '  <message name="invokeRequest">\n'
        '    <part name="xmlData" type="soapenc:string"/>\n'
        "  </message>\n"
        '  <message name="invokeResponse">\n'
        '    <part name="invokeReturn" type="soapenc:string"/>\n'
        "  </message>\n"
        '  <portType name="{service_name}">\n'
        '    <operation name="invoke" parameterOrder="xmlData">\n'
        '      <input message="impl:invokeRequest" name="invokeRequest"/>\n'
        '      <output message="impl:invokeResponse" name="invokeResponse"/>\n'
        "    </operation>\n"
        "  </portType>\n"
        '  <binding name="{service_name}SoapBinding" type="impl:{service_name}">\n'
        '    <wsdlsoap:binding style="rpc" transport="http://schemas.xmlsoap.org/soap/http"/>\n'
        '    <operation name="invoke">\n'
        '      <wsdlsoap:operation soapAction=""/>\n'
        '      <input name="invokeRequest">\n'
        '        <wsdlsoap:body use="encoded" encodingStyle="http://schemas.xmlsoap.org/soap/encoding/" namespace="{target_namespace}"/>\n'
        "      </input>\n"
        '      <output name="invokeResponse">\n'
        '        <wsdlsoap:body use="encoded" encodingStyle="http://schemas.xmlsoap.org/soap/encoding/" namespace="{target_namespace}"/>\n'
        "      </output>\n"
        "    </operation>\n"
        "  </binding>\n"
        '  <service name="{service_name}Service">\n'
        '    <port name="{service_name}" binding="impl:{service_name}SoapBinding">\n'
        '      <wsdlsoap:address location="{endpoint}"/>\n'
        "    </port>\n"
        "  </service>\n"
        "</definitions>\n"
    ).format(
        service_name=service_name,
        target_namespace=target_namespace,
        endpoint=endpoint,
    )


def sc_service_wsdl(endpoint: str | None = None) -> str:
    return _build_wsdl(
        service_name="SCService",
        target_namespace=SC_NAMESPACE,
        endpoint=endpoint or settings.b_interface_sc_service_url,
    )


def fsu_service_wsdl(endpoint: str | None = None) -> str:
    return _build_wsdl(
        service_name="FSUService",
        target_namespace=FSU_NAMESPACE,
        endpoint=endpoint or settings.b_interface_fsu_service_url,
    )
