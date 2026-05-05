# B接口 P0 验收报告

日期：2026-05-05

结论：`passed`

## 验收范围

- `[BIF-P0-001]` `LOGIN_ACK` 严格符合规范
- `[BIF-P0-002]` `SEND_ALARM_ACK` `strict/compat` 模式拆分
- `[BIF-P0-003]` FSU 登录状态入库/状态缓存
- `[BIF-P0-004]` `SEND_ALARM` 当前告警/历史告警入库

## 验收环境

完整应用按以下开发配置启动到 `0.0.0.0:8080`：

```powershell
cd backend
$env:DATABASE_URL='sqlite:///./b_interface_full_app.db'
$env:AUTO_CREATE_SCHEMA='true'
$env:TIMESCALEDB_AUTO_ENABLE='false'
$env:FSU_GATEWAY_ENABLED='false'
$env:B_INTERFACE_RESPONSE_MODE='compat'
$env:B_INTERFACE_AUTH_MODE='compat'
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8080
```

验收过程中分别验证了 `compat` 和 `strict` 两种 `B_INTERFACE_RESPONSE_MODE`。

## 执行命令

```powershell
python -m compileall backend\app
```

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_b_interface_soap -v
```

结果：

- `compileall` 通过
- `unittest` 通过，`35/35 OK`

## 通过项

1. `GET /services/SCService?wsdl` 返回 `200`，WSDL 含 `SCServiceSoapBinding`，SOAP 1.1 `rpc/encoded` 形态正常。
2. `POST LOGIN` 返回 `HTTP 200`，`LOGIN 101` 可解析，`LOGIN_ACK` 正常返回。
3. `POST SEND_ALARM` 单条、两条、三条 `TAlarm` 均返回 `HTTP 200` 和 `SEND_ALARM_ACK`。
4. `strict` 模式下 `LOGIN_ACK` 只包含：
   - `SCIP`
   - `RightLevel`
5. `strict` 模式下 `SEND_ALARM_ACK` 只包含：
   - `Result`
6. `compat` 模式下 `SEND_ALARM_ACK` 保留 `AlarmCount`，且 `1/2/3` 条 `TAlarm` 分别返回 `1/2/3`。
7. `GET /api/b-interface/fsus` 可返回最新 FSU 登录状态。
8. `GET /api/b-interface/latest-login` 可返回：
   - `FsuId`
   - `FsuCode`
   - `FsuIP`
   - `MacId`
   - `FSUVendor`
   - `FSUType`
   - `FSUClass`
   - `Version`
   - `DictVersion`
   - `DeviceList`
9. `GET /api/b-interface/alarms/current` 可返回当前告警。
10. `GET /api/b-interface/alarms/history` 可返回历史告警。
11. 日志脱敏通过，以下敏感字段明文未出现在 `backend/logs/b_interface/soap-invoke-YYYY-MM-DD.jsonl`：
    - `PaSCword`
    - `PassWord`
    - `Password`
    - `FTPPwd`
    - `IPSecPwd`
12. UDP DSC/RDS 监听代码未纳入本次修复范围，验收期间未对其做功能改动，也未新增面向真实设备的 UDP ACK 逻辑。

## 验收摘要

### compat 模式

- `LOGIN_ACK` 包含 `SCIP`、`RightLevel`、`FsuId`、`FsuCode`
- `SEND_ALARM_ACK` 包含 `AlarmCount`
- `FSU` 状态 API 正常
- 当前/历史告警 API 正常
- 日志脱敏正常

### strict 模式

- `LOGIN_ACK` 不含扩展字段 `FsuId/FsuCode/Result`
- `SEND_ALARM_ACK` 不含 `AlarmCount`
- `FSU` 状态 API 正常
- 当前/历史告警 API 正常
- 日志脱敏正常

## 未通过项

- 无

## 需要修复项

- 无阻断项。
- 残余观察项：
  重复收到相同 `END-only` 告警时，历史表会按接收事实保留多条记录。这不影响 P0 验收范围，但后续如果要做告警收敛或去重，需要单独定义规则。

## UDP 影响确认

- 未修改 `UDP_DSC 9000` / `UDP_RDS 7000` 监听职责。
- 未因为 P0 验收新增任何针对真实设备的 UDP ACK。
- 验收中只启用了 HTTP SOAP 路径，`FSU_GATEWAY_ENABLED=false`。

## 下一阶段 P1 建议

1. 继续按真实 FSU 样本补齐 `GET_DATA_ACK`、`GET_FSUINFO_ACK`、`GET_LOGININFO_ACK` 的结构化解析和入库。
2. 在手动 `FSUService` 调用链路上补更细的错误分类，例如连接失败、超时、空 `invokeReturn`、业务 XML 非法。
3. 为 `SEND_ALARM` 增加可选的重复事件收敛策略，但不要在未确认现场规则前默认启用。
4. 将 `GET_DATA` 的实时点位与项目现有 `TelemetryLatest/TelemetryHistory` 做映射前，先固定铁塔标准 `SignalId` 与本地 `BaseTypeId/SignalId` 的对照来源。
