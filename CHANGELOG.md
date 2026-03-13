# 变更记录

本文档只记录当前版本仍然有效的主要收口结果，避免把历史试验性设计继续当成现状。

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
