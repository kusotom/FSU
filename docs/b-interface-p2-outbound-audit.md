# B接口 P2-003 出站调用审计与错误分类

## 范围

本阶段覆盖 `SC -> FSUService` 手动出站调用：

- `GET_DATA`
- `TIME_CHECK`
- `GET_FSUINFO`
- `GET_LOGININFO`

不改 `SCService` 入站主逻辑，不改 WSDL，不改 UDP DSC/RDS，不默认自动外呼真实 FSU，不执行 `SET_FSUREBOOT`。

## 出站调用流程

1. 只允许通过手动 API 触发。
2. 平台构造 SOAP 1.1 `rpc/encoded` `invoke(xmlData)`。
3. 发送到 `http://<fsu_ip>:8080/services/FSUService`。
4. 解析 SOAP Body 中的 `invokeReturn`。
5. 校验业务 ACK 是否与请求匹配。
6. 将结构化结果写入出站审计表和查询 API。

## 审计字段

每次调用统一保存：

- `call_id`
- `ok`
- `action`
- `fsu_id`
- `fsu_code`
- `endpoint`
- `dry_run`
- `request_xml_sanitized`
- `soap_request_sanitized`
- `http_status`
- `response_text_sanitized`
- `invoke_return_sanitized`
- `business_name`
- `business_code`
- `error_type`
- `error_message`
- `elapsed_ms`
- `created_at`

## error_type 定义

- `none`：调用成功，SOAP 与业务 ACK 均符合预期。
- `dry_run`：仅生成请求，不实际外呼。
- `invalid_endpoint`：endpoint 缺失或格式非法。
- `connection_failed`：TCP/HTTP 连接失败。
- `timeout`：外呼超时。
- `http_error`：HTTP 状态非 2xx。
- `soap_fault`：返回 SOAP Fault。
- `empty_response`：HTTP 200 但 Body 为空。
- `empty_invoke_return`：SOAP 中缺少或空 `invokeReturn`。
- `invalid_soap`：SOAP 不是合法 XML。
- `invalid_business_xml`：`invokeReturn` 不是合法业务 XML。
- `unexpected_business_ack`：请求与 ACK 不匹配，例如 `GET_DATA -> LOGIN_ACK`。
- `unsupported_response`：业务 XML 缺少可识别的 `PK_Type/Name`。
- `parse_error`：后续结构化解析或落库失败。
- `unknown_error`：未分类异常。

## API

手动触发：

- `POST /api/b-interface/fsus/{fsu_id}/actions/get-data`
- `POST /api/b-interface/fsus/{fsu_id}/actions/time-check`
- `POST /api/b-interface/fsus/{fsu_id}/actions/get-fsuinfo`
- `POST /api/b-interface/fsus/{fsu_id}/actions/get-logininfo`

查询：

- `GET /api/b-interface/outbound-calls?limit=50`
- `GET /api/b-interface/outbound-calls/{call_id}`

可选过滤：

- `fsu_id`
- `action`
- `error_type`

## 返回示例

```json
{
  "call_id": "0f3a3f0df2ff4c31b8c0b0f60f8e2d0d",
  "ok": false,
  "dry_run": false,
  "action": "get_data",
  "endpoint": "http://192.168.100.100:8080/services/FSUService",
  "business_name": "",
  "business_code": "",
  "error_type": "timeout",
  "error_message": "timed out",
  "elapsed_ms": 203,
  "http_status": null
}
```

```json
{
  "call_id": "f5d1c5d1d3ae4dc8ab9f45e7d9abbe81",
  "ok": true,
  "dry_run": false,
  "action": "get_fsuinfo",
  "endpoint": "http://192.168.100.100:8080/services/FSUService",
  "business_name": "GET_FSUINFO_ACK",
  "business_code": "1702",
  "error_type": "none",
  "error_message": "",
  "elapsed_ms": 48,
  "http_status": 200
}
```

## dry_run 策略

- 默认 `dry_run=true`
- `dry_run=true` 只生成 `xmlData` 和 SOAP 请求，不触发真实网络连接
- `dry_run` 同样写审计记录，便于现场确认请求内容

## 脱敏策略

以下字段在请求、响应、审计中均不保留明文：

- `PaSCword`
- `PaSCWord`
- `PassWord`
- `Password`
- `FTPPwd`
- `IPSecPwd`
- `IPSecUser`
- `IPSecIP`

## 排查示例

连接失败：

- `error_type=connection_failed`
- 先确认 FSU IP、路由、端口 `8080`、本机到 FSU 的网络可达性

SOAP Fault：

- `error_type=soap_fault`
- 检查 FSUService 是否接受当前 namespace、SOAP 编码方式、业务报文名

invokeReturn 为空：

- `error_type=empty_invoke_return`
- 检查 FSU 是否只返回空 SOAP 壳，或返回格式与当前解析规则不一致

ACK 不匹配：

- `error_type=unexpected_business_ack`
- 例如 `GET_DATA` 收到 `LOGIN_ACK`
- 优先检查 FSU 固件差异、请求体业务 XML 内容和目标服务地址

## 安全说明

- 默认不自动外呼真实 FSU
- 不修改真实设备配置
- 不执行真实重启
- 不修改 UDP DSC/RDS
