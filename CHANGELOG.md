# 变更记录

本文档只记录当前版本仍然有效的主要收口结果，避免把历史试验性设计继续当成现状。

## 0.22

### 铁塔 B 接口 SOAP/XML 兼容层
- 新增 `backend/app/modules/b_interface/` 模块化兼容层，接入现有 FastAPI 应用。
- 新增 `SCService` / `FSUService` SOAP 1.1 `rpc/encoded` 兼容实现，核心操作为 `invoke(xmlData) -> invokeReturn`。
- 新增动态 WSDL 返回与原始附件级 WSDL 对齐能力。

### 入站能力
- 支持 `LOGIN`、`SEND_ALARM`、`GET_DATA`、`TIME_CHECK`、`GET_FSUINFO`、`GET_LOGININFO`、`SET_LOGININFO`、`SET_FSUREBOOT` 基础兼容响应。
- `LOGIN_ACK` 与 `SEND_ALARM_ACK` 支持 `strict / compat` 模式切换。
- 新增真实 FSU 联调日志、样本归档、脱敏和只读查看 API。

### 状态与数据落库
- 新增 FSU 登录状态缓存与查询接口。
- 新增当前告警 / 历史告警入库与查询接口。
- 新增实时点位入库与查询接口。
- 新增历史点位 `GET_HISDATA / GET_HISDATA_ACK` 解析、去重落库与查询接口。

### 映射与缓存
- 接入 `init_list.ini`、`SignalIdMap.ini`、`SignalIdMap-2G.ini`、`MonitorUnits XML`。
- 实现标准 `SignalId -> BaseTypeId/Signal` 映射，支持 `mapped / unmapped / ambiguous`。
- 新增 `GET_FSUINFO_ACK` / `GET_LOGININFO_ACK` 结构化缓存。

### 出站能力
- 新增 `FSUService` 手动客户端，支持 `GET_DATA`、`GET_HISDATA`、`TIME_CHECK`、`GET_FSUINFO`、`GET_LOGININFO`。
- 所有出站调用接入统一审计、错误分类和查询接口。
- 默认 `dry_run=true`，不自动外呼真实 FSU。

### 控制命令安全框架
- 新增 `AUTO_UPGRADE`、`SET_AUTOUPGRADE`、`SET_FSUUPGRADE`、`SET_UPGRADE`、`SET_FSUREBOOT` 识别与策略判断。
- 默认禁用真实升级、真实重启、真实设备控制。
- 授权模式在当前阶段也仅允许 `accepted_dry_run`，`executed` 恒为 `false`。

### 安全边界
- 未修改 UDP DSC/RDS 实时监听主逻辑。
- 未新增真实 UDP ACK。
- 未执行真实升级、真实重启、真实设备控制。

### 文档与测试
- 新增 B 接口阶段文档、联调说明、验收报告和 WSDL 重构文件。
- `backend/tests/test_b_interface_soap.py` 扩展到完整覆盖当前 B 接口主链路。

## 0.21

### 角色与用户管理收口

- 核心角色收口为 `platform_admin / company_admin / employee`。
- 平台管理员只负责创建公司和公司管理员。
- 公司管理员只负责管理本公司员工。
- 普通员工只访问自己被授权的功能和数据。
- 用户授权主流程改为“核心角色 + 权限点 + 数据范围”。
- 岗位差异改为权限模板，不再继续扩充底层固定角色。

### 手机号账号体系

- 登录方式切换为“后台创建账号 + 手机号验证码登录/激活”。
- `sys_user` 补充手机号、激活状态、锁定状态、最近登录等字段。
- 新增短信登录接口：
  - `POST /api/v1/auth/sms/send-code`
  - `POST /api/v1/auth/sms/send`
  - `POST /api/v1/auth/sms/login`
- 首次验证码登录会把账号从 `PENDING` 自动激活为 `ACTIVE`。

### UniSMS 接入骨架

- 新增 UniSMS 供应商适配层：
  - `backend/app/integrations/unisms/client.py`
  - `backend/app/integrations/unisms/error_mapping.py`
- 新增验证码与投递日志双表：
  - `auth_sms_code`
  - `auth_sms_delivery_log`
- 新增状态回执接口：
  - `POST /api/v1/webhooks/unisms/dlr`
- 已支持回执签名校验、错误码映射、发送记录落库和失败排查。
- 当前默认仍保留 `mock` 兼容链路；未配置 UniSMS 正式参数时，不影响现有手机号登录。

### 文档

- 新增 `docs/unisms-sms-task-record.md`
- 新增 `backend/app/integrations/unisms/README.md`
- 根 `README.md` 已同步到当前角色和短信登录模型
