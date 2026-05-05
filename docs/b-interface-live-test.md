# B Interface Live Test

## Purpose

This runbook is for real FSU SOAP observation and sample archiving. The goal is to record actual `invoke(xmlData) -> invokeReturn` traffic and stop guessing message structure once a real device connects.

## Start command

```powershell
cd backend
$env:DATABASE_URL='sqlite:///./b_interface_full_app.db'
$env:AUTO_CREATE_SCHEMA='true'
$env:TIMESCALEDB_AUTO_ENABLE='false'
$env:FSU_GATEWAY_ENABLED='false'
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8080
```

Notes:

- This keeps the test environment local to SQLite.
- `FSU_GATEWAY_ENABLED='false'` avoids enabling the separate UDP gateway path during SOAP-only live testing.
- This procedure does not change any real device configuration.

## Quick validation

```powershell
curl http://127.0.0.1:8080/services/SCService?wsdl
```

Expected result:

- HTTP `200`
- returned WSDL includes `SCServiceSoapBinding`
- returned WSDL includes `style="rpc"` and `use="encoded"`

## Wireshark filter

```text
ip.addr == 192.168.100.100 && tcp.port == 8080
```

Use this while the FSU is pointed at the platform host and the SOAP service is listening on `8080`.

## Runtime logs

SOAP invoke logs are written to:

- `backend/logs/b_interface/soap-invoke-YYYY-MM-DD.jsonl`

Each record contains:

- `timestamp`
- `remote_addr`
- `service_name`
- `soap_action`
- `message_name`
- `message_code`
- `fsu_id`
- `fsu_code`
- `raw_soap_request_sanitized`
- `extracted_xmlData_sanitized`
- `response_xml`
- `parse_ok`
- `error`

Sensitive values are always redacted before disk write:

- `PassWord`
- `Password`
- `pwd`
- `FTPPwd`
- `IPSecPwd`

## Message sample archive

Sanitized business XML samples are stored under:

- `backend/logs/b_interface/samples/`

Current naming convention:

- `backend/logs/b_interface/samples/YYYY-MM-DD-LOGIN.xml`
- `backend/logs/b_interface/samples/YYYY-MM-DD-GET_DATA.xml`
- `backend/logs/b_interface/samples/YYYY-MM-DD-SEND_ALARM.xml`

If multiple requests of the same type arrive on the same day, the latest sanitized sample currently replaces the earlier file for that message type. This is intentional for quick diff and triage during first-pass live testing.

## Live test steps

1. Start the full backend on `0.0.0.0:8080` with the command above.
2. Verify `GET /services/SCService?wsdl` locally.
3. Start Wireshark with the filter `ip.addr == 192.168.100.100 && tcp.port == 8080`.
4. Let the real FSU initiate SOAP traffic.
5. Check `backend/logs/b_interface/soap-invoke-YYYY-MM-DD.jsonl` for the first request.
6. Check `backend/logs/b_interface/samples/` for sanitized `xmlData` snapshots grouped by message type.
7. Use the captured real samples to refine `GET_DATA_ACK`, `GET_FSUINFO_ACK`, and `SEND_ALARM` structures incrementally.

## Constraints

- Do not modify UDP DSC/RDS listeners for this SOAP live-test phase.
- Do not send any UDP ACK.
- Do not modify real device configuration from the server side.
- Do not store plaintext passwords in logs or sample files.
