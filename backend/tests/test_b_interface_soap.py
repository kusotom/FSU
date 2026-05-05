from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import os
import socket
import subprocess

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.routes.b_interface_logs import router as b_interface_logs_router
from app.core.config import settings
from app.models.b_interface_alarm import BInterfaceAlarmHistory, BInterfaceCurrentAlarm
from app.models.b_interface_fsu_status import BInterfaceFsuStatus
from app.models.b_interface_history import BInterfaceHistory
from app.models.b_interface_info_cache import BInterfaceFsuInfoCache, BInterfaceLoginInfoCache
from app.models.b_interface_outbound_call import BInterfaceOutboundCall
from app.models.b_interface_realtime import BInterfaceRealtime
from app.modules.b_interface.alarm_store import reset_session_factory as reset_alarm_session_factory
from app.modules.b_interface.alarm_store import set_session_factory as set_alarm_session_factory
from app.modules.b_interface.client import (
    build_all_devices_code,
    build_get_data_xml,
    build_get_fsuinfo_xml,
    build_get_hisdata_xml,
    build_get_logininfo_xml,
    build_invoke_soap,
    build_time_check_xml,
    parse_invoke_return,
)
from app.modules.b_interface.command_policy import BInterfaceCommandPolicy
from app.modules.b_interface.control_commands import handle_sc_to_fsu_control_command, handle_sc_to_fsu_control_xml
from app.modules.b_interface.config_loader import load_b_interface_config, resolve_signal_mapping
from app.modules.b_interface.info_store import (
    parse_get_fsuinfo_ack,
    parse_get_logininfo_ack,
    reset_session_factory as reset_info_session_factory,
    set_session_factory as set_info_session_factory,
)
from app.modules.b_interface.history_store import list_history, parse_get_hisdata_ack
from app.modules.b_interface.history_store import reset_session_factory as reset_history_session_factory
from app.modules.b_interface.history_store import set_session_factory as set_history_session_factory
from app.modules.b_interface.logging_utils import BInterfaceInvokeLogger
from app.modules.b_interface.outbound_store import reset_session_factory as reset_outbound_session_factory
from app.modules.b_interface.outbound_store import set_session_factory as set_outbound_session_factory
from app.modules.b_interface.realtime_store import parse_get_data_ack
from app.modules.b_interface.realtime_store import reset_session_factory as reset_realtime_session_factory
from app.modules.b_interface.realtime_store import set_session_factory as set_realtime_session_factory
import app.modules.b_interface.router as b_interface_router
from app.modules.b_interface.status_store import reset_session_factory, set_session_factory
from app.modules.b_interface.xml_protocol import parse_b_interface_xml


def _soap_envelope(inner_xml: str, prefix: str = "ns1") -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" '
        f'xmlns:{prefix}="http://SCService.chinatowercom.com">'
        "<soapenv:Body>"
        f"<{prefix}:invoke>"
        f"<xmlData>{inner_xml.replace('<', '&lt;').replace('>', '&gt;')}</xmlData>"
        f"</{prefix}:invoke>"
        "</soapenv:Body>"
        "</soapenv:Envelope>"
    )


def _rpc_encoded_soap_envelope(inner_xml: str, prefix: str = "ns1", namespace: str = "http://SCService.chinatowercom.com") -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<SOAP-ENV:Envelope '
        'xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/" '
        'xmlns:SOAP-ENC="http://schemas.xmlsoap.org/soap/encoding/" '
        'xmlns:soapenc="http://schemas.xmlsoap.org/soap/encoding/" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        'xmlns:xsd="http://www.w3.org/2001/XMLSchema" '
        f'xmlns:{prefix}="{namespace}">'
        '<SOAP-ENV:Body SOAP-ENV:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
        f"<{prefix}:invoke>"
        f'<xmlData xsi:type="soapenc:string">{inner_xml.replace("<", "&lt;").replace(">", "&gt;")}</xmlData>'
        f"</{prefix}:invoke>"
        "</SOAP-ENV:Body>"
        "</SOAP-ENV:Envelope>"
    )


class BInterfaceSoapTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_log_dir = settings.b_interface_log_dir
        self.original_response_mode = settings.b_interface_response_mode
        settings.b_interface_log_dir = self.tempdir.name
        db_path = Path(self.tempdir.name) / "b_interface_test.sqlite3"
        self.engine = create_engine(
            f"sqlite:///{db_path}",
            future=True,
            connect_args={"check_same_thread": False, "timeout": 15},
        )
        self.TestSessionLocal = sessionmaker(
            bind=self.engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
            future=True,
        )
        BInterfaceFsuStatus.__table__.create(bind=self.engine, checkfirst=True)
        BInterfaceCurrentAlarm.__table__.create(bind=self.engine, checkfirst=True)
        BInterfaceAlarmHistory.__table__.create(bind=self.engine, checkfirst=True)
        BInterfaceHistory.__table__.create(bind=self.engine, checkfirst=True)
        BInterfaceFsuInfoCache.__table__.create(bind=self.engine, checkfirst=True)
        BInterfaceLoginInfoCache.__table__.create(bind=self.engine, checkfirst=True)
        BInterfaceOutboundCall.__table__.create(bind=self.engine, checkfirst=True)
        BInterfaceRealtime.__table__.create(bind=self.engine, checkfirst=True)
        set_session_factory(self.TestSessionLocal)
        set_alarm_session_factory(self.TestSessionLocal)
        set_history_session_factory(self.TestSessionLocal)
        set_info_session_factory(self.TestSessionLocal)
        set_outbound_session_factory(self.TestSessionLocal)
        set_realtime_session_factory(self.TestSessionLocal)
        app = FastAPI()
        b_interface_router.invoke_logger = BInterfaceInvokeLogger(self.tempdir.name)
        app.include_router(b_interface_router.service_router)
        app.include_router(b_interface_logs_router)
        self.client = TestClient(app)

    def tearDown(self) -> None:
        settings.b_interface_log_dir = self.original_log_dir
        settings.b_interface_response_mode = self.original_response_mode
        reset_session_factory()
        reset_alarm_session_factory()
        reset_history_session_factory()
        reset_info_session_factory()
        reset_outbound_session_factory()
        reset_realtime_session_factory()
        self.engine.dispose()
        self.tempdir.cleanup()

    def _log_text(self) -> str:
        log_files = list(Path(self.tempdir.name).glob("soap-invoke-*.jsonl"))
        self.assertTrue(log_files, "expected at least one invoke log file")
        return log_files[0].read_text(encoding="utf-8")

    def _real_login_xml(self) -> str:
        return (
            "<Request><PK_Type><Name>LOGIN</Name><Code>101</Code></PK_Type>"
            "<Info>"
            "<UserName></UserName>"
            "<PaSCword>abc123</PaSCword>"
            "<FsuId>51051243812345</FsuId>"
            "<FsuCode>51051243812345</FsuCode>"
            "<FsuIP>192.168.100.100</FsuIP>"
            "<MacId>00:09:F5:FD:85:85</MacId>"
            "<Reg_Mode>2</Reg_Mode>"
            "<FSUVendor>AMS</FSUVendor>"
            "<FSUType>FSU</FSUType>"
            "<FSUClass>INTSTAN</FSUClass>"
            "<Version>21.1.HQ.FSU.WD.AA44.R</Version>"
            "<DictVersion>1</DictVersion>"
            "<DeviceList>"
            "<Device>51051241820004</Device>"
            "<Device>51051241830004</Device>"
            "<Device>51051241840004</Device>"
            "<Device>51051240700002</Device>"
            "<Device>51051243812345</Device>"
            "</DeviceList>"
            "</Info>"
            "</Request>"
        )

    def _real_send_alarm_xml(self, alarm_count: int) -> str:
        alarms = []
        for index in range(1, alarm_count + 1):
            alarms.append(
                "<TAlarm>"
                f"<SerialNo>{1000 + index}</SerialNo>"
                f"<Id>ALARM-{index}</Id>"
                "<FsuId>51051243812345</FsuId>"
                "<FsuCode>51051243812345</FsuCode>"
                f"<DeviceId>510512418{index}0004</DeviceId>"
                f"<DeviceCode>510512418{index}0004</DeviceCode>"
                f"<AlarmTime>2026-05-05 12:0{index}:00</AlarmTime>"
                f"<AlarmLevel>{index}</AlarmLevel>"
                f"<AlarmFlag>{'BEGIN' if index % 2 else 'END'}</AlarmFlag>"
                f"<AlarmDesc>Alarm {index}</AlarmDesc>"
                "</TAlarm>"
            )
        return (
            "<Request><PK_Type><Name>SEND_ALARM</Name><Code>501</Code></PK_Type>"
            "<Info><Values><TAlarmList>"
            + "".join(alarms) +
            "</TAlarmList></Values></Info>"
            "</Request>"
        )

    def _real_send_alarm_missing_fields_xml(self) -> str:
        return (
            "<Request><PK_Type><Name>SEND_ALARM</Name><Code>501</Code></PK_Type>"
            "<Info><Values><TAlarmList>"
            "<TAlarm><SerialNo>2001</SerialNo><AlarmFlag>BEGIN</AlarmFlag></TAlarm>"
            "<TAlarm><Id>ALARM-X</Id><AlarmDesc>Partial alarm</AlarmDesc></TAlarm>"
            "</TAlarmList></Values></Info>"
            "</Request>"
        )

    def _mock_get_data_ack_xml(self) -> str:
        return (
            "<Response><PK_Type><Name>GET_DATA_ACK</Name><Code>402</Code></PK_Type>"
            "<Info><FsuId>51051243812345</FsuId><FsuCode>51051243812345</FsuCode><Time>2026-05-05 13:00:00</Time>"
            "<Values><DeviceList>"
            '<Device Id="51051241820004" Code="51051241820004">'
            '<TSemaphore Id="418199999" Type="DI" MeasuredVal="1" SetupVal="0" Status="ON" />'
            '<TSemaphore Id="S-2" Type="AI" MeasuredVal="23.5" SetupVal="30.0" Status="OK" />'
            "</Device>"
            '<Device Id="51051241830004" Code="51051241830004">'
            '<TSemaphore Id="418101001" Type="AI" MeasuredVal="26.5" SetupVal="30.0" Status="OK" />'
            '<TSemaphore Id="418102001" Type="AI" MeasuredVal="55.0" SetupVal="60.0" Status="OK" />'
            "</Device>"
            "</DeviceList></Values></Info></Response>"
        )

    def _mock_get_data_ack_unknown_xml(self) -> str:
        return (
            "<Response><PK_Type><Name>GET_DATA_ACK</Name><Code>402</Code></PK_Type>"
            "<Info><FsuId>51051243812345</FsuId><FsuCode>51051243812345</FsuCode><Time>2026-05-05 13:00:00</Time>"
            "<Values><DeviceList>"
            '<Device Id="51051241830004" Code="51051241830004">'
            '<TSemaphore Id="418000000" Type="AI" MeasuredVal="99" SetupVal="0" Status="UNKNOWN" />'
            "</Device>"
            "</DeviceList></Values></Info></Response>"
        )

    def _mock_get_fsuinfo_ack_xml(self) -> str:
        return (
            "<Response><PK_Type><Name>GET_FSUINFO_ACK</Name><Code>1702</Code></PK_Type>"
            "<Info><FsuId>51051243812345</FsuId><FsuCode>51051243812345</FsuCode>"
            "<TFSUStatus><CPUUsage>22</CPUUsage><MEMUsage>41</MEMUsage></TFSUStatus><Result>1</Result></Info></Response>"
        )

    def _mock_get_fsuinfo_ack_missing_xml(self) -> str:
        return (
            "<Response><PK_Type><Name>GET_FSUINFO_ACK</Name><Code>1702</Code></PK_Type>"
            "<Info><FsuId>51051243812345</FsuId><Result>1</Result></Info></Response>"
        )

    def _mock_get_logininfo_ack_xml(self) -> str:
        return (
            "<Response><PK_Type><Name>GET_LOGININFO_ACK</Name><Code>1502</Code></PK_Type>"
            "<Info><FsuId>51051243812345</FsuId><FsuCode>51051243812345</FsuCode><SCIP>192.168.100.123</SCIP>"
            "<FsuIP>192.168.100.100</FsuIP><UserName>tower-user</UserName><PaSCword>abc123</PaSCword>"
            "<FTPPwd>ftpsecret</FTPPwd><IPSecIP>10.0.0.2</IPSecIP><IPSecUser>vpn-user</IPSecUser><IPSecPwd>vpn-secret</IPSecPwd>"
            "<FTPUser>ftp-user</FTPUser><DeviceList><Device>51051241820004</Device><Device>51051241830004</Device></DeviceList><Result>1</Result></Info></Response>"
        )

    def _mock_get_hisdata_ack_attr_xml(self) -> str:
        return (
            "<Response><PK_Type><Name>GET_HISDATA_ACK</Name><Code>602</Code></PK_Type>"
            "<Info><FsuId>51051243812345</FsuId><FsuCode>51051243812345</FsuCode><Result>1</Result>"
            "<Values><DeviceList>"
            '<Device Id="51051241830004" Code="51051241830004">'
            '<TSemaphore Id="418101001" Type="AI" MeasuredVal="26.5" SetupVal="30.0" Status="OK" Time="2026-05-05 13:01:00" />'
            '<TSemaphore Id="418102001" Type="AI" MeasuredVal="55.0" SetupVal="60.0" Status="OK" SampleTime="2026-05-05 13:02:00" />'
            "</Device>"
            "</DeviceList></Values></Info></Response>"
        )

    def _mock_get_hisdata_ack_node_xml(self) -> str:
        return (
            "<Response><PK_Type><Name>GET_HISDATA_ACK</Name><Code>602</Code></PK_Type>"
            "<Info><FsuId>51051243812345</FsuId><FsuCode>51051243812345</FsuCode><Result>1</Result>"
            "<Values><TSemaphoreList>"
            "<TSemaphore><DeviceId>51051241830004</DeviceId><Id>418101001</Id><Type>AI</Type><MeasuredVal>27.1</MeasuredVal><Status>OK</Status><CollectTime>2026-05-05 13:03:00</CollectTime></TSemaphore>"
            "<TSemaphore><DeviceId>51051241830004</DeviceId><Id>418000000</Id><Type>AI</Type><Status>MISS</Status></TSemaphore>"
            "</TSemaphoreList></Values></Info></Response>"
        )

    def _set_fsureboot_xml(self) -> str:
        return (
            "<Request><PK_Type><Name>SET_FSUREBOOT</Name><Code>1701</Code></PK_Type>"
            "<Info><FsuId>51051243812345</FsuId><FsuCode>51051243812345</FsuCode><RebootAfterUpgrade>true</RebootAfterUpgrade></Info>"
            "</Request>"
        )

    def _auto_upgrade_xml(self) -> str:
        return (
            "<Request><PK_Type><Name>AUTO_UPGRADE</Name><Code>1801</Code></PK_Type>"
            "<Info><FsuId>51051243812345</FsuId><FsuCode>51051243812345</FsuCode>"
            "<UpgradeUrl>ftp://example.com/fsu.pkg</UpgradeUrl><FTPUser>tower</FTPUser><ftp_password>secret123</ftp_password>"
            "<Version>22.0</Version><RebootAfterUpgrade>true</RebootAfterUpgrade></Info></Request>"
        )

    def _soap_invoke_response(self, inner_xml: str) -> str:
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/" '
            'xmlns:SOAP-ENC="http://schemas.xmlsoap.org/soap/encoding/" '
            'xmlns:soapenc="http://schemas.xmlsoap.org/soap/encoding/" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
            'xmlns:xsd="http://www.w3.org/2001/XMLSchema" '
            'xmlns:ns1="http://FSUService.chinatowercom.com">'
            '<SOAP-ENV:Body SOAP-ENV:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
            f'<ns1:invokeResponse><invokeReturn xsi:type="soapenc:string">{inner_xml.replace("<", "&lt;").replace(">", "&gt;")}</invokeReturn></ns1:invokeResponse>'
            "</SOAP-ENV:Body></SOAP-ENV:Envelope>"
        )

    def _soap_fault_response(self, fault_string: str) -> str:
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/">'
            "<SOAP-ENV:Body><SOAP-ENV:Fault>"
            "<faultcode>SOAP-ENV:Server</faultcode>"
            f"<faultstring>{fault_string}</faultstring>"
            "</SOAP-ENV:Fault></SOAP-ENV:Body></SOAP-ENV:Envelope>"
        )

    def test_logs_include_live_observation_fields_and_samples(self) -> None:
        body = _rpc_encoded_soap_envelope(
            "<Request><PK_Type><Name>GET_DATA</Name><Code>401</Code></PK_Type><Info><FsuId>51051243812345</FsuId><FsuCode>51051243812345</FsuCode><Password>abc123</Password></Info></Request>"
        )
        response = self.client.post("/services/SCService", content=body, headers={"Content-Type": "text/xml", "SOAPAction": '""'})
        self.assertEqual(response.status_code, 200)
        text = self._log_text()
        self.assertIn('"service_name":"SCService"', text)
        self.assertIn('"raw_soap_request_sanitized":', text)
        self.assertIn('"extracted_xmlData_sanitized":', text)
        self.assertIn('"parse_ok":true', text)
        self.assertNotIn("abc123", text)
        samples = list((Path(self.tempdir.name) / "samples").glob("*-GET_DATA.xml"))
        self.assertTrue(samples, "expected sanitized sample file")
        self.assertNotIn("abc123", samples[0].read_text(encoding="utf-8"))

    def test_messages_api_reads_jsonl(self) -> None:
        self.client.post("/services/SCService", content=_rpc_encoded_soap_envelope(self._real_login_xml()), headers={"Content-Type": "text/xml"})
        self.client.post("/services/SCService", content=_rpc_encoded_soap_envelope(self._real_send_alarm_xml(2)), headers={"Content-Type": "text/xml"})
        response = self.client.get("/api/b-interface/messages?limit=2")
        self.assertEqual(response.status_code, 200)
        rows = response.json()
        self.assertEqual(len(rows), 2)
        self.assertIn("message_name", rows[0])
        self.assertIn("alarm_count", rows[0])

    def test_latest_login_api_parses_login(self) -> None:
        self.client.post("/services/SCService", content=_rpc_encoded_soap_envelope(self._real_login_xml()), headers={"Content-Type": "text/xml"})
        response = self.client.get("/api/b-interface/latest-login")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["FsuId"], "51051243812345")
        self.assertEqual(payload["FsuIP"], "192.168.100.100")
        self.assertEqual(payload["FSUVendor"], "AMS")
        self.assertEqual(len(payload["DeviceList"]), 5)
        self.assertNotIn("PaSCword", payload)

    def test_fsu_status_is_upserted_and_listed(self) -> None:
        self.client.post("/services/SCService", content=_rpc_encoded_soap_envelope(self._real_login_xml()), headers={"Content-Type": "text/xml"})
        listing = self.client.get("/api/b-interface/fsus")
        self.assertEqual(listing.status_code, 200)
        rows = listing.json()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["fsu_id"], "51051243812345")
        self.assertEqual(rows[0]["fsu_ip"], "192.168.100.100")
        self.assertEqual(rows[0]["device_list"][0], "51051241820004")
        detail = self.client.get("/api/b-interface/fsus/51051243812345")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["version"], "21.1.HQ.FSU.WD.AA44.R")

    def test_fsu_client_builds_rpc_encoded_get_data_request(self) -> None:
        xml_data = build_get_data_xml("51051243812345", "51051243812345", ["51051241820004", "51051241830004"])
        soap = build_invoke_soap(xml_data)
        self.assertIn("<Name>GET_DATA</Name>", xml_data)
        self.assertIn("<Code>401</Code>", xml_data)
        self.assertIn('Device Id="51051241820004" Code="51051241820004"', xml_data)
        self.assertIn('SOAP-ENV:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"', soap)
        self.assertIn('xsi:type="soapenc:string"', soap)
        self.assertIn("&lt;Name&gt;GET_DATA&lt;/Name&gt;", soap)

    def test_fsu_client_builds_expected_request_codes(self) -> None:
        self.assertIn("<Code>1301</Code>", build_time_check_xml("51051243812345", "51051243812345"))
        self.assertIn("<Code>1701</Code>", build_get_fsuinfo_xml("51051243812345", "51051243812345"))
        self.assertIn("<Code>1501</Code>", build_get_logininfo_xml("51051243812345", "51051243812345"))
        self.assertIn("<Code>601</Code>", build_get_hisdata_xml("51051243812345", "51051243812345", ["51051241830004"], "2026-05-05 12:00:00", "2026-05-05 13:00:00"))

    def test_signal_id_map_ini_parses_418_mapping(self) -> None:
        config = load_b_interface_config()
        self.assertEqual(config.signal_id_map["418"]["418101001"], ("1004001001",))

    def test_init_list_device_type_is_resolved(self) -> None:
        config = load_b_interface_config()
        device = next(device for device in config.devices if device.id == "51051241830004")
        self.assertEqual(device.type, "418")

    def test_monitor_units_base_type_resolves_i2c_temperature(self) -> None:
        config = load_b_interface_config()
        signal = config.monitor_units.signals_by_base_type["1004001001"][0]
        self.assertEqual(signal.signal_name, "I2C温度")
        self.assertEqual(signal.unit, "℃")

    def test_resolve_signal_mapping_maps_temperature(self) -> None:
        mapping = resolve_signal_mapping("51051241830004", "51051241830004", "418101001")
        self.assertEqual(mapping.mapping_status, "mapped")
        self.assertEqual(mapping.signal_name, "I2C温度")
        self.assertEqual(mapping.unit, "℃")

    def test_resolve_signal_mapping_maps_humidity(self) -> None:
        mapping = resolve_signal_mapping("51051241830004", "51051241830004", "418102001")
        self.assertEqual(mapping.mapping_status, "mapped")
        self.assertEqual(mapping.signal_name, "I2C湿度")
        self.assertEqual(mapping.unit, "%")

    def test_resolve_signal_mapping_unknown_keeps_unmapped(self) -> None:
        mapping = resolve_signal_mapping("51051241830004", "51051241830004", "418000000")
        self.assertEqual(mapping.mapping_status, "unmapped")
        self.assertEqual(mapping.signal_name, "")

    def test_resolve_signal_mapping_ambiguous_keeps_candidates(self) -> None:
        mapping = resolve_signal_mapping("51051241820004", "51051241820004", "418199999")
        self.assertEqual(mapping.mapping_status, "ambiguous")
        self.assertEqual(mapping.mapped_ids, ("1004999001", "1004999002"))

    def test_get_data_all_devices_uses_all_nines_semantics(self) -> None:
        self.assertEqual(build_all_devices_code("51051241820004"), "99999999999999")
        self.client.post("/services/SCService", content=_rpc_encoded_soap_envelope(self._real_login_xml()), headers={"Content-Type": "text/xml"})
        response = self.client.post(
            "/api/b-interface/fsus/51051243812345/actions/get-data?dry_run=true",
            json={"all_devices": True},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("99999999999999", response.json()["request_xml"])

    def test_get_hisdata_dry_run_returns_xml_and_does_not_call_endpoint(self) -> None:
        self.client.post("/services/SCService", content=_rpc_encoded_soap_envelope(self._real_login_xml()), headers={"Content-Type": "text/xml"})
        with patch("app.modules.b_interface.client.httpx.post") as mocked_post:
            response = self.client.post(
                "/api/b-interface/fsus/51051243812345/actions/get-hisdata?dry_run=true",
                json={
                    "start_time": "2026-05-05 12:00:00",
                    "end_time": "2026-05-05 13:00:00",
                    "device_list": ["51051241830004"],
                },
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["error_type"], "dry_run")
        self.assertIn("<Name>GET_HISDATA</Name>", payload["xmlData"])
        self.assertIn("<Code>601</Code>", payload["xmlData"])
        self.assertIn("<StartTime>2026-05-05 12:00:00</StartTime>", payload["xmlData"])
        self.assertIn("<EndTime>2026-05-05 13:00:00</EndTime>", payload["xmlData"])
        self.assertIn("51051241830004", payload["xmlData"])
        mocked_post.assert_not_called()

    def test_get_hisdata_time_range_validation(self) -> None:
        self.client.post("/services/SCService", content=_rpc_encoded_soap_envelope(self._real_login_xml()), headers={"Content-Type": "text/xml"})
        bad_order = self.client.post(
            "/api/b-interface/fsus/51051243812345/actions/get-hisdata?dry_run=true",
            json={"start_time": "2026-05-05 13:00:00", "end_time": "2026-05-05 13:00:00"},
        )
        self.assertEqual(bad_order.status_code, 200)
        self.assertEqual(bad_order.json()["error_type"], "invalid_time_range")
        too_wide = self.client.post(
            "/api/b-interface/fsus/51051243812345/actions/get-hisdata?dry_run=true",
            json={"start_time": "2026-05-04 10:00:00", "end_time": "2026-05-05 13:00:00"},
        )
        self.assertEqual(too_wide.status_code, 200)
        self.assertEqual(too_wide.json()["error_type"], "invalid_time_range")
        valid = self.client.post(
            "/api/b-interface/fsus/51051243812345/actions/get-hisdata?dry_run=true",
            json={"start_time": "2026-05-05T12:00:00", "end_time": "2026-05-05T13:00:00"},
        )
        self.assertEqual(valid.status_code, 200)
        self.assertEqual(valid.json()["error_type"], "dry_run")

    def test_fsu_action_dry_run_does_not_call_endpoint(self) -> None:
        self.client.post("/services/SCService", content=_rpc_encoded_soap_envelope(self._real_login_xml()), headers={"Content-Type": "text/xml"})
        with patch("app.modules.b_interface.client.httpx.post") as mocked_post:
            response = self.client.post("/api/b-interface/fsus/51051243812345/actions/get-data?dry_run=true", json={})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["dry_run"])
        self.assertIn("<Name>GET_DATA</Name>", payload["request_xml"])
        self.assertIn("<Name>GET_DATA</Name>", payload["xmlData"])
        self.assertIn("SOAP-ENV:Envelope", payload["soap_request"])
        mocked_post.assert_not_called()

    def test_fsu_action_dry_run_other_commands_return_rpc_encoded_soap(self) -> None:
        self.client.post("/services/SCService", content=_rpc_encoded_soap_envelope(self._real_login_xml()), headers={"Content-Type": "text/xml"})
        cases = [
            ("/api/b-interface/fsus/51051243812345/actions/time-check?dry_run=true", "TIME_CHECK", "1301"),
            ("/api/b-interface/fsus/51051243812345/actions/get-fsuinfo?dry_run=true", "GET_FSUINFO", "1701"),
            ("/api/b-interface/fsus/51051243812345/actions/get-logininfo?dry_run=true", "GET_LOGININFO", "1501"),
        ]
        for path, name, code in cases:
            response = self.client.post(path, json={})
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["action"], name.lower())
            self.assertIn(f"<Name>{name}</Name>", payload["xmlData"])
            self.assertIn(f"<Code>{code}</Code>", payload["xmlData"])
            self.assertIn("SOAP-ENV:Envelope", payload["soap_request"])

    def test_fsu_action_live_call_parses_invoke_return(self) -> None:
        self.client.post("/services/SCService", content=_rpc_encoded_soap_envelope(self._real_login_xml()), headers={"Content-Type": "text/xml"})
        ack_inner = self._mock_get_data_ack_xml()
        response_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/" '
            'xmlns:SOAP-ENC="http://schemas.xmlsoap.org/soap/encoding/" '
            'xmlns:soapenc="http://schemas.xmlsoap.org/soap/encoding/" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
            'xmlns:xsd="http://www.w3.org/2001/XMLSchema" '
            'xmlns:ns1="http://FSUService.chinatowercom.com">'
            '<SOAP-ENV:Body SOAP-ENV:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
            "<ns1:invokeResponse>"
            f'<invokeReturn xsi:type="soapenc:string">{ack_inner.replace("<", "&lt;").replace(">", "&gt;")}</invokeReturn>'
            "</ns1:invokeResponse>"
            "</SOAP-ENV:Body>"
            "</SOAP-ENV:Envelope>"
        )
        mock_response = httpx.Response(
            200,
            content=response_xml.encode("utf-8"),
            request=httpx.Request("POST", "http://192.168.100.100:8080/services/FSUService"),
        )
        with patch("app.modules.b_interface.client.httpx.post", return_value=mock_response) as mocked_post:
            response = self.client.post(
                "/api/b-interface/fsus/51051243812345/actions/get-data",
                json={"dry_run": False},
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertIn("GET_DATA_ACK", payload["invoke_return"])
        self.assertEqual(payload["realtime_count"], 4)
        mocked_post.assert_called_once()

    def test_parse_get_data_ack_extracts_realtime_values(self) -> None:
        rows = parse_get_data_ack(self._mock_get_data_ack_xml())
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[0].fsu_id, "51051243812345")
        self.assertEqual(rows[0].device_id, "51051241820004")
        self.assertEqual(rows[0].semaphore_id, "418199999")
        self.assertEqual(rows[0].measured_val, "1")
        self.assertEqual(rows[0].mapping_status, "ambiguous")
        self.assertEqual(rows[2].signal_name, "I2C温度")
        self.assertEqual(rows[3].signal_name, "I2C湿度")

    def test_parse_get_data_ack_unknown_signal_is_preserved(self) -> None:
        rows = parse_get_data_ack(self._mock_get_data_ack_unknown_xml())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].mapping_status, "unmapped")
        self.assertEqual(rows[0].semaphore_id, "418000000")

    def test_parse_get_hisdata_ack_attribute_style_extracts_rows(self) -> None:
        rows = parse_get_hisdata_ack(self._mock_get_hisdata_ack_attr_xml())
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].base_type_id, "1004001001")
        self.assertEqual(rows[1].base_type_id, "1004001002")
        self.assertEqual(rows[0].mapping_status, "mapped")
        self.assertEqual(rows[1].mapping_status, "mapped")

    def test_parse_get_hisdata_ack_node_style_extracts_rows(self) -> None:
        rows = parse_get_hisdata_ack(self._mock_get_hisdata_ack_node_xml())
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].sample_time.isoformat(), "2026-05-05T13:03:00+00:00")
        self.assertEqual(rows[1].mapping_status, "unmapped")

    def test_get_hisdata_live_call_saves_history_and_api_returns_rows(self) -> None:
        self.client.post("/services/SCService", content=_rpc_encoded_soap_envelope(self._real_login_xml()), headers={"Content-Type": "text/xml"})
        mock_response = httpx.Response(
            200,
            content=self._soap_invoke_response(self._mock_get_hisdata_ack_attr_xml()).encode("utf-8"),
            request=httpx.Request("POST", "http://192.168.100.100:8080/services/FSUService"),
        )
        with patch("app.modules.b_interface.client.httpx.post", return_value=mock_response):
            response = self.client.post(
                "/api/b-interface/fsus/51051243812345/actions/get-hisdata?dry_run=false",
                json={"start_time": "2026-05-05 12:00:00", "end_time": "2026-05-05 13:00:00"},
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["business_name"], "GET_HISDATA_ACK")
        self.assertGreaterEqual(payload["history_count"], 2)
        rows = self.client.get("/api/b-interface/fsus/51051243812345/history").json()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["source_call_id"], payload["call_id"])
        filtered = self.client.get("/api/b-interface/history?fsu_id=51051243812345&semaphore_id=418101001").json()
        self.assertEqual(len(filtered), 1)

    def test_get_hisdata_duplicate_import_does_not_grow_unbounded(self) -> None:
        self.client.post("/services/SCService", content=_rpc_encoded_soap_envelope(self._real_login_xml()), headers={"Content-Type": "text/xml"})
        mock_response = httpx.Response(
            200,
            content=self._soap_invoke_response(self._mock_get_hisdata_ack_attr_xml()).encode("utf-8"),
            request=httpx.Request("POST", "http://192.168.100.100:8080/services/FSUService"),
        )
        with patch("app.modules.b_interface.client.httpx.post", return_value=mock_response):
            self.client.post("/api/b-interface/fsus/51051243812345/actions/get-hisdata?dry_run=false", json={"start_time": "2026-05-05 12:00:00", "end_time": "2026-05-05 13:00:00"})
            self.client.post("/api/b-interface/fsus/51051243812345/actions/get-hisdata?dry_run=false", json={"start_time": "2026-05-05 12:00:00", "end_time": "2026-05-05 13:00:00"})
        rows = list_history(limit=10, fsu_id="51051243812345")
        self.assertEqual(len(rows), 2)

    def test_get_hisdata_missing_fields_do_not_return_500(self) -> None:
        self.client.post("/services/SCService", content=_rpc_encoded_soap_envelope(self._real_login_xml()), headers={"Content-Type": "text/xml"})
        missing_xml = (
            "<Response><PK_Type><Name>GET_HISDATA_ACK</Name><Code>602</Code></PK_Type>"
            "<Info><FsuId>51051243812345</FsuId><Values><DeviceList>"
            '<Device Id="51051241830004"><TSemaphore Id="418000000"><Status>MISS</Status></TSemaphore></Device>'
            "</DeviceList></Values></Info></Response>"
        )
        mock_response = httpx.Response(
            200,
            content=self._soap_invoke_response(missing_xml).encode("utf-8"),
            request=httpx.Request("POST", "http://192.168.100.100:8080/services/FSUService"),
        )
        with patch("app.modules.b_interface.client.httpx.post", return_value=mock_response):
            response = self.client.post("/api/b-interface/fsus/51051243812345/actions/get-hisdata?dry_run=false", json={"start_time": "2026-05-05 12:00:00", "end_time": "2026-05-05 13:00:00"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])

    def test_get_data_live_call_saves_realtime_and_api_returns_rows(self) -> None:
        self.client.post("/services/SCService", content=_rpc_encoded_soap_envelope(self._real_login_xml()), headers={"Content-Type": "text/xml"})
        ack_inner = self._mock_get_data_ack_xml()
        response_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/" '
            'xmlns:SOAP-ENC="http://schemas.xmlsoap.org/soap/encoding/" '
            'xmlns:soapenc="http://schemas.xmlsoap.org/soap/encoding/" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
            'xmlns:xsd="http://www.w3.org/2001/XMLSchema" '
            'xmlns:ns1="http://FSUService.chinatowercom.com">'
            '<SOAP-ENV:Body SOAP-ENV:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
            "<ns1:invokeResponse>"
            f'<invokeReturn xsi:type="soapenc:string">{ack_inner.replace("<", "&lt;").replace(">", "&gt;")}</invokeReturn>'
            "</ns1:invokeResponse>"
            "</SOAP-ENV:Body>"
            "</SOAP-ENV:Envelope>"
        )
        mock_response = httpx.Response(
            200,
            content=response_xml.encode("utf-8"),
            request=httpx.Request("POST", "http://192.168.100.100:8080/services/FSUService"),
        )
        with patch("app.modules.b_interface.client.httpx.post", return_value=mock_response):
            response = self.client.post("/api/b-interface/fsus/51051243812345/actions/get-data?dry_run=false", json={})
        self.assertEqual(response.status_code, 200)
        per_fsu = self.client.get("/api/b-interface/fsus/51051243812345/realtime")
        self.assertEqual(per_fsu.status_code, 200)
        fsu_rows = per_fsu.json()
        self.assertEqual(len(fsu_rows), 4)
        self.assertEqual(fsu_rows[0]["fsu_id"], "51051243812345")
        self.assertIn(fsu_rows[0]["mapping_status"], {"mapped", "ambiguous", "unmapped"})
        temp = next(row for row in fsu_rows if row["semaphore_id"] == "418101001")
        humidity = next(row for row in fsu_rows if row["semaphore_id"] == "418102001")
        ambiguous = next(row for row in fsu_rows if row["semaphore_id"] == "418199999")
        self.assertEqual(temp["signal_name"], "I2C温度")
        self.assertEqual(temp["unit"], "℃")
        self.assertEqual(humidity["signal_name"], "I2C湿度")
        self.assertEqual(humidity["unit"], "%")
        self.assertEqual(ambiguous["mapping_status"], "ambiguous")
        self.assertEqual(ambiguous["mapped_ids"], ["1004999001", "1004999002"])
        by_fsu = self.client.get("/api/b-interface/realtime?fsu_id=51051243812345")
        self.assertEqual(by_fsu.status_code, 200)
        self.assertEqual(len(by_fsu.json()), 4)
        by_device = self.client.get("/api/b-interface/realtime?device_id=51051241820004")
        self.assertEqual(by_device.status_code, 200)
        self.assertEqual(len(by_device.json()), 2)

    def test_overview_api_handles_empty_and_populated_state(self) -> None:
        empty = self.client.get("/api/b-interface/overview")
        self.assertEqual(empty.status_code, 200)
        self.assertEqual(empty.json()["fsu_count"], 0)
        self.client.post("/services/SCService", content=_rpc_encoded_soap_envelope(self._real_login_xml()), headers={"Content-Type": "text/xml"})
        populated = self.client.get("/api/b-interface/overview")
        self.assertEqual(populated.status_code, 200)
        payload = populated.json()
        self.assertEqual(payload["fsu_count"], 1)
        self.assertIn("recent_messages", payload)

    def test_parse_invoke_return_supports_rpc_encoded_response(self) -> None:
        response_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/" '
            'xmlns:ns1="http://FSUService.chinatowercom.com">'
            "<SOAP-ENV:Body><ns1:invokeResponse><return>&lt;Response&gt;&lt;PK_Type&gt;&lt;Name&gt;TIME_CHECK_ACK&lt;/Name&gt;&lt;/PK_Type&gt;&lt;/Response&gt;</return></ns1:invokeResponse></SOAP-ENV:Body>"
            "</SOAP-ENV:Envelope>"
        )
        self.assertIn("TIME_CHECK_ACK", parse_invoke_return(response_xml))

    def test_parse_get_fsuinfo_ack_extracts_cpu_and_mem(self) -> None:
        parsed = parse_get_fsuinfo_ack(self._mock_get_fsuinfo_ack_xml())
        self.assertEqual(parsed.fsu_id, "51051243812345")
        self.assertEqual(parsed.cpu_usage, "22")
        self.assertEqual(parsed.mem_usage, "41")
        self.assertEqual(parsed.result, "1")

    def test_parse_get_fsuinfo_ack_missing_fields_does_not_fail(self) -> None:
        parsed = parse_get_fsuinfo_ack(self._mock_get_fsuinfo_ack_missing_xml())
        self.assertEqual(parsed.fsu_id, "51051243812345")
        self.assertEqual(parsed.cpu_usage, "")
        self.assertEqual(parsed.mem_usage, "")

    def test_parse_get_logininfo_ack_redacts_passwords(self) -> None:
        parsed = parse_get_logininfo_ack(self._mock_get_logininfo_ack_xml())
        self.assertEqual(parsed.sc_ip, "192.168.100.123")
        self.assertEqual(parsed.fsu_ip, "192.168.100.100")
        self.assertEqual(parsed.username, "tower-user")
        self.assertEqual(parsed.device_list, ("51051241820004", "51051241830004"))
        self.assertNotIn("abc123", parsed.raw_xml_sanitized)
        self.assertNotIn("ftpsecret", parsed.raw_xml_sanitized)
        self.assertNotIn("vpn-secret", parsed.raw_xml_sanitized)

    def test_get_fsuinfo_action_saves_cache_and_api_returns_it(self) -> None:
        self.client.post("/services/SCService", content=_rpc_encoded_soap_envelope(self._real_login_xml()), headers={"Content-Type": "text/xml"})
        ack_inner = self._mock_get_fsuinfo_ack_xml()
        response_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/" '
            'xmlns:SOAP-ENC="http://schemas.xmlsoap.org/soap/encoding/" '
            'xmlns:soapenc="http://schemas.xmlsoap.org/soap/encoding/" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
            'xmlns:xsd="http://www.w3.org/2001/XMLSchema" '
            'xmlns:ns1="http://FSUService.chinatowercom.com">'
            '<SOAP-ENV:Body SOAP-ENV:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
            f"<ns1:invokeResponse><invokeReturn xsi:type=\"soapenc:string\">{ack_inner.replace('<', '&lt;').replace('>', '&gt;')}</invokeReturn></ns1:invokeResponse>"
            "</SOAP-ENV:Body></SOAP-ENV:Envelope>"
        )
        mock_response = httpx.Response(200, content=response_xml.encode("utf-8"), request=httpx.Request("POST", "http://192.168.100.100:8080/services/FSUService"))
        with patch("app.modules.b_interface.client.httpx.post", return_value=mock_response):
            response = self.client.post("/api/b-interface/fsus/51051243812345/actions/get-fsuinfo?dry_run=false", json={})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["parsed"]["cpu_usage"], "22")
        cached = self.client.get("/api/b-interface/fsus/51051243812345/fsuinfo")
        self.assertEqual(cached.status_code, 200)
        self.assertEqual(cached.json()["mem_usage"], "41")

    def test_get_logininfo_action_saves_cache_and_api_returns_it(self) -> None:
        self.client.post("/services/SCService", content=_rpc_encoded_soap_envelope(self._real_login_xml()), headers={"Content-Type": "text/xml"})
        ack_inner = self._mock_get_logininfo_ack_xml()
        response_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/" '
            'xmlns:SOAP-ENC="http://schemas.xmlsoap.org/soap/encoding/" '
            'xmlns:soapenc="http://schemas.xmlsoap.org/soap/encoding/" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
            'xmlns:xsd="http://www.w3.org/2001/XMLSchema" '
            'xmlns:ns1="http://FSUService.chinatowercom.com">'
            '<SOAP-ENV:Body SOAP-ENV:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
            f"<ns1:invokeResponse><invokeReturn xsi:type=\"soapenc:string\">{ack_inner.replace('<', '&lt;').replace('>', '&gt;')}</invokeReturn></ns1:invokeResponse>"
            "</SOAP-ENV:Body></SOAP-ENV:Envelope>"
        )
        mock_response = httpx.Response(200, content=response_xml.encode("utf-8"), request=httpx.Request("POST", "http://192.168.100.100:8080/services/FSUService"))
        with patch("app.modules.b_interface.client.httpx.post", return_value=mock_response):
            response = self.client.post("/api/b-interface/fsus/51051243812345/actions/get-logininfo?dry_run=false", json={})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["parsed"]["sc_ip"], "192.168.100.123")
        self.assertEqual(payload["parsed"]["ftp_user"], "ftp-user")
        self.assertNotIn("PaSCword", payload["parsed"])
        cached = self.client.get("/api/b-interface/fsus/51051243812345/logininfo")
        self.assertEqual(cached.status_code, 200)
        body = cached.json()
        self.assertEqual(body["username"], "tower-user")
        self.assertEqual(body["device_list"], ["51051241820004", "51051241830004"])
        self.assertNotIn("abc123", body["raw_xml_sanitized"])

    def test_outbound_dry_run_records_audit(self) -> None:
        self.client.post("/services/SCService", content=_rpc_encoded_soap_envelope(self._real_login_xml()), headers={"Content-Type": "text/xml"})
        response = self.client.post("/api/b-interface/fsus/51051243812345/actions/get-data?dry_run=true", json={})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["error_type"], "dry_run")
        listing = self.client.get("/api/b-interface/outbound-calls?limit=10")
        self.assertEqual(listing.status_code, 200)
        rows = listing.json()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["error_type"], "dry_run")
        detail = self.client.get(f"/api/b-interface/outbound-calls/{payload['call_id']}")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["call_id"], payload["call_id"])

    def test_outbound_invalid_endpoint_returns_invalid_endpoint(self) -> None:
        self.client.post("/services/SCService", content=_rpc_encoded_soap_envelope(self._real_login_xml()), headers={"Content-Type": "text/xml"})
        response = self.client.post(
            "/api/b-interface/fsus/51051243812345/actions/get-data?dry_run=false",
            json={"endpoint": "not-a-url"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error_type"], "invalid_endpoint")

    def test_outbound_connection_failed_returns_connection_failed(self) -> None:
        self.client.post("/services/SCService", content=_rpc_encoded_soap_envelope(self._real_login_xml()), headers={"Content-Type": "text/xml"})
        request = httpx.Request("POST", "http://192.168.100.100:8080/services/FSUService")
        with patch("app.modules.b_interface.client.httpx.post", side_effect=httpx.ConnectError("connect failed", request=request)):
            response = self.client.post("/api/b-interface/fsus/51051243812345/actions/get-data?dry_run=false", json={})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["error_type"], "connection_failed")

    def test_outbound_timeout_returns_timeout(self) -> None:
        self.client.post("/services/SCService", content=_rpc_encoded_soap_envelope(self._real_login_xml()), headers={"Content-Type": "text/xml"})
        request = httpx.Request("POST", "http://192.168.100.100:8080/services/FSUService")
        with patch("app.modules.b_interface.client.httpx.post", side_effect=httpx.ReadTimeout("timed out", request=request)):
            response = self.client.post(
                "/api/b-interface/fsus/51051243812345/actions/time-check",
                json={"dry_run": False, "timeout_seconds": 0.2},
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error_type"], "timeout")

    def test_outbound_http_error_returns_http_error(self) -> None:
        self.client.post("/services/SCService", content=_rpc_encoded_soap_envelope(self._real_login_xml()), headers={"Content-Type": "text/xml"})
        mock_response = httpx.Response(
            500,
            content=b"server error",
            request=httpx.Request("POST", "http://192.168.100.100:8080/services/FSUService"),
        )
        with patch("app.modules.b_interface.client.httpx.post", return_value=mock_response):
            response = self.client.post("/api/b-interface/fsus/51051243812345/actions/get-data?dry_run=false", json={})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error_type"], "http_error")
        self.assertEqual(payload["http_status"], 500)

    def test_outbound_soap_fault_returns_soap_fault(self) -> None:
        self.client.post("/services/SCService", content=_rpc_encoded_soap_envelope(self._real_login_xml()), headers={"Content-Type": "text/xml"})
        mock_response = httpx.Response(
            200,
            content=self._soap_fault_response("fault detail").encode("utf-8"),
            request=httpx.Request("POST", "http://192.168.100.100:8080/services/FSUService"),
        )
        with patch("app.modules.b_interface.client.httpx.post", return_value=mock_response):
            response = self.client.post("/api/b-interface/fsus/51051243812345/actions/get-data?dry_run=false", json={})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error_type"], "soap_fault")
        self.assertIn("fault detail", payload["error_message"])

    def test_outbound_empty_response_returns_empty_response(self) -> None:
        self.client.post("/services/SCService", content=_rpc_encoded_soap_envelope(self._real_login_xml()), headers={"Content-Type": "text/xml"})
        mock_response = httpx.Response(
            200,
            content=b"",
            request=httpx.Request("POST", "http://192.168.100.100:8080/services/FSUService"),
        )
        with patch("app.modules.b_interface.client.httpx.post", return_value=mock_response):
            response = self.client.post("/api/b-interface/fsus/51051243812345/actions/get-data?dry_run=false", json={})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["error_type"], "empty_response")

    def test_outbound_empty_invoke_return_returns_empty_invoke_return(self) -> None:
        self.client.post("/services/SCService", content=_rpc_encoded_soap_envelope(self._real_login_xml()), headers={"Content-Type": "text/xml"})
        soap_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/" xmlns:ns1="http://FSUService.chinatowercom.com">'
            "<SOAP-ENV:Body><ns1:invokeResponse></ns1:invokeResponse></SOAP-ENV:Body></SOAP-ENV:Envelope>"
        )
        mock_response = httpx.Response(
            200,
            content=soap_xml.encode("utf-8"),
            request=httpx.Request("POST", "http://192.168.100.100:8080/services/FSUService"),
        )
        with patch("app.modules.b_interface.client.httpx.post", return_value=mock_response):
            response = self.client.post("/api/b-interface/fsus/51051243812345/actions/get-data?dry_run=false", json={})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["error_type"], "empty_invoke_return")

    def test_outbound_invalid_business_xml_returns_invalid_business_xml(self) -> None:
        self.client.post("/services/SCService", content=_rpc_encoded_soap_envelope(self._real_login_xml()), headers={"Content-Type": "text/xml"})
        mock_response = httpx.Response(
            200,
            content=self._soap_invoke_response("not-xml").encode("utf-8"),
            request=httpx.Request("POST", "http://192.168.100.100:8080/services/FSUService"),
        )
        with patch("app.modules.b_interface.client.httpx.post", return_value=mock_response):
            response = self.client.post("/api/b-interface/fsus/51051243812345/actions/get-data?dry_run=false", json={})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["error_type"], "invalid_business_xml")

    def test_outbound_unexpected_business_ack_returns_unexpected_business_ack(self) -> None:
        self.client.post("/services/SCService", content=_rpc_encoded_soap_envelope(self._real_login_xml()), headers={"Content-Type": "text/xml"})
        login_ack = "<Response><PK_Type><Name>LOGIN_ACK</Name><Code>102</Code></PK_Type><Info><Result>1</Result></Info></Response>"
        mock_response = httpx.Response(
            200,
            content=self._soap_invoke_response(login_ack).encode("utf-8"),
            request=httpx.Request("POST", "http://192.168.100.100:8080/services/FSUService"),
        )
        with patch("app.modules.b_interface.client.httpx.post", return_value=mock_response):
            response = self.client.post("/api/b-interface/fsus/51051243812345/actions/get-data?dry_run=false", json={})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error_type"], "unexpected_business_ack")
        self.assertEqual(payload["business_name"], "LOGIN_ACK")

    def test_outbound_success_get_data_returns_ok_true(self) -> None:
        self.client.post("/services/SCService", content=_rpc_encoded_soap_envelope(self._real_login_xml()), headers={"Content-Type": "text/xml"})
        mock_response = httpx.Response(
            200,
            content=self._soap_invoke_response(self._mock_get_data_ack_xml()).encode("utf-8"),
            request=httpx.Request("POST", "http://192.168.100.100:8080/services/FSUService"),
        )
        with patch("app.modules.b_interface.client.httpx.post", return_value=mock_response):
            response = self.client.post("/api/b-interface/fsus/51051243812345/actions/get-data?dry_run=false", json={})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["error_type"], "none")
        self.assertEqual(payload["business_name"], "GET_DATA_ACK")

    def test_outbound_calls_api_filters_and_redacts_sensitive_fields(self) -> None:
        self.client.post("/services/SCService", content=_rpc_encoded_soap_envelope(self._real_login_xml()), headers={"Content-Type": "text/xml"})
        mock_response = httpx.Response(
            200,
            content=self._soap_invoke_response(self._mock_get_logininfo_ack_xml()).encode("utf-8"),
            request=httpx.Request("POST", "http://192.168.100.100:8080/services/FSUService"),
        )
        with patch("app.modules.b_interface.client.httpx.post", return_value=mock_response):
            response = self.client.post(
                "/api/b-interface/fsus/51051243812345/actions/get-logininfo?dry_run=false",
                json={"endpoint": "http://192.168.100.100:8080/services/FSUService"},
            )
        self.assertEqual(response.status_code, 200)
        call_id = response.json()["call_id"]
        listing = self.client.get("/api/b-interface/outbound-calls?limit=10&fsu_id=51051243812345&action=get_logininfo&error_type=none")
        self.assertEqual(listing.status_code, 200)
        rows = listing.json()
        self.assertEqual(len(rows), 1)
        detail = self.client.get(f"/api/b-interface/outbound-calls/{call_id}")
        self.assertEqual(detail.status_code, 200)
        payload = detail.json()
        self.assertEqual(payload["call_id"], call_id)
        self.assertNotIn("abc123", payload["request_xml_sanitized"])
        self.assertNotIn("abc123", payload["response_text_sanitized"])
        self.assertNotIn("ftpsecret", payload["response_text_sanitized"])
        self.assertNotIn("vpn-secret", payload["response_text_sanitized"])

    def test_fsu_action_timeout_does_not_return_500(self) -> None:
        self.client.post("/services/SCService", content=_rpc_encoded_soap_envelope(self._real_login_xml()), headers={"Content-Type": "text/xml"})
        with patch("app.modules.b_interface.client.httpx.post", side_effect=httpx.TimeoutException("timed out")):
            response = self.client.post(
                "/api/b-interface/fsus/51051243812345/actions/time-check",
                json={"dry_run": False, "timeout_seconds": 0.2},
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error_type"], "timeout")
        self.assertIn("timed out", payload["error_message"])

    def test_alarms_api_parses_send_alarm(self) -> None:
        self.client.post("/services/SCService", content=_rpc_encoded_soap_envelope(self._real_send_alarm_xml(3)), headers={"Content-Type": "text/xml"})
        response = self.client.get("/api/b-interface/alarms/current?limit=2")
        self.assertEqual(response.status_code, 200)
        rows = response.json()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["fsu_id"], "51051243812345")
        self.assertIn("serial_no", rows[0])

    def test_send_alarm_begin_creates_current_alarm(self) -> None:
        body = _rpc_encoded_soap_envelope(self._real_send_alarm_xml(1))
        response = self.client.post("/services/SCService", content=body, headers={"Content-Type": "text/xml"})
        self.assertEqual(response.status_code, 200)
        current = self.client.get("/api/b-interface/alarms/current")
        self.assertEqual(current.status_code, 200)
        rows = current.json()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "active")
        self.assertEqual(rows[0]["serial_no"], "1001")

    def test_send_alarm_end_clears_current_and_writes_history(self) -> None:
        begin_xml = (
            "<Request><PK_Type><Name>SEND_ALARM</Name><Code>501</Code></PK_Type>"
            "<Info><Values><TAlarmList>"
            "<TAlarm><SerialNo>5001</SerialNo><Id>ALARM-CLEAR</Id><FsuId>51051243812345</FsuId><FsuCode>51051243812345</FsuCode>"
            "<DeviceId>51051241820004</DeviceId><DeviceCode>51051241820004</DeviceCode><AlarmTime>2026-05-05 12:01:00</AlarmTime>"
            "<AlarmLevel>1</AlarmLevel><AlarmFlag>BEGIN</AlarmFlag><AlarmDesc>Door open</AlarmDesc></TAlarm>"
            "</TAlarmList></Values></Info></Request>"
        )
        end_xml = begin_xml.replace("<AlarmFlag>BEGIN</AlarmFlag>", "<AlarmFlag>END</AlarmFlag>").replace(
            "<AlarmTime>2026-05-05 12:01:00</AlarmTime>",
            "<AlarmTime>2026-05-05 12:06:00</AlarmTime>",
        )
        self.client.post("/services/SCService", content=_rpc_encoded_soap_envelope(begin_xml), headers={"Content-Type": "text/xml"})
        response = self.client.post("/services/SCService", content=_rpc_encoded_soap_envelope(end_xml), headers={"Content-Type": "text/xml"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("SEND_ALARM_ACK", response.text)
        current = self.client.get("/api/b-interface/alarms/current")
        self.assertEqual(current.status_code, 200)
        self.assertEqual(current.json(), [])
        history = self.client.get("/api/b-interface/alarms/history")
        self.assertEqual(history.status_code, 200)
        rows = history.json()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "cleared")
        self.assertEqual(rows[0]["begin_time"], "2026-05-05 12:01:00")
        self.assertEqual(rows[0]["end_time"], "2026-05-05 12:06:00")
        self.assertEqual(rows[0]["duration_seconds"], 300)

    def test_send_alarm_end_only_does_not_error(self) -> None:
        end_only_xml = (
            "<Request><PK_Type><Name>SEND_ALARM</Name><Code>501</Code></PK_Type>"
            "<Info><Values><TAlarmList>"
            "<TAlarm><SerialNo>7001</SerialNo><Id>ALARM-END-ONLY</Id><FsuId>51051243812345</FsuId><FsuCode>51051243812345</FsuCode>"
            "<DeviceId>51051241820004</DeviceId><DeviceCode>51051241820004</DeviceCode><AlarmTime>2026-05-05 12:10:00</AlarmTime>"
            "<AlarmLevel>2</AlarmLevel><AlarmFlag>END</AlarmFlag><AlarmDesc>Recovered</AlarmDesc></TAlarm>"
            "</TAlarmList></Values></Info></Request>"
        )
        response = self.client.post("/services/SCService", content=_rpc_encoded_soap_envelope(end_only_xml), headers={"Content-Type": "text/xml"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("SEND_ALARM_ACK", response.text)
        history = self.client.get("/api/b-interface/alarms/history")
        self.assertEqual(history.status_code, 200)
        rows = history.json()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "end_only")

    def test_send_alarm_multiple_entries_are_processed_together(self) -> None:
        body = _rpc_encoded_soap_envelope(self._real_send_alarm_xml(3))
        response = self.client.post("/services/SCService", content=body, headers={"Content-Type": "text/xml"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("&lt;AlarmCount&gt;3&lt;/AlarmCount&gt;", response.text)
        current = self.client.get("/api/b-interface/alarms/current")
        history = self.client.get("/api/b-interface/alarms/history")
        merged = self.client.get("/api/b-interface/alarms?limit=3")
        self.assertEqual(len(current.json()), 2)
        self.assertEqual(len(history.json()), 1)
        self.assertEqual(len(merged.json()), 3)

    def test_samples_api_blocks_path_traversal(self) -> None:
        self.client.post("/services/SCService", content=_rpc_encoded_soap_envelope(self._real_login_xml()), headers={"Content-Type": "text/xml"})
        listing = self.client.get("/api/b-interface/samples")
        self.assertEqual(listing.status_code, 200)
        self.assertTrue(listing.json())
        blocked = self.client.get("/api/b-interface/samples/%2E%2E%2Fsecret.xml")
        self.assertEqual(blocked.status_code, 400)

    def test_scservice_wsdl(self) -> None:
        response = self.client.get("/services/SCService?wsdl")
        self.assertEqual(response.status_code, 200)
        text = response.text
        self.assertTrue("wsdl:definitions" in text or "<definitions" in text)
        self.assertIn("http://SCService.chinatowercom.com", text)
        self.assertIn('operation name="invoke"', text)
        self.assertIn("xmlData", text)
        self.assertIn("invokeReturn", text)
        self.assertIn('style="rpc"', text)
        self.assertIn('use="encoded"', text)
        self.assertIn("soapenc:string", text)
        self.assertIn("SCServiceSoapBinding", text)

    def test_fsuservice_wsdl(self) -> None:
        response = self.client.get("/services/FSUService?wsdl")
        self.assertEqual(response.status_code, 200)
        text = response.text
        self.assertIn("http://FSUService.chinatowercom.com", text)
        self.assertIn('style="rpc"', text)
        self.assertIn('use="encoded"', text)
        self.assertIn("soapenc:string", text)
        self.assertIn("FSUServiceSoapBinding", text)

    def test_login_returns_login_ack(self) -> None:
        settings.b_interface_response_mode = "compat"
        body = _rpc_encoded_soap_envelope(self._real_login_xml())
        response = self.client.post("/services/SCService", content=body, headers={"Content-Type": "text/xml"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("LOGIN_ACK", response.text)
        self.assertIn("<ns1:invokeResponse>", response.text)
        self.assertIn('xsi:type="soapenc:string"', response.text)
        self.assertIn("&lt;FsuId&gt;51051243812345&lt;/FsuId&gt;", response.text)
        self.assertIn("&lt;FsuCode&gt;51051243812345&lt;/FsuCode&gt;", response.text)

    def test_login_ack_strict_mode_is_b2016_minimal(self) -> None:
        settings.b_interface_response_mode = "strict"
        body = _rpc_encoded_soap_envelope(self._real_login_xml())
        response = self.client.post("/services/SCService", content=body, headers={"Content-Type": "text/xml"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("LOGIN_ACK", response.text)
        self.assertIn("&lt;SCIP&gt;192.168.100.123&lt;/SCIP&gt;", response.text)
        self.assertIn("&lt;RightLevel&gt;2&lt;/RightLevel&gt;", response.text)
        self.assertNotIn("&lt;FsuId&gt;", response.text)
        self.assertNotIn("&lt;FsuCode&gt;", response.text)
        self.assertNotIn("&lt;Result&gt;", response.text)

    def test_login_ack_compat_mode_keeps_current_behavior(self) -> None:
        settings.b_interface_response_mode = "compat"
        body = _rpc_encoded_soap_envelope(self._real_login_xml())
        response = self.client.post("/services/SCService", content=body, headers={"Content-Type": "text/xml"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("&lt;FsuId&gt;51051243812345&lt;/FsuId&gt;", response.text)
        self.assertIn("&lt;FsuCode&gt;51051243812345&lt;/FsuCode&gt;", response.text)
        self.assertIn("&lt;SCIP&gt;192.168.100.123&lt;/SCIP&gt;", response.text)
        self.assertIn("&lt;RightLevel&gt;2&lt;/RightLevel&gt;", response.text)

    def test_get_data_returns_get_data_ack(self) -> None:
        body = _rpc_encoded_soap_envelope(
            "<Request><PK_Type><Name>GET_DATA</Name><Code>401</Code></PK_Type><Info><FsuId>51051243812345</FsuId><FsuCode>51051243812345</FsuCode></Info></Request>",
            prefix="invokeNs",
        )
        response = self.client.post("/services/SCService", content=body, headers={"Content-Type": "application/xml"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("GET_DATA_ACK", response.text)
        self.assertIn("51051241900002", response.text)
        self.assertIn('xsi:type="soapenc:string"', response.text)

    def test_send_alarm_returns_send_alarm_ack(self) -> None:
        settings.b_interface_response_mode = "compat"
        body = _soap_envelope(self._real_send_alarm_xml(1))
        response = self.client.post(
            "/services/SCService",
            content=body,
            headers={"Content-Type": "application/soap+xml", "SOAPAction": '""'},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("SEND_ALARM_ACK", response.text)
        self.assertIn("&lt;AlarmCount&gt;1&lt;/AlarmCount&gt;", response.text)

    def test_send_alarm_ack_strict_mode_is_minimal(self) -> None:
        settings.b_interface_response_mode = "strict"
        body = _rpc_encoded_soap_envelope(self._real_send_alarm_xml(2))
        response = self.client.post("/services/SCService", content=body, headers={"Content-Type": "text/xml"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("SEND_ALARM_ACK", response.text)
        self.assertIn("&lt;Result&gt;1&lt;/Result&gt;", response.text)
        self.assertNotIn("&lt;AlarmCount&gt;", response.text)
        self.assertNotIn("&lt;FsuId&gt;", response.text)
        self.assertNotIn("&lt;FsuCode&gt;", response.text)

    def test_send_alarm_ack_compat_mode_keeps_alarm_count(self) -> None:
        settings.b_interface_response_mode = "compat"
        body = _rpc_encoded_soap_envelope(self._real_send_alarm_xml(2))
        response = self.client.post("/services/SCService", content=body, headers={"Content-Type": "text/xml"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("&lt;AlarmCount&gt;2&lt;/AlarmCount&gt;", response.text)
        self.assertIn("&lt;Result&gt;1&lt;/Result&gt;", response.text)

    def test_malformed_soap_returns_fault(self) -> None:
        response = self.client.post("/services/SCService", content="<soapenv:Envelope>", headers={"Content-Type": "text/xml"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("Fault", response.text)

    def test_unknown_pk_type_returns_supported_error_response(self) -> None:
        body = _soap_envelope(
            "<Request><PK_Type><Name>NOT_IMPLEMENTED</Name><Code>999</Code></PK_Type><Info><FsuId>51051243812345</FsuId></Info></Request>"
        )
        response = self.client.post("/services/SCService", content=body, headers={"Content-Type": "text/xml"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("unsupported_in_prototype", response.text)
        self.assertIn("ERROR_ACK", response.text)

    def test_logs_redact_password(self) -> None:
        body = _soap_envelope(self._real_login_xml())
        response = self.client.post("/services/SCService", content=body, headers={"Content-Type": "text/xml"})
        self.assertEqual(response.status_code, 200)
        text = self._log_text()
        self.assertIn("***", text)
        self.assertNotIn("abc123", text)
        self.assertIn('"alarm_count":0', text)

    def test_real_login_parses_pas_cword_and_devices(self) -> None:
        parsed = parse_b_interface_xml(self._real_login_xml())
        self.assertEqual(parsed.message_name, "LOGIN")
        self.assertEqual(parsed.password, "abc123")
        self.assertEqual(parsed.fsu_ip, "192.168.100.100")
        self.assertEqual(parsed.mac_id, "00:09:F5:FD:85:85")
        self.assertEqual(parsed.fsu_vendor, "AMS")
        self.assertEqual(parsed.fsu_type, "FSU")
        self.assertEqual(parsed.fsu_class, "INTSTAN")
        self.assertEqual(parsed.version, "21.1.HQ.FSU.WD.AA44.R")
        self.assertEqual(parsed.dict_version, "1")
        self.assertEqual(len(parsed.devices), 5)
        self.assertEqual(parsed.devices[0].id, "51051241820004")
        self.assertIn("<PaSCword>***</PaSCword>", parsed.sanitized_xml)

    def test_real_send_alarm_single_entry(self) -> None:
        body = _rpc_encoded_soap_envelope(self._real_send_alarm_xml(1))
        response = self.client.post("/services/SCService", content=body, headers={"Content-Type": "text/xml"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("&lt;AlarmCount&gt;1&lt;/AlarmCount&gt;", response.text)
        text = self._log_text()
        self.assertIn('"message_name":"SEND_ALARM"', text)
        self.assertIn('"fsu_id":"51051243812345"', text)
        self.assertIn('"fsu_code":"51051243812345"', text)
        self.assertIn('"alarm_count":1', text)

    def test_real_send_alarm_two_entries(self) -> None:
        body = _rpc_encoded_soap_envelope(self._real_send_alarm_xml(2))
        response = self.client.post("/services/SCService", content=body, headers={"Content-Type": "text/xml"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("&lt;AlarmCount&gt;2&lt;/AlarmCount&gt;", response.text)
        self.assertIn('"alarm_count":2', self._log_text())

    def test_real_send_alarm_three_entries(self) -> None:
        body = _rpc_encoded_soap_envelope(self._real_send_alarm_xml(3))
        response = self.client.post("/services/SCService", content=body, headers={"Content-Type": "text/xml"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("&lt;AlarmCount&gt;3&lt;/AlarmCount&gt;", response.text)
        self.assertIn('"alarm_count":3', self._log_text())

    def test_send_alarm_missing_fields_does_not_return_500(self) -> None:
        settings.b_interface_response_mode = "compat"
        body = _rpc_encoded_soap_envelope(self._real_send_alarm_missing_fields_xml())
        response = self.client.post("/services/SCService", content=body, headers={"Content-Type": "text/xml"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("SEND_ALARM_ACK", response.text)
        self.assertIn("&lt;AlarmCount&gt;2&lt;/AlarmCount&gt;", response.text)

    def test_set_fsureboot_default_policy_is_blocked(self) -> None:
        parsed = parse_b_interface_xml(self._set_fsureboot_xml())
        result = handle_sc_to_fsu_control_command(parsed)
        self.assertTrue(result.parse_ok)
        self.assertEqual(result.command, "SET_FSUREBOOT")
        self.assertEqual(result.direction, "SC_TO_FSU")
        self.assertFalse(result.allowed)
        self.assertTrue(result.blocked)
        self.assertTrue(result.dry_run)
        self.assertFalse(result.executed)
        self.assertIn("disabled", result.reason)

    def test_set_fsureboot_authorized_policy_is_dry_run_only(self) -> None:
        parsed = parse_b_interface_xml(self._set_fsureboot_xml())
        result = handle_sc_to_fsu_control_command(
            parsed,
            BInterfaceCommandPolicy(
                allow_auto_upgrade=False,
                allow_fsu_reboot=True,
                allow_real_device_control=True,
                dry_run_only=True,
            ),
        )
        self.assertEqual(result.command, "SET_FSUREBOOT")
        self.assertTrue(result.allowed)
        self.assertFalse(result.blocked)
        self.assertTrue(result.dry_run)
        self.assertFalse(result.executed)
        self.assertEqual(result.reason, "accepted_dry_run")

    def test_auto_upgrade_default_policy_is_blocked(self) -> None:
        parsed = parse_b_interface_xml(self._auto_upgrade_xml())
        result = handle_sc_to_fsu_control_command(parsed)
        self.assertEqual(result.command, "AUTO_UPGRADE")
        self.assertFalse(result.allowed)
        self.assertTrue(result.blocked)
        self.assertTrue(result.dry_run)
        self.assertFalse(result.executed)
        self.assertIn("disabled", result.reason)
        self.assertEqual(result.params["ftp_password"], "***")

    def test_auto_upgrade_authorized_policy_is_dry_run_only(self) -> None:
        parsed = parse_b_interface_xml(self._auto_upgrade_xml())
        result = handle_sc_to_fsu_control_command(
            parsed,
            BInterfaceCommandPolicy(
                allow_auto_upgrade=True,
                allow_fsu_reboot=False,
                allow_real_device_control=True,
                dry_run_only=True,
            ),
        )
        self.assertEqual(result.command, "AUTO_UPGRADE")
        self.assertTrue(result.allowed)
        self.assertFalse(result.blocked)
        self.assertTrue(result.dry_run)
        self.assertFalse(result.executed)
        self.assertEqual(result.reason, "accepted_dry_run")

    def test_control_command_invalid_xml_returns_parse_error(self) -> None:
        result = handle_sc_to_fsu_control_xml("<Request><PK_Type>", None)
        self.assertFalse(result.parse_ok)
        self.assertTrue(result.blocked)
        self.assertFalse(result.executed)
        self.assertTrue(result.error_message)

    def test_unknown_control_command_is_blocked(self) -> None:
        parsed = parse_b_interface_xml(
            "<Request><PK_Type><Name>SET_SOMETHING</Name><Code>1901</Code></PK_Type><Info><FsuId>51051243812345</FsuId></Info></Request>"
        )
        result = handle_sc_to_fsu_control_command(parsed)
        self.assertEqual(result.command, "UNKNOWN_CONTROL_COMMAND")
        self.assertTrue(result.blocked)
        self.assertFalse(result.executed)

    def test_control_command_soap_requests_are_audited_and_redacted(self) -> None:
        response = self.client.post("/services/SCService", content=_rpc_encoded_soap_envelope(self._auto_upgrade_xml()), headers={"Content-Type": "text/xml"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("AUTO_UPGRADE_ACK", response.text)
        logs = self.client.get("/api/b-interface/logs?command_name=AUTO_UPGRADE&direction=SC_TO_FSU&blocked=true")
        self.assertEqual(logs.status_code, 200)
        rows = logs.json()
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["command_name"], "AUTO_UPGRADE")
        self.assertEqual(row["direction"], "SC_TO_FSU")
        self.assertFalse(row["policy_allowed"])
        self.assertTrue(row["blocked"])
        self.assertTrue(row["dry_run"])
        self.assertFalse(row["executed"])
        self.assertNotIn("secret123", row["raw_soap_request_sanitized"])
        self.assertNotIn("secret123", row["response_xml"])

    def test_control_command_has_no_real_side_effects(self) -> None:
        with patch.object(socket.socket, "sendto") as mocked_sendto, patch.object(subprocess, "run") as mocked_run, patch.object(os, "system") as mocked_system:
            response = self.client.post("/services/SCService", content=_rpc_encoded_soap_envelope(self._set_fsureboot_xml()), headers={"Content-Type": "text/xml"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("SET_FSUREBOOT_ACK", response.text)
        mocked_sendto.assert_not_called()
        mocked_run.assert_not_called()
        mocked_system.assert_not_called()


if __name__ == "__main__":
    unittest.main()
