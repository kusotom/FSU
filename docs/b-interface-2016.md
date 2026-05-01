# B 接口协议 2016 接入说明（维谛/Vertiv）

平台只保留 B 接口协议 2016 作为 FSU 接入协议。当前实现按维谛/Vertiv eStoneII、FSU-2808IM 这类设备的实际接入方式做兼容：设备通过 gSOAP `SCService` 向平台注册、上报告警；平台可按需向设备侧 `FSUService` 主动发起 `GET_DATA` 拉取实时数据。

## 设备侧配置

把 FSU 的上级 `SC` 服务地址指向平台：

```text
http://<平台IP>:8000/services/SCService
```

如果设备页面只提供拆分字段：

```text
SC IP: <平台IP>
SC Port: 8000
SC Path: /services/SCService
```

维谛设备常见行为：

- `LOGIN(Code=101)` 由设备主动发到平台 `/services/SCService`。
- 登录包里通常包含 `FsuId`、`FsuCode`、`FsuIP`、`FSUVendor=AMS`、`FSUManufactor=AMS`、`Version`、`DeviceList`。
- 平台返回 `LOGIN_ACK(Code=102)`，`RightLevel=2`，并返回当前平台 `SCIP`。
- 设备侧本地业务服务通常是 `http://<FsuIP>:8080/services/FSUService`。
- 平台主动采集实时数据时，向设备 `FSUService` 发送 `GET_DATA(Code=401)`。

## 平台入口

| 用途 | 方法 | 路径 |
| --- | --- | --- |
| 真实 FSU 上报入口 | `POST` | `/services/SCService` |
| 兼容入口 | `POST` | `/services/FSUService` |
| 调试直接投递 XML | `POST` | `/api/v1/b-interface/2016/invoke` |
| 通用主动轮询 | `POST` | `/api/v1/b-interface/2016/poll` |
| 维谛按设备编码轮询 | `POST` | `/api/v1/b-interface/2016/vertiv/{fsu_code}/poll` |
| 健康检查 | `GET` | `/api/v1/b-interface/2016/health` |
| WSDL 占位 | `GET` | `/services/SCService?wsdl` |

`/services/*` 同时接受裸 XML、gSOAP `invoke/xmlData` 包，以及 SOAP `return` 回包。平台响应会按请求形态返回裸 XML 或 SOAP `invokeResponse/return`。

## 已支持报文

| 报文 | 常见 Code | 平台行为 |
| --- | --- | --- |
| `LOGIN` | `101` | 注册或更新 FSU、站点、设备清单，返回维谛兼容 `LOGIN_ACK` |
| `LOGOUT` | `103` | 标记 FSU 离线，返回 `LOGOUT_ACK` |
| `SEND_ALARM` | `501` | 写入或恢复告警，返回 `SEND_ALARM_ACK` |
| `GET_FSUINFO_ACK` | `102/200` | 更新 FSU 信息和设备清单 |
| `GET_DATA_ACK` | `402/200` | 解析 `TSemaphore/Semaphore/Signal/TSignal`，写入实时值和历史值 |
| `GET_HISDATA_ACK` | `404/200` | 解析遥测点并写入历史/实时遥测 |
| `TIME_CHECK` | `1301` | 返回平台时间 `TIME_CHECK_ACK` |

其他已知配置类报文会返回通用成功 ACK，避免设备反复重试；字段级处理后续按真实抓包继续补。

## 数据映射

- `FsuCode/FsuId` 作为平台站点编码和 B 接口设备编码。
- `FsuIP` 会保存到平台 B 设备台账，供维谛专用轮询接口自动生成 `FSUService` 地址。
- `LOGIN/Info/DeviceList/Device[@Code]` 会在平台内创建设备。
- `GET_DATA_ACK/Info/DeviceList/Device/TSemaphore` 会创建监控点并写入遥测。
- 遥测点 ID 兼容 `Id/ID/Code/SignalId/SemaphoreId`。
- 遥测值兼容 `MeasuredVal/SetupVal/Status/Value/Val/value`。
- 遥测点名称兼容 `Name/SignalName`。
- 遥测单位兼容 `Unit/UnitName`。
- `SEND_ALARM/TAlarm` 会创建或恢复平台告警。
- `AlarmFlag` 为 `0`、`2`、`recover`、`recovered`、`clear`、`cleared`、`end`、`normal` 时按恢复处理，其余按活动告警处理。

## 维谛主动 GET_DATA

设备完成 `LOGIN` 后，平台已保存该 FSU 的 `FsuIP`。可以直接按设备编码主动拉实时数据：

```powershell
Invoke-RestMethod `
  -Method POST `
  -Uri http://127.0.0.1:8000/api/v1/b-interface/2016/vertiv/51050243802162/poll `
  -ContentType 'application/json' `
  -Body '{
    "command": "GET_DATA",
    "port": 8080,
    "path": "/services/FSUService",
    "soap": true,
    "timeout_seconds": 10
  }'
```

该接口会自动请求：

```text
http://<FsuIP>:8080/services/FSUService
```

默认发送的业务 XML 为：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<Request>
    <PK_Type>
        <Name>GET_DATA</Name>
        <Code>401</Code>
    </PK_Type>
    <Info>
        <FsuId>51050243802162</FsuId>
        <FsuCode>51050243802162</FsuCode>
    </Info>
</Request>
```

如果设备返回 `GET_DATA_ACK` 或 `GET_HISDATA_ACK`，平台会立即解析并写库，接口返回里会包含 `ingested_metrics`。

## 通用主动轮询

如果现场需要手工指定设备服务地址：

```powershell
Invoke-RestMethod `
  -Method POST `
  -Uri http://127.0.0.1:8000/api/v1/b-interface/2016/poll `
  -ContentType 'application/json' `
  -Body '{
    "target_url": "http://10.10.10.2:8080/services/FSUService",
    "command": "GET_DATA",
    "code": "401",
    "fsu_code": "51050243802162",
    "soap": true,
    "timeout_seconds": 10
  }'
```

如果设备要求特殊 XML 模板，可以用 `raw_xml` 覆盖平台生成的请求。

## 本地快速验证

启动后端：

```powershell
cd C:\Users\测试\Desktop\动环\fsu-platform
powershell -ExecutionPolicy Bypass -File .\scripts\start-backend.ps1
```

检查 2016 入口：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/v1/b-interface/2016/health
Invoke-WebRequest http://127.0.0.1:8000/services/SCService?wsdl
```

投递维谛登录样例：

```powershell
$xml = @'
<?xml version="1.0" encoding="UTF-8"?>
<Request>
  <PK_Type><Name>LOGIN</Name><Code>101</Code></PK_Type>
  <Info>
    <FsuId>51050243802162</FsuId>
    <FsuCode>51050243802162</FsuCode>
    <FsuIP>10.10.10.2</FsuIP>
    <FSUVendor>AMS</FSUVendor>
    <FSUManufactor>AMS</FSUManufactor>
    <Version>24.1.HQ.FSU.WD.AA48.R</Version>
    <DeviceList>
      <Device Id="51050241832131" Code="51050241832131"/>
    </DeviceList>
  </Info>
</Request>
'@
Invoke-WebRequest `
  -Method POST `
  -Uri http://127.0.0.1:8000/services/SCService `
  -ContentType 'text/xml; charset=utf-8' `
  -Body $xml
```

正常应返回 `LOGIN_ACK`，并包含 `RightLevel=2`。

## eStoneII FSUService 现场修正（2026-04-27）

真实 eStoneII 设备的本地 WebProvider 与通用 B 接口文档有差异：

- 本地入口使用 `http://<FsuIP>:8080/` 根路径，`/services/FSUService` 不稳定。
- SOAP namespace 使用 `http://FSUService.chinatowercom.com`。
- `GET_FSUINFO(Code=101)` 返回的内层包名是 `LOGIN`，不是 `GET_FSUINFO_ACK`，但可以解析出 FSU 信息和 `DeviceList`。
- `GET_DATA` 必须使用 `Code=401`。
- `GET_DATA` 必须在 `Info` 下带 `DeviceList`。只带 `FsuId/FsuCode` 会导致设备日志出现 `[ParseXmlData]ERR`，并重启本地 8080 WebService。
- `GET_DATA Code=201` 会被设备记录为错误命令。
- `Info/Values/DeviceList` 不是该固件接受的请求格式。

平台的维谛专用轮询接口已经按以上规则生成安全请求：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<Request>
    <PK_Type>
        <Name>GET_DATA</Name>
        <Code>401</Code>
    </PK_Type>
    <Info>
        <FsuId>51051243812345</FsuId>
        <FsuCode>51051243812345</FsuCode>
        <DeviceList>
            <Device Id="51051241820004" Code="51051241820004"/>
        </DeviceList>
    </Info>
</Request>
```

当前现场设备对该请求返回 `GET_DATA_ACK(Code=402, Result=1)`，但 `Values/DeviceList` 仍为空。因此 HTTP 主动轮询已经可作为兼容入口保留，真实遥测落地继续以 DS/RDS 私有 UDP 业务帧解析为主线推进。
