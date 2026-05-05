# B接口 P2-004 GET_HISDATA 历史数据能力

## 能力说明

平台支持手动向 `FSUService` 发起 `GET_HISDATA`，并解析 `GET_HISDATA_ACK`，将历史点位保存到本地数据库后通过只读 API 查询。

当前实现不修改 WSDL，不改 `SCService` 入站主逻辑，不改 UDP DSC/RDS，不自动外呼真实 FSU。

## 请求参数

手动触发接口：

- `POST /api/b-interface/fsus/{fsu_id}/actions/get-hisdata`

请求参数：

- `dry_run`
- `start_time`
- `end_time`
- `device_id`
- `device_code`
- `device_list`
- `all_devices`
- `max_records`

请求业务 XML 使用兼容结构：

```xml
<Request>
  <PK_Type>
    <Name>GET_HISDATA</Name>
    <Code>601</Code>
  </PK_Type>
  <Info>
    <FsuId>51051243812345</FsuId>
    <FsuCode>51051243812345</FsuCode>
    <StartTime>2026-05-05 12:00:00</StartTime>
    <EndTime>2026-05-05 13:00:00</EndTime>
    <DeviceList>
      <Device Id="51051241830004" Code="51051241830004">51051241830004</Device>
    </DeviceList>
  </Info>
</Request>
```

## 时间范围限制

- 默认 `start_time = end_time - 1 hour`
- 默认 `end_time = now`
- `start_time` 必须早于 `end_time`
- 单次默认最大跨度 `24` 小时
- 超过范围直接返回结构化错误，不真实外呼

兼容输入格式：

- `yyyy-MM-dd HH:mm:ss`
- ISO8601，例如 `2026-05-05T13:00:00`

## dry_run 策略

- 默认 `dry_run=true`
- `dry_run=true` 不发生真实网络请求
- 仍返回：
  - `endpoint`
  - `xmlData`
  - `soap_request`
  - `time_range`
  - `device_list`
- 如 P2-003 已启用，`dry_run` 同样写出站审计

## GET_HISDATA_ACK 解析

兼容以下结构：

- `Values/DeviceList/Device/TSemaphore`
- `Values/TSemaphoreList/TSemaphore`
- `TSemaphore` 属性形式
- `TSemaphore` 子节点形式

兼容时间字段：

- `Time`
- `SampleTime`
- `CollectTime`
- `MeasuredTime`
- `RecordTime`

## 历史数据模型

保存字段包括：

- `fsu_id`
- `fsu_code`
- `device_id`
- `device_code`
- `device_type`
- `semaphore_id`
- `semaphore_type`
- `measured_val`
- `setup_val`
- `status`
- `sample_time`
- `mapping_status`
- `standard_signal_id`
- `mapped_ids`
- `base_type_id`
- `local_signal_id`
- `signal_name`
- `unit`
- `signal_category`
- `signal_type`
- `channel_no`
- `signal_meanings`
- `raw_fragment`
- `source_call_id`
- `collected_at`
- `created_at`

当前用 `fsu_id + device_id + semaphore_id + sample_time` 做去重，避免 mock 或重复导入无限重复。

## 查询 API 示例

- `GET /api/b-interface/fsus/51051243812345/history`
- `GET /api/b-interface/history?fsu_id=51051243812345&device_id=51051241830004`
- `GET /api/b-interface/history?mapping_status=mapped&limit=100`

返回示例：

```json
{
  "fsu_id": "51051243812345",
  "device_id": "51051241830004",
  "semaphore_id": "418101001",
  "signal_name": "I2C温度",
  "measured_val": "26.5",
  "unit": "℃",
  "status": "OK",
  "sample_time": "2026-05-05T13:01:00+00:00",
  "mapping_status": "mapped",
  "source_call_id": "0f3a3f0df2ff4c31b8c0b0f60f8e2d0d"
}
```

## SignalIdMap 复用

历史点位解析后复用 P2-001 的映射链路：

- `init_list.ini`
- `SignalIdMap.ini / SignalIdMap-2G.ini`
- `MonitorUnits XML`

已验证示例：

- `418101001 -> I2C温度`
- `418102001 -> I2C湿度`
- 未知点位保留并标记 `unmapped`

## 限制

- 不默认自动外呼真实 FSU
- 单次查询默认最多 `24` 小时
- 单次解析默认最多 `5000` 条
- `max_records` 上限 `20000`
- 真实 `FSUService` 未验证时，使用 mock 响应做验收
