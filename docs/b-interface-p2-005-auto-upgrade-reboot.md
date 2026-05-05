# B接口 P2-005 自动升级与 SET_FSUREBOOT

## 范围

P2-005 只实现：

- SC -> FSU 控制命令识别
- 自动升级相关命令识别
- `SET_FSUREBOOT` 识别
- 参数解析
- 安全策略判断
- 默认禁用响应
- 授权 dry-run 响应
- JSONL 审计记录

本阶段不实现真实升级，不实现真实重启，不实现真实发包。

## SC -> FSU 控制流程

1. SOAP `invoke(xmlData)` 进入现有 B 接口服务端。
2. 业务 XML 解析出 `PK_Type/Name`。
3. 如果命中升级/重启控制命令，进入控制策略层。
4. 依据配置生成：
   - 默认 `blocked`
   - 授权但仍 `dry_run`
5. 返回兼容业务 ACK。
6. 写入审计日志。

## 当前状态

### 自动升级

- 默认禁止
- 可识别命令：
  - `AUTO_UPGRADE`
  - `SET_AUTOUPGRADE`
  - `SET_FSUUPGRADE`
  - `SET_UPGRADE`
- 即使授权，也只返回 `accepted_dry_run`

### SET_FSUREBOOT

- 默认禁止
- 即使授权，也只返回 `accepted_dry_run`
- `executed` 始终为 `false`

## 默认禁用策略

配置项：

- `B_INTERFACE_ALLOW_AUTO_UPGRADE=false`
- `B_INTERFACE_ALLOW_FSU_REBOOT=false`
- `B_INTERFACE_ALLOW_REAL_DEVICE_CONTROL=false`
- `B_INTERFACE_CONTROL_DRY_RUN_ONLY=true`

默认语义：

- `allowed=false`
- `blocked=true`
- `dry_run=true`
- `executed=false`
- `reason=disabled_by_default`

## 授权 dry-run 策略

即使显式设置：

- `B_INTERFACE_ALLOW_AUTO_UPGRADE=true`
- `B_INTERFACE_ALLOW_FSU_REBOOT=true`
- `B_INTERFACE_ALLOW_REAL_DEVICE_CONTROL=true`

当前也只返回：

- `allowed=true`
- `blocked=false`
- `dry_run=true`
- `executed=false`
- `reason=accepted_dry_run`

## 配置项说明

- `B_INTERFACE_ALLOW_AUTO_UPGRADE`
  - 仅影响升级类命令是否进入 `accepted_dry_run`
- `B_INTERFACE_ALLOW_FSU_REBOOT`
  - 仅影响 `SET_FSUREBOOT` 是否进入 `accepted_dry_run`
- `B_INTERFACE_ALLOW_REAL_DEVICE_CONTROL`
  - 未开启时，所有控制命令都保持阻断
- `B_INTERFACE_CONTROL_DRY_RUN_ONLY`
  - 当前阶段固定为安全导向；即使授权，也不允许真实执行

## 审计字段

控制命令请求会写入 `backend/logs/b_interface/soap-invoke-YYYY-MM-DD.jsonl`，包含：

- `timestamp`
- `service_name`
- `message_name`
- `message_code`
- `direction`
- `command_name`
- `fsu_id`
- `fsu_code`
- `raw_soap_request_sanitized`
- `response_xml`
- `parse_ok`
- `policy_allowed`
- `blocked`
- `dry_run`
- `executed`
- `reason`
- `correlation_id`
- `error`

## 测试覆盖

已覆盖：

- `SET_FSUREBOOT` 默认禁用
- `SET_FSUREBOOT` 授权 dry-run
- 自动升级默认禁用
- 自动升级授权 dry-run
- 非法 XML 返回 `parse_ok=false`
- 未知控制命令阻断
- 审计记录存在且已脱敏
- 无真实副作用

## 明确不做的事情

- 默认禁止真实重启
- 默认禁止真实升级
- 不下载升级包
- 不保存升级包
- 不调用升级程序
- 不执行 `reboot/shutdown/subprocess/os.system`
- 不发送 UDP/TCP/HTTP 真实设备控制请求
- 不修改 DSC/RDS 实时网关
- 不修改 one-shot ACK 实验逻辑

## 后续真实启用前置条件

- 需要独立任务放开真实执行能力
- 需要单独的人工授权和审计方案
- 需要明确升级包来源、校验、回滚、超时和故障恢复策略
- 需要真实设备联调与灰度验证
