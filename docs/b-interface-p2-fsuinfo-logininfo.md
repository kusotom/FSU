# B接口 P2-002 FSUINFO / LOGININFO 结构化解析

## GET_FSUINFO_ACK 解析字段

当前解析并缓存：

- `fsu_id`
- `fsu_code`
- `cpu_usage`
- `mem_usage`
- `result`
- `raw_xml_sanitized`
- `collected_at`

## GET_LOGININFO_ACK 解析字段

当前解析并缓存：

- `fsu_id`
- `fsu_code`
- `sc_ip`
- `fsu_ip`
- `username`
- `ipsec_ip`
- `ipsec_user`
- `ftp_user`
- `device_list`
- `result`
- `raw_xml_sanitized`
- `collected_at`

## 密码脱敏策略

以下字段不保存明文：

- `PaSCword`
- `Password`
- `PassWord`
- `FTPPwd`
- `IPSecPwd`
- `IPSecUser`
- `IPSecIP`

策略：

1. 结构化缓存中不单独保存这些密码字段
2. `raw_xml_sanitized` 中统一脱敏为 `***`

## API 示例

手动触发：

```http
POST /api/b-interface/fsus/51051243812345/actions/get-fsuinfo?dry_run=false
POST /api/b-interface/fsus/51051243812345/actions/get-logininfo?dry_run=false
```

只读查询：

```http
GET /api/b-interface/fsus/51051243812345/fsuinfo
GET /api/b-interface/fsus/51051243812345/logininfo
```

## 限制

1. 默认不自动外呼真实 FSU
2. 仍需手动触发 `GET_FSUINFO / GET_LOGININFO`
3. 字段缺失时按空值处理，不因为缺字段导致 `500`
