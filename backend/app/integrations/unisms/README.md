# UniSMS 集成说明

本目录只负责 UniSMS 供应商适配，不承载账号状态、权限判定、验证码状态机等平台业务逻辑。

设计原则：
- 业务逻辑放在 `services/`
- 供应商调用放在 `integrations/unisms/`
- 便于后续替换为腾讯云、阿里云等其他短信服务商

---

## 目录说明

- `client.py`
  - UniSMS SDK 封装
  - 负责模板短信发送
  - 对外暴露统一结果对象与异常
- `error_mapping.py`
  - UniSMS 错误码到平台内部错误分类的映射

---

## 当前接入范围

当前仅覆盖：
- 登录验证码模板短信发送
- UniSMS 状态回执 DLR 所需的错误分类支持

当前不负责：
- 用户是否允许登录
- 手机号是否存在于系统中
- 验证码生成与校验
- 账号激活与锁定
- 租户隔离

这些逻辑在以下服务中实现：
- `backend/app/services/auth_sms_service.py`
- `backend/app/services/auth_sms_login_service.py`
- `backend/app/services/unisms_webhook_service.py`

---

## 当前使用方式

发送登录验证码：

```python
from app.integrations.unisms.client import UniSmsClient

client = UniSmsClient()
result = client.send_login_code(
    to_e164="+8613800138000",
    code="123456",
)
```

返回对象：
- `UniSmsSendResult`
  - `code`
  - `message`
  - `raw`
  - `messages`

其中 `messages` 列表中的每一项为：
- `provider_message_id`
- `to`
- `status`
- `upstream`
- `region_code`
- `country_code`
- `message_count`
- `price`

---

## 配置项

依赖以下配置：
- `UNISMS_ENABLED`
- `UNISMS_ACCESS_KEY_ID`
- `UNISMS_ACCESS_KEY_SECRET`
- `UNISMS_HMAC_ENABLED`
- `UNISMS_SMS_SIGNATURE`
- `UNISMS_LOGIN_TEMPLATE_ID`
- `UNISMS_DLR_SECRET`

相关定义见：
- `backend/app/core/config.py`
- `backend/.env`
- `backend/.env.example`
- `backend/.env.unisms.example`

---

## 模板短信约束

当前约定只使用模板短信，不使用纯文本短信。

发送参数固定为：
- `signature`
- `templateId`
- `templateData`

登录验证码模板默认参数：
- `code`
- `ttl`

如果后续 UniSMS 实际模板变量名称不同，只需要调整 `client.py` 中的 `templateData` 组装逻辑。

---

## 错误处理

`client.py` 对外统一抛出：
- `UniSmsClientError`

字段：
- `code`
- `message`
- `raw`

业务层不应直接处理 SDK 原始异常，而应只依赖 `UniSmsClientError`。

内部错误分类映射见：
- `error_mapping.py`

---

## 注意事项

### 1. 当前 SDK 版本

当前实际安装版本为：
- `unisms==0.0.7`

因此：
- 文档示例中的 SDK 返回对象可能和实际存在差异
- 如 SDK 字段不一致，只允许在本目录调整适配
- 不要把 SDK 细节泄漏到业务服务层

### 2. 不要在这里做状态机

以下逻辑不要写在 `integrations/unisms/`：
- `PENDING -> ACTIVE`
- 验证码过期
- 错误次数锁定
- 用户不存在统一响应

这些属于平台认证逻辑，不属于供应商适配层。

### 3. DLR 验签不在这里做

UniSMS 回执签名验证当前在：
- `backend/app/services/unisms_webhook_service.py`

原因：
- 它属于“平台接收第三方回调”的应用层逻辑
- 不只是 SDK 调用

---

## 后续待办

1. 用正式 UniSMS 参数验证真实发送
2. 对照真实返回结构微调 `client.py`
3. 补充单元测试或最小联调脚本
4. 根据正式回执字段确认 `submit_status / dlr_status` 的最终枚举
