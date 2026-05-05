# B接口 P1 验收报告

日期：2026-05-05

结论：`passed`

## 验收范围

- `[BIF-P1-001]` SC 主动调用 `FSUService` 客户端
- `[BIF-P1-002]` `GET_DATA` 实时数据闭环
- `[BIF-P1-003]` B接口只读查看 API / 页面增强

## 基础回归

执行：

```powershell
python -m compileall backend\app
```

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_b_interface_soap -v
```

结果：

- `compileall` 通过
- `unittest` 通过，`38/38 OK`
- P0 相关回归未退化

## 完整应用启动

使用以下 SQLite 开发配置启动完整 `app.main:app`：

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

结果：

- 完整应用可启动
- P0 回归接口可用

## P0 回归结果

以下接口通过：

- `GET /services/SCService?wsdl`
- `GET /api/b-interface/fsus`
- `GET /api/b-interface/latest-login`
- `GET /api/b-interface/alarms/current`
- `GET /api/b-interface/alarms/history`

验证摘要：

- `WSDL` 含 `SCServiceSoapBinding`
- `fsus` 返回 `51051243812345`
- `latest-login` 返回 `FSUVendor=AMS`
- `alarms/current` 返回 `active`
- `alarms/history` 返回 `end_only`

## P1 dry_run 结果

验证接口：

- `POST /api/b-interface/fsus/{fsu_id}/actions/get-data?dry_run=true`
- `POST /api/b-interface/fsus/{fsu_id}/actions/time-check?dry_run=true`
- `POST /api/b-interface/fsus/{fsu_id}/actions/get-fsuinfo?dry_run=true`
- `POST /api/b-interface/fsus/{fsu_id}/actions/get-logininfo?dry_run=true`

结果：

1. `dry_run=true` 未发生真实网络请求。
   验证方式：
   本地 mock `FSUService` 请求计数在四个 `dry_run` 调用后仍为 `0`。
2. 返回结构中包含：
   - `endpoint`
   - `xmlData`
   - `soap_request`
3. `soap_request` 为 SOAP 1.1 `rpc/encoded`
4. `xmlData` 报文名与 `Code` 正确：
   - `GET_DATA` `401`
   - `TIME_CHECK` `1301`
   - `GET_FSUINFO` `1701`
   - `GET_LOGININFO` `1501`

## GET_DATA_ACK 解析结果

使用本地 mock `FSUService` 返回模拟 `GET_DATA_ACK 402`：

- 含两个设备
- 含三个 `TSemaphore`
- 至少两个点位字段完整

解析结果：

1. `invokeReturn` 成功解析为业务 XML
2. `Values/DeviceList/Device/TSemaphore` 成功提取
3. 实时数据成功写入数据库
4. 返回 `realtime_count=3`
5. 未知信号未丢弃，也未报错
   当前统一标记为 `mapping_status="unmapped"`

## 实时数据 API 结果

接口：

- `GET /api/b-interface/fsus/{fsu_id}/realtime`
- `GET /api/b-interface/realtime?fsu_id=51051243812345`
- `GET /api/b-interface/realtime?device_id=51051241820004`

结果：

- `fsu_id=51051243812345` 返回 `3` 条实时点位
- `device_id=51051241820004` 返回 `2` 条实时点位
- 返回字段包含：
  - `fsu_id`
  - `fsu_code`
  - `device_id`
  - `device_code`
  - `semaphore_id`
  - `semaphore_type`
  - `measured_val`
  - `setup_val`
  - `status`
  - `mapping_status`
  - `raw_xml`
  - `collected_at`

## 只读 API 结果

验证接口：

- `GET /api/b-interface/overview`
- `GET /api/b-interface/messages?limit=20`
- `GET /api/b-interface/samples`
- `GET /api/b-interface/realtime`

结果：

1. 空数据场景不返回 `500`
2. 有数据时返回结构化字段
3. `samples` 路径穿越拦截通过
   - `/api/b-interface/samples/%2E%2E%2Fsecret.xml` 返回 `400`
4. 不返回明文敏感字段

`overview` 摘要示例：

- `fsu_count=1`
- `current_alarm_count=2`
- `history_alarm_count=1`
- `realtime_count=3`
- `sample_count=2`

## 真实 FSUService 外呼结果

验证步骤：

1. 尝试访问：
   `http://192.168.100.100:8080/services/FSUService?wsdl`

结果：

- `not verified`
- 原因：当前环境无法连接到远程服务器

说明：

- 该项按验收要求不阻断 P1
- 本次只对本地 mock `FSUService` 完成了 `dry_run=false` 手动一次调用验证
- 调用成功时返回结构化结果，没有出现 `500`

## 安全确认

1. 未修改 UDP DSC/RDS 逻辑
2. 未新增针对真实设备的 UDP ACK
3. 未修改真实设备配置
4. 未执行 `SET_FSUREBOOT`
5. 未默认自动轮询真实设备
6. 日志脱敏通过

脱敏验证结果：

- `PaSCword` 明文未出现
- `PassWord` 明文未出现
- `Password` 明文未出现
- `FTPPwd` 明文未出现
- `IPSecPwd` 明文未出现

## 未通过项

- 无阻断项
- `真实 FSUService` 外呼未验证，仅记录为 `not verified`

## 需要修复项

- 无阻断修复项
- 后续优化项：
  当前实时点位统一标记为 `mapping_status="unmapped"`，尚未接入 `SignalIdMap.ini / SignalIdMap-2G.ini` 的正式映射逻辑。

## P2 建议

1. 接入真实 `SignalId` 到本地点位模型的正式映射，替换当前统一 `unmapped` 标记。
2. 增加 `GET_FSUINFO_ACK`、`GET_LOGININFO_ACK` 的结构化解析与缓存。
3. 为 `FSUService` 出站调用补更细的失败分类和审计字段，例如连接失败、超时、SOAP Fault、业务 XML 非法。
4. 在确认现场允许前，继续保持“手动触发优先”，不要默认开启自动轮询。
