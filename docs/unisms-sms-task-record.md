# UniSMS 短信接入任务记录

> 任务目标：在当前 FSU 平台中接入 UniSMS，支持“后台创建账号 + 手机号验证码登录/激活 + 状态回执 + 发送排查”。

---

## 1. 背景

当前平台已经具备：
- 手机号登录基础模型
- 用户状态模型：`PENDING / ACTIVE / DISABLED / LOCKED`
- 后台创建账号
- 短信验证码登录骨架

本任务是在现有骨架上升级为企业可落地的 UniSMS 接入方案。

---

## 2. 已完成内容

### 2.1 数据模型

已新增或确认：
- `sys_user.phone_login_enabled`
- `auth_sms_code`
- `auth_sms_delivery_log`

兼容保留：
- `sms_code_log`

说明：
- `auth_sms_code` 负责验证码生命周期
- `auth_sms_delivery_log` 负责短信发送与 DLR 回执
- 旧表暂不删除，避免影响现有流程

### 2.2 后端代码骨架

已新增：
- `backend/app/integrations/unisms/client.py`
- `backend/app/integrations/unisms/error_mapping.py`
- `backend/app/services/auth_sms_service.py`
- `backend/app/services/auth_sms_login_service.py`
- `backend/app/services/unisms_webhook_service.py`
- `backend/app/api/routes/webhooks_unisms.py`

已改造：
- `backend/app/api/routes/auth_sms.py`
- `backend/app/core/config.py`
- `backend/app/models/auth_sms.py`
- `backend/app/models/user.py`
- `backend/app/api/router.py`
- `backend/app/schemas/auth_sms.py`

### 2.3 路由

当前已接入：
- `POST /api/v1/auth/sms/send-code`
- `POST /api/v1/auth/sms/send`
- `POST /api/v1/auth/sms/login`
- `POST /api/v1/webhooks/unisms/dlr`

### 2.4 配置与依赖

已补充：
- `backend/.env.example`
- `backend/.env.unisms.example`
- `backend/.env`
- `backend/requirements.txt`

当前状态：
- `unisms` 实际安装版本为 `0.0.7`
- `SMS_PROVIDER` 当前默认保持为 `mock`
- `UNISMS_ENABLED` 当前默认保持为 `false`

这样做是为了在没有正式 UniSMS 参数前，不中断现有登录流程。

### 2.5 数据库状态

已完成：
- Alembic 版本对齐到 `20260312_0009`

说明：
- 数据库物理结构此前已由应用启动时自动建表补齐
- 直接执行旧历史迁移会因为已有表而报错
- 当前采用“结构核对 + `alembic stamp`”方式对齐版本链

### 2.6 验证结果

已验证：
- 后端编译通过
- Alembic 脚本编译通过
- 后端服务重启成功
- `/health` 正常
- `/auth/sms/send-code` 正常响应
- `/webhooks/unisms/dlr` 本地签名校验通过
- `auth_sms_delivery_log` 已成功写入模拟回执数据

当前数据库验证结果：
- `auth_sms_delivery_log` 已有一条 `provider=unisms`、`dlr_status=delivered` 的模拟回执记录
- `auth_sms_code` 当前尚未产生真实 UniSMS 发送记录

原因：
- 当前环境尚未切换到 UniSMS 实发模式

---

## 3. 仍待完成

1. 配置真实 UniSMS 参数
2. 切换 `SMS_PROVIDER=unisms`
3. 切换 `UNISMS_ENABLED=true`
4. 使用真实模板短信执行发码验证
5. 验证 UniSMS 实际回执是否与本地字段映射一致
6. 根据真实 SDK 返回结构微调 `client.py`

---

## 4. 切换到 UniSMS 实发前需要准备的参数

需要提供：
- `UNISMS_ACCESS_KEY_ID`
- `UNISMS_ACCESS_KEY_SECRET`
- `UNISMS_SMS_SIGNATURE`
- `UNISMS_LOGIN_TEMPLATE_ID`
- `UNISMS_DLR_SECRET`

并修改：
- `SMS_PROVIDER=unisms`
- `UNISMS_ENABLED=true`

---

## 5. 风险与注意事项

### 5.1 SDK 版本风险

当前安装的 `unisms` 为 `0.0.7`，实际 SDK 返回结构可能和文档示例存在细微差异。

处理方式：
- 已将 SDK 适配隔离在 `backend/app/integrations/unisms/client.py`
- 如后续字段名不同，只需调整该文件

### 5.2 回执签名风险

当前本地 webhook 已通过签名验证，但实际 UniSMS 回执字段顺序、时间格式仍需用正式环境再确认一次。

### 5.3 兼容性策略

当前保留了 mock/旧链路回退：
- 未配置 UniSMS 时，现有手机号登录不受影响
- 配置完成后再切换到 UniSMS

---

## 6. 下一步建议

建议按以下顺序推进：
1. 提供正式 UniSMS 参数
2. 参考 `backend/.env.unisms.example` 切换 `.env`
3. 重启后端
4. 调用 `/api/v1/auth/sms/send-code`
5. 检查 `auth_sms_code` 和 `auth_sms_delivery_log`
6. 用真实回执验证 `/api/v1/webhooks/unisms/dlr`
7. 最后补联调文档和运维手册

---

## 7. 相关文件

- `backend/app/integrations/unisms/client.py`
- `backend/app/integrations/unisms/error_mapping.py`
- `backend/app/services/auth_sms_service.py`
- `backend/app/services/auth_sms_login_service.py`
- `backend/app/services/unisms_webhook_service.py`
- `backend/app/api/routes/auth_sms.py`
- `backend/app/api/routes/webhooks_unisms.py`
- `backend/app/models/auth_sms.py`
- `backend/alembic/versions/20260312_0009_unisms_sms.py`
- `backend/.env`
- `backend/.env.example`
- `backend/.env.unisms.example`
