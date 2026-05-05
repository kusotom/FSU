# B Interface SOAP/XML Integration Prototype

## Confirmed evidence summary

- Firmware contains `libgsoap++.so` symbols for `ns1:invoke`, `ns1:invokeResponse`, `xmlData`, `invokeReturn`, and the SOAP 1.1 envelope namespace `http://schemas.xmlsoap.org/soap/envelope/`.
- `ttb.so` and `SiteUnit` include `http://SCService.chinatowercom.com`, `http://FSUService.chinatowercom.com`, `http://%s:%d/services/SCService`, and message names including `LOGIN`, `GET_DATA`, `SEND_ALARM`, `TIME_CHECK`, `GET_LOGININFO`, `SET_LOGININFO`, `GET_FSUINFO`, and `SET_FSUREBOOT`.
- `init_list.ini`, `MonitorUnits*.xml`, `SignalIdMap*.ini`, and `SiteUnit_TT.ini` show that the northbound model is Tower B interface oriented and that device metadata is recoverable from local configuration files.

## Why SOAP 1.1

- The recovered gSOAP envelope namespace is SOAP 1.1 rather than SOAP 1.2.
- Original attachment-level `SCService.wsdl` and `FSUService.wsdl` have now been recovered.
- The original WSDL shape is SOAP 1.1 `rpc/encoded`, not `document/literal`.
- The confirmed callable pattern is `invoke(xmlData:string) -> invokeReturn:string`.
- The earlier `document/literal` reconstruction was only a placeholder used before the original WSDL was available.
- The runtime WSDL and SOAP response shape now follow the recovered `rpc/encoded` contract while request parsing stays tolerant enough to accept both `rpc/encoded` and the earlier `document/literal` style.

## Namespaces and endpoints

- `SCService` namespace: `http://SCService.chinatowercom.com`
- `FSUService` namespace: `http://FSUService.chinatowercom.com`
- SC service target endpoint: `http://192.168.100.123:8080/services/SCService`
- FSU service placeholder endpoint: `http://127.0.0.1:8080/services/FSUService`
- The static reconstructed WSDL files keep the attachment-style `127.0.0.1:8080` address.
- `GET /services/SCService?wsdl` and `GET /services/FSUService?wsdl` dynamically rewrite `soap:address` to the current request URL so the served WSDL reflects the active listener.

## Supported prototype messages

- `LOGIN` -> `LOGIN_ACK`
- `GET_DATA` -> `GET_DATA_ACK`
- `SEND_ALARM` -> `SEND_ALARM_ACK`
- `TIME_CHECK` -> `TIME_CHECK_ACK`
- `GET_FSUINFO` -> `GET_FSUINFO_ACK`
- `GET_LOGININFO` -> `GET_LOGININFO_ACK`
- `SET_LOGININFO` -> `SET_LOGININFO_ACK`
- `SET_FSUREBOOT` -> `SET_FSUREBOOT_ACK`

Unknown message types return a generic XML error response wrapped in SOAP, and malformed SOAP returns a SOAP fault with HTTP 400.

## Prototype constraints

- This implementation is a compatibility prototype, not a claim of full factory SC platform equivalence.
- UDP `DSC` on `9000` and UDP `RDS` on `7000` are left in place and were not removed or refactored.
- This phase does not add or change any real UDP ACK behavior.
- `SET_FSUREBOOT` is explicitly ignored. The prototype will not reboot any device.
- `SET_LOGININFO` acknowledges requests but does not persist them to device configuration.
- Plaintext passwords are not written to logs. `PassWord`, `Password`, `pwd`, `FTPPwd`, and `IPSecPwd` are redacted.

## WSDL files

- [reconstructed-SCService.wsdl](/C:/Users/测试/Desktop/动环/fsu-platform/docs/b-interface/wsdl/reconstructed-SCService.wsdl)
- [reconstructed-FSUService.wsdl](/C:/Users/测试/Desktop/动环/fsu-platform/docs/b-interface/wsdl/reconstructed-FSUService.wsdl)

## Current data sources

- `init_list.ini` is loaded from:
  - `backend/config/init_list.ini`
  - `backend/app/config/init_list.ini`
  - `backend/fixtures/fsu/init_list.ini`
  - limited recursive search under `runtime-data`, `snapshots`, and `$dest`
- If no project-local file is found, a built-in fallback is used for:
  - `SCIP=192.168.100.123`
  - `FSUID=51051243812345`
  - `FSUCode=51051243812345`
  - the 6 confirmed device records
- `MonitorUnits*.xml` is read opportunistically to fill `FSUVendor`, `FSUType`, and `FSUClass` when present.

## Startup and validation

Existing helper `backend/run_backend_server.py` still starts the app on port `8000`. To expose the SOAP prototype on `8080`, start the same FastAPI app explicitly on `8080`:

```powershell
cd backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8080
```

Example validation commands:

```powershell
curl.exe "http://127.0.0.1:8080/services/SCService?wsdl"
```

```powershell
curl.exe -X POST "http://127.0.0.1:8080/services/SCService" ^
  -H "Content-Type: text/xml" ^
  --data-binary "@login-soap.xml"
```

```powershell
curl.exe -X POST "http://127.0.0.1:8080/services/SCService" ^
  -H "Content-Type: text/xml" ^
  --data-binary "@get-data-soap.xml"
```

```powershell
curl.exe -X POST "http://127.0.0.1:8080/services/SCService" ^
  -H "Content-Type: text/xml" ^
  --data-binary "@send-alarm-soap.xml"
```

Packet capture should verify that the real FSU is calling `/services/SCService` with SOAP 1.1 `invoke(xmlData)` and that the server responds with `invokeReturn`.

The current runtime shape is expected to look like:

- `binding style="rpc"`
- `wsdlsoap:body use="encoded"`
- `encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"`
- `xmlData` and `invokeReturn` typed as `soapenc:string`

## Not completed yet

- Full factory WSDL alignment
- Full `GET_DATA_ACK` point data payloads
- Full `SEND_ALARM` masking, interval, and correlation rules from `SiteUnit_TT.ini`
- Full `SignalIdMap*.ini` mapping for standard signal IDs
- Full FTP and upgrade workflow behavior
