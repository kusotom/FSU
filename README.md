# FSU 动环监控平台（MVP）

本项目是一个面向 FSU（动力+环境）场景的全栈监控平台，支持数据采集、实时监控、告警联动、规则治理、多租户隔离与权限控制。

当前实现重点：
- 支持站点/设备多维监控数据采集与展示。
- 支持告警生命周期（触发、确认、关闭、恢复）。
- 支持“总部模板 + 租户策略覆盖”的两层规则模型。
- 支持多租户隔离（租户内可见、可管），并保留集团侧跨租户汇总能力。

---

## 1. 技术栈

- 后端：FastAPI + SQLAlchemy + Alembic
- 前端：Vue 3 + Element Plus + Pinia + Vue Router + ECharts
- 数据库：PostgreSQL（默认）
- 时序增强：TimescaleDB 扩展（默认启用，可关闭）
- 监控链路：Prometheus + Alertmanager + Grafana（可选本地一键启动）
- 消息接入：HTTP Ingest（内置）+ MQTT Bridge（可选）+ DTU TCP Gateway（可选）

---

## 2. 系统架构与数据流

```text
采集设备/FSU
   │
   ├─ 现场推荐: DTU TCP -> scripts/dtu_ingest_gateway.py -> /api/v1/ingest/dtu
   ├─ HTTP: /api/v1/ingest/telemetry
   ├─ DTU TCP: scripts/dtu_ingest_gateway.py -> /api/v1/ingest/dtu
   └─ MQTT: fsu/telemetry/# (经 bridge 转发)
          │
          ▼
  Ingest 服务（direct/queue）
          │
          ├─ 写入 telemetry_history / telemetry_latest
          ├─ 规则评估（模板+租户策略）
          ├─ 触发/恢复告警
          └─ 推送 WebSocket 实时消息
          │
          ▼
  前端实时监控 / 告警中心 / 规则策略 / 报表
```

后端启动时会自动执行：
- 基础表结构检查（`AUTO_CREATE_SCHEMA=true` 时）。
- TimescaleDB 扩展与时序策略启用（`TIMESCALEDB_AUTO_ENABLE=true` 时，默认开启）。
- 内置角色与默认账号初始化。
- 内置角色权限与默认数据范围初始化。
- 默认规则与示例站点数据初始化。
- 关键索引检查（PostgreSQL）。

---

## 3. 目录结构

```text
fsu-platform/
  backend/                 # FastAPI 后端
    app/
      api/routes/          # 接口路由（auth/ingest/telemetry/alarms/...）
      services/            # 规则解析、权限控制、通知、WS 等服务
      models/              # ORM 模型
      schemas/             # Pydantic 入参与返回模型
    scripts/               # 压测/回归/模拟数据脚本
    sql/                   # PostgreSQL 初始化 SQL（含 authz seed）
  frontend/                # Vue 前端
    src/views/             # 页面（实时监控、告警、规则、用户管理等）
    src/stores/            # Pinia 状态（登录态、权限）
  deploy/                  # Prometheus/Alertmanager/Grafana/MQTT 配置
  scripts/                 # Windows 本地启动/检查/安装脚本
  docs/
    user-management-plan.md # 用户与租户权限规划（中文）
    unisms-sms-task-record.md # UniSMS 短信接入任务记录
```

文档文件：
- `README.md`：项目总览、部署方式、模块能力说明。
- `CHANGELOG.md`：持续记录重要功能变更与收口情况。
- `docs/unisms-sms-task-record.md`：UniSMS 接入执行记录与剩余工作。
- `docs/estoneii-private-ds-udp9000.md`：eStoneII `SiteUnit` 在 SOAP B 接口前的 DS UDP/9000 私有握手解析。
- `backend/app/integrations/unisms/README.md`：UniSMS 供应商适配层说明。
- `backend/.env.unisms.example`：UniSMS 实发模式环境变量模板。

---

## 4. 多租户隔离与权限模型（重点）

### 4.1 设计原则

当前版本采用简化模型：
- `platform_admin`：负责创建公司和公司管理员，同时保留全局只读视角，可查看所有公司的项目、站点、告警和监控数据。
- `company_admin`：只负责管理本公司的员工、权限和数据范围。
- `employee`：只访问自己被授权的功能和数据。

角色只表达管理层级，不承载复杂岗位差异。业务差异通过权限点组合实现，数据可见范围通过数据范围实现。

### 4.2 当前权限实现

当前后端访问控制已收口为“核心角色 + 权限点 + 数据范围”：
- 核心角色：`platform_admin / company_admin / employee`
- 权限点：控制页面访问和业务动作
- 数据范围：控制租户、站点、设备组等可见数据

第一批常用权限点包括：
- 页面访问：`dashboard.view`、`realtime.view`、`site.view`、`alarm.view`、`history.view`
- 告警动作：`alarm.view`、`alarm.handle`
- 站点治理：`site.view`、`site.manage`
- 规则治理：`rule.view`、`rule.manage`
- 通知治理：`notify.view`、`notify.manage`
- 报表导出：`report.export`
- 员工管理：`user.manage_company`

兼容说明：
- 历史数据里仍可能看到 `admin / hq_noc / sub_noc / operator`。
- 运行时这些旧角色会映射到新的核心角色或仅作为兼容数据保留，不再建议继续新增和分配。

### 4.3 职责边界

| 角色 | 职责边界 |
|---|---|
| `platform_admin` | 创建公司、创建公司管理员、全局只读查看所有公司的项目/站点/告警/监控数据 |
| `company_admin` | 管理本公司员工、分配员工权限模板、配置员工数据范围 |
| `employee` | 使用已授权页面和功能，访问已授权数据 |

说明：
- 平台管理员默认具备全局只读权限，便于总部视角查看所有项目和站点，但不参与公司内部日常配置维护。
- 公司管理员不能跨公司管理账号，也不能创建平台管理员。
- 普通员工无用户管理权限。

---

## 5. 快速启动（Windows，本地开发）

### 5.1 启动后端

```powershell
# 进入后端目录
cd C:\Users\Administrator\Desktop\fsu-platform\backend

# 首次复制配置
Copy-Item .env.example .env

# 安装依赖
pip install -r requirements.txt

# （可选）新库可显式执行迁移
python -m alembic upgrade head

# （可选）如果你使用 init SQL 初始化 PostgreSQL，再执行权限 seed
psql -f .\sql\init_postgres.sql
psql -f .\sql\authz_seed.sql

# 启动服务
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

健康检查：
- `http://127.0.0.1:8000/health`

升级说明：
- 全新数据库可以直接执行 `python -m alembic upgrade head`。
- 已由 `AUTO_CREATE_SCHEMA=true` 自动建表跑起来的旧环境，先不要盲目重放全部历史迁移；需要先核对实际表结构，再决定是补迁移还是使用 `alembic stamp` 对齐版本链。

### 5.2 启动前端

```powershell
cd C:\Users\Administrator\Desktop\fsu-platform\frontend
npm install
npm run dev
```

访问地址：
- `http://127.0.0.1:5173`

### 5.3 一键脚本（可选）

```powershell
# 后端
powershell -ExecutionPolicy Bypass -File .\scripts\start-backend.ps1

# 前端
powershell -ExecutionPolicy Bypass -File .\scripts\start-frontend.ps1
```

---

## 6. 默认账号

当前默认演示账号已切换为手机号登录：

| 用户名 | 手机号 | 说明 |
|---|---|---|
| `admin` | `13800000001` | 平台管理员 |
| `suba_admin` | `13800000002` | 公司管理员 |
| `emp_demo` | `13800000003` | 普通员工 |

说明：
- 当前前端默认使用手机号验证码登录。
- 若 `SMS_PROVIDER=mock`，系统走本地兼容链路。
- 若 `SMS_PROVIDER=unisms` 且 `UNISMS_ENABLED=true`，系统走 UniSMS 模板短信发送。

权限规划文档：
- `docs/user-management-plan.md`

---

## 7. 核心接口（按模块）

以下均为 `API_V1_PREFIX=/api/v1` 下的路径。

### 7.1 认证与会话

- `POST /auth/login`：登录获取 JWT。
- `GET /auth/me`：获取当前用户、核心角色、权限点、数据范围。
- `POST /auth/sms/send-code`：发送手机号登录验证码。
- `POST /auth/sms/send`：兼容旧链路的发码接口。
- `POST /auth/sms/login`：手机号验证码登录/激活。
- `WS /ws/realtime?token=JWT`：实时推送通道。

### 7.2 租户与站点

- `GET /tenants`：查询可见公司列表（按权限裁剪）。
- `GET /projects`：查询可见项目列表；平台管理员默认可查看所有公司下的项目。
- `GET /sites`：查询可见站点列表（按权限裁剪）。
- `POST /sites`：创建站点（平台管理员可指定公司，公司管理员仅可操作本公司资源）。

### 7.3 数据采集与查询

- `POST /ingest/telemetry`：标准采集入口。
- `POST /ingest/dtu`：DTU 适配入口。
- `POST /ingest/estone`：兼容适配入口。
- `GET /ingest/queue-status`：采集队列状态。
- `GET /telemetry/latest`：最新值查询。
- `GET /telemetry/history`：历史曲线查询。
- `GET /telemetry/history-batch`：批量历史查询（默认支持分钟聚合）。

### 7.3.1 B接口协议2016（平台接入协议）

平台当前按 2016 版 B 接口作为 FSU 接入协议。设备侧把上级 `SC` 地址指向平台后，平台接收 `LOGIN`、`SEND_ALARM` 以及 `GET_DATA_ACK/GET_HISDATA_ACK`，并映射到站点、设备、遥测和告警数据。

- 真实设备入口：`POST /services/SCService`
- 兼容入口：`POST /services/FSUService`
- 调试入口：`POST /api/v1/b-interface/2016/invoke`
- 主动轮询：`POST /api/v1/b-interface/2016/poll`
- 维谛轮询：`POST /api/v1/b-interface/2016/vertiv/{fsu_code}/poll`
- 健康检查：`GET /api/v1/b-interface/2016/health`
- WSDL 占位：`GET /services/SCService?wsdl`

支持裸 XML、gSOAP `xmlData` 请求包以及 `return` 回包。维谛设备登录后会保存 `FsuIP`，需要平台主动采集时，可通过 `/api/v1/b-interface/2016/vertiv/{fsu_code}/poll` 自动向设备 `FSUService` 发 `GET_DATA(Code=401)` 并处理返回的 `GET_DATA_ACK`。详细说明见 `docs/b-interface-2016.md`。

### 7.4 告警

- `GET /alarms`：告警列表（支持分页与状态筛选，返回 `X-Total-Count`）。
- `POST /alarms/{id}/ack`：确认告警。
- `POST /alarms/{id}/close`：关闭告警。

### 7.5 规则与策略

- `GET /alarm-rules`：模板规则列表（按权限裁剪）。
- `POST /alarm-rules`：新增模板规则（按权限裁剪）。
- `PUT /alarm-rules/{id}`：修改模板规则（按权限裁剪）。
- `GET /alarm-rules/tenant-policies`：查看公司策略（平台管理员可指定公司，公司管理员默认仅本公司）。
- `PUT /alarm-rules/tenant-policies/{id}`：修改公司策略（按权限裁剪）。

### 7.6 用户与角色

- `GET /users`：用户列表（平台管理员看公司管理员，公司管理员看本公司员工）。
- `POST /users`：创建用户（平台管理员创建公司管理员，公司管理员创建员工）。
- `PUT /users/{id}`：更新用户基本信息、权限和数据范围。
- `GET /users/meta`：获取核心角色、权限模板、权限点、数据范围选项。

说明：
- 当前仍保留 `GET/POST/PUT/DELETE /users/role-defs` 兼容接口，但不再建议作为主流程使用。
- 新主流程是“少量核心角色 + 权限模板 + 数据范围”。

### 7.7 通知与报表

- `GET /notify/channels`：查看通知通道（`notify.channel.view`）。
- `POST /notify/channels`：创建通知通道（`notify.channel.manage`）。
- `POST /notify/channels/{id}/test`：测试通知通道（`notify.channel.manage`）。
- `GET /notify/policies`：查看通知策略（`notify.policy.view`）。
- `POST /notify/policies`：创建通知策略（`notify.policy.manage`）。
- 通知策略支持绑定多个通道，后端会并行尝试发送；兼容旧字段 `channel_id`。
- `GET /reports/alarm-summary`：告警统计报表（按权限裁剪）。

说明：
- `wechat_robot`：`endpoint` 填企业微信群机器人 webhook 地址。
- `sms_tencent`：`endpoint` 填手机号列表（逗号分隔），例如 `+8613800138000,+8613900139000`。

### 7.8 可观测性

- `GET /metrics`：Prometheus 采集指标。

---

## 8. 环境配置说明（`backend/.env`）

### 8.1 基础配置

- `API_V1_PREFIX`：接口前缀，默认 `/api/v1`。
- `SECRET_KEY`、`ALGORITHM`：JWT 签名配置。
- `ACCESS_TOKEN_EXPIRE_MINUTES`：令牌有效期（分钟）。
- `CORS_ORIGINS`：前端跨域白名单。

### 8.2 数据库连接池

- `DATABASE_URL`：默认 PostgreSQL。
- `TIMESCALEDB_AUTO_ENABLE`：是否在启动时自动启用 TimescaleDB（默认 `true`）。
- `DB_POOL_SIZE`、`DB_MAX_OVERFLOW`：连接池容量。
- `DB_POOL_TIMEOUT_SECONDS`：取连接超时。
- `DB_POOL_RECYCLE_SECONDS`：连接回收周期。
- `DB_POOL_PRE_PING`：连接可用性探测。

### 8.3 采集模式（高并发关键）

- `INGEST_MODE=direct`：同步写库，读写一致性强。
- `INGEST_MODE=queue`：请求先入队，再异步批量写库，吞吐更高。
- `INGEST_QUEUE_MAXSIZE`：队列长度。
- `INGEST_QUEUE_WORKERS`：消费协程数。
- `INGEST_QUEUE_BATCH_SIZE`：批量写入条数。
- `INGEST_QUEUE_BATCH_WAIT_MS`：批量聚合等待时延。
- `INGEST_THREAD_TOKENS`：线程池令牌上限。

建议：
- 大规模设备接入优先 `INGEST_MODE=queue`。
- 需要强一致读写回显时选 `direct`。

### 8.4 系统规则评估

- `SYSTEM_RULE_EVAL_ENABLED`：是否开启系统规则调度。
- `SYSTEM_RULE_EVAL_INTERVAL_SECONDS`：评估周期。
- `SYSTEM_RULE_INLINE_ENABLED`：是否在采集链路内联评估。

### 8.5 DTU Gateway

- `DTU_GATEWAY_ENABLED`：是否启用 DTU 网关配置模板。
- `DTU_GATEWAY_HOST` / `DTU_GATEWAY_PORT`：DTU TCP 监听地址。
- `DTU_GATEWAY_PROTOCOL`：当前报文解析器，默认 `json_line`。
- `DTU_GATEWAY_FRAME_MODE`：拆帧模式，支持 `line` 和 `idle`。
- `DTU_GATEWAY_FRAME_DELIMITER`：`line` 模式分隔符，默认 `\n`。
- `DTU_GATEWAY_IDLE_FLUSH_SECONDS`：`idle` 模式下的空闲分帧时间。
- `DTU_GATEWAY_MESSAGE_MAX_BYTES`：单帧最大长度。
- `DTU_GATEWAY_BACKEND_INGEST_URL`：网关转发地址，默认 `/api/v1/ingest/dtu`。
- `DTU_GATEWAY_RAW_LOG_ENABLED` / `DTU_GATEWAY_RAW_LOG_DIR`：原始报文落盘开关与目录。

说明：
- 当前默认提供 `json_line / telemetry_json / estone_json` 三类解析器。
- 如果后续 DTU 上送的是厂商私有二进制帧，只需要在 `backend/app/services/protocol_adapters.py` 新增解析器，不需要改告警、时序库和前端展示链路。

### 8.6 腾讯云短信（重要告警）

- `SMS_TENCENT_ENABLED`：是否启用腾讯云短信通道（默认 `false`）。
- `SMS_TENCENT_SECRET_ID`：腾讯云 API 密钥 ID。
- `SMS_TENCENT_SECRET_KEY`：腾讯云 API 密钥 Key。
- `SMS_TENCENT_SDK_APP_ID`：短信应用 SDK AppID。
- `SMS_TENCENT_SIGN_NAME`：短信签名。
- `SMS_TENCENT_TEMPLATE_ID`：短信模板 ID。
- `SMS_TENCENT_REGION`：区域，默认 `ap-guangzhou`。
- `SMS_TENCENT_TEMPLATE_MODE`：模板参数模式，支持：
  - `single_text`：单变量模板（推荐，模板只放 `{1}`）。
  - `alarm_v6`：六变量模板（事件/站点/设备/监控项/级别/状态）。

### 8.7 手机号登录与 UniSMS

- `SMS_PROVIDER`：短信服务商开关，当前支持：
  - `mock`
  - `unisms`
- `SMS_PHONE_LOGIN_ENABLED`：是否启用手机号验证码登录主链路。
- `SMS_CODE_LENGTH`：验证码位数，默认 `6`。
- `SMS_CODE_EXPIRE_SECONDS`：验证码有效期，默认 `300` 秒。
- `SMS_SEND_INTERVAL_SECONDS`：同手机号重发间隔，默认 `60` 秒。
- `SMS_SEND_LIMIT_PER_10M`：同手机号 10 分钟发送次数上限。
- `SMS_VERIFY_MAX_ATTEMPTS`：单验证码最大输错次数。
- `SMS_LOGIN_FAIL_LOCK_THRESHOLD`：账号累计失败阈值。
- `SMS_LOGIN_LOCK_MINUTES`：达到阈值后的锁定时长。
- `SMS_IP_LIMIT_PER_MINUTE` / `SMS_IP_LIMIT_PER_HOUR`：IP 限流阈值。

UniSMS 配置项：

- `UNISMS_ENABLED`
- `UNISMS_ACCESS_KEY_ID`
- `UNISMS_ACCESS_KEY_SECRET`
- `UNISMS_HMAC_ENABLED`
- `UNISMS_SMS_SIGNATURE`
- `UNISMS_LOGIN_TEMPLATE_ID`
- `UNISMS_DLR_VERIFY_ENABLED`
- `UNISMS_DLR_SECRET`

推荐做法：

- 本地调试继续使用 `backend/.env.example`
- 准备切到 UniSMS 实发时，先参考 `backend/.env.unisms.example`
- 把正式参数写入 `backend/.env`
- 重启后端后再联调发码和回执

UniSMS 相关接口：

- `POST /api/v1/auth/sms/send-code`
- `POST /api/v1/auth/sms/login`
- `POST /api/v1/webhooks/unisms/dlr`

当前项目状态：

- 骨架、双表模型、DLR 验签与回执落库已完成。
- 若未配置正式 UniSMS 参数，系统会自动回退到 mock/兼容链路。

切换到 UniSMS 实发的最小步骤：

1. 用 `backend/.env.unisms.example` 作为参考补齐 `backend/.env`
2. 确认 `SMS_PROVIDER=unisms`
3. 确认 `UNISMS_ENABLED=true`
4. 配好 `UNISMS_ACCESS_KEY_ID / UNISMS_ACCESS_KEY_SECRET / UNISMS_SMS_SIGNATURE / UNISMS_LOGIN_TEMPLATE_ID / UNISMS_DLR_SECRET`
5. 重启后端
6. 调用 `POST /api/v1/auth/sms/send-code`
7. 检查 `auth_sms_code` 和 `auth_sms_delivery_log`
- 详细执行记录见 `docs/unisms-sms-task-record.md`。

---

## 9. 数据库与时序能力

### 9.1 当前默认数据库

- PostgreSQL（默认连接：`postgresql+psycopg://fsu:fsu123456@127.0.0.1:5432/fsu`）
- 初始化 SQL：`backend/sql/init_postgres.sql`

### 9.2 时序查询优化（已落地）

后端启动会确保以下关键索引存在：
- `telemetry_history(point_id, collected_at DESC)`
- `telemetry_latest(collected_at DESC)`
- `monitor_point(point_key, device_id)`

### 9.3 TimescaleDB（默认启用）

- 默认自动启用 Timescale 扩展，增强时序写入与压缩能力。
- 迁移 `20260303_0006` 已包含 `telemetry_history` hypertable 转换。
- 策略建议：
  - 最近 7 天不压缩。
  - 7 天前数据压缩。
  - 历史保留 90 天（按业务再调）。
- 如需关闭自动启用，可在 `backend/.env` 中设置：`TIMESCALEDB_AUTO_ENABLE=false`。

### 9.4 PostgreSQL 快速初始化示例

```powershell
# 1) 创建账号与数据库
$env:PGPASSWORD='postgres'
psql -U postgres -h 127.0.0.1 -d postgres -c "create role fsu login password 'fsu123456';"
psql -U postgres -h 127.0.0.1 -d postgres -c "create database fsu owner fsu;"

# 2) 执行迁移
cd C:\Users\Administrator\Desktop\fsu-platform\backend
$env:DATABASE_URL='postgresql+psycopg://fsu:fsu123456@127.0.0.1:5432/fsu'
python -m alembic upgrade head
```

---

## 10. 本地监控栈（可选，非容器）

已提供本地脚本，默认组合：
- MQTT（本地脚本当前可使用 `amqtt` 兼容）
- Prometheus
- Alertmanager
- Grafana

### 10.1 安装与启动

```powershell
cd C:\Users\Administrator\Desktop\fsu-platform

# 安装依赖与二进制
powershell -ExecutionPolicy Bypass -File .\scripts\install-free-stack-local.ps1

# 启动整套本地服务
powershell -ExecutionPolicy Bypass -File .\scripts\start-free-stack-local.ps1

# 健康检查
powershell -ExecutionPolicy Bypass -File .\scripts\check-free-stack-local.ps1

# 端到端验证（MQTT -> Bridge -> Backend -> Prometheus）
powershell -ExecutionPolicy Bypass -File .\scripts\verify-free-stack-local.ps1

# 停止服务
powershell -ExecutionPolicy Bypass -File .\scripts\stop-free-stack-local.ps1
```

Windows 常驻启动：

```powershell
# 安装当前用户登录自启动任务
powershell -ExecutionPolicy Bypass -File .\scripts\install-services.ps1

# 卸载自启动任务
powershell -ExecutionPolicy Bypass -File .\scripts\uninstall-services.ps1
```

- `install-services.ps1` 现在使用“计划任务”在当前用户登录后自动拉起前后端。
- 不再使用 `sc.exe create` 伪装 Windows Service；`uvicorn` 和 `vite preview` 在这台机器上用计划任务更稳定。
- 默认端口：
  - 前端：`http://localhost:5173`
  - 后端：`http://127.0.0.1:8000`

### 10.2 常用地址

- Backend：`http://127.0.0.1:8000`
- MQTT Broker：`127.0.0.1:1883`
- Bridge Metrics：`http://127.0.0.1:9108`
- Prometheus：`http://127.0.0.1:9090`
- Alertmanager：`http://127.0.0.1:9093`
- Grafana：`http://127.0.0.1:3000`（`admin / admin123456`）

配置文件位置：
- `deploy/prometheus/prometheus.yml`
- `deploy/prometheus/alert.rules.yml`
- `deploy/alertmanager/alertmanager.yml`
- `deploy/grafana/provisioning/*`
- `deploy/grafana/dashboards/fsu-realtime-overview.json`

---

## 11. 测试与压测脚本

脚本目录：`backend/scripts/`

### 11.1 功能回归与曲线数据

```powershell
cd C:\Users\Administrator\Desktop\fsu-platform\backend

# 全量监控项回归（登录 + 采集 + 告警 + 查询）
python scripts\test_all_metrics.py --base-url http://127.0.0.1:8000 --username admin --password admin123

# 权限回归（/auth/me + authz + 站点/通知/告警细粒度权限）
python scripts\test_authz_permissions.py

# 公司中心资源回归（项目 / 设备组 / 自定义范围 CRUD + 公司管理员权限边界）
python scripts\test_company_scope_resources.py

# 公司中心批量创建员工（如需手动验证，可在页面内使用“批量创建”入口）
# 当前批量入口默认绑定当前公司范围，复杂范围请创建后单独编辑

# 10分钟、15秒间隔采集回归
python scripts\test_ingest_10min_15s.py --base-url http://127.0.0.1:8000 --interval-seconds 15 --duration-minutes 10

# 20分钟持续稳定性测试
python scripts\test_soak_20min.py --base-url http://127.0.0.1:8000 --duration-minutes 20

# 平滑曲线数据生成（用于实时曲线展示）
python scripts\mock_curve_ingest.py --base-url http://127.0.0.1:8000 --duration-minutes 20 --interval-seconds 5
```

### 11.2 FSU-2808IM 采集桥

```powershell
cd C:\Users\Administrator\Desktop\fsu-platform\backend

# 先只看桥接后的标准 payload
python scripts\fsu_2808im_bridge.py --password "你的设备密码" --dry-run --once

# 再持续上报到平台
python scripts\fsu_2808im_bridge.py --password "你的设备密码" --backend-ingest-url http://127.0.0.1:8000/api/v1/ingest/telemetry
```

说明：
- 脚本会登录 FSU-2808IM 的 Web CGI 接口，自动读取内部设备列表并轮询 `0x0011` 实时信号。
- 已内置关键测点映射，包括 `room_temp`、`room_humidity`、`mains_voltage`、`mains_current`、`mains_frequency`、`mains_power_state`、`rectifier_output_voltage`、`rectifier_output_current`、`rectifier_fault_status`、`dc_bus_voltage`、`dc_current`、`dc_breaker_status`、`battery_group_voltage`、`battery_group_current`、`battery_temp`、`battery_fault_status`、`battery_fuse_status`、`spd_failure`、`water_leak_status`、`smoke_status`、`door_access_status`、`ac_running_status`、`ac_fault_status`、`ac_comm_status`。
- 如需同时保留原始测点，可追加 `--include-raw-signals`。

### 11.3 DTU TCP 网关

```powershell
cd C:\Users\Administrator\Desktop\fsu-platform\backend

# 默认按换行拆帧，适合 DTU 透传 JSON 行协议
python scripts\dtu_ingest_gateway.py

# 若 DTU 采用空闲分帧，切到 idle 模式
$env:DTU_GATEWAY_FRAME_MODE='idle'
python scripts\dtu_ingest_gateway.py
```

说明：
- 网关负责监听 DTU TCP 上行端口，并转发到 `POST /api/v1/ingest/dtu`。
- 当前支持 `line` 和 `idle` 两种拆帧模式，适配大多数 DTU 透传场景。
- 原始报文会按 `jsonl` 落盘到 `backend/logs/dtu-raw/`，便于后续补私有协议解析器。

推荐接入策略：
- 当前 `FSU-2808IM` 脚本仅用于协议摸底、点表确认和兼容存量设备。
- 后续新设备建议统一通过 `DTU TCP -> /api/v1/ingest/dtu` 接入平台，不再按单设备单脚本接入。
- 平台侧应尽量把 DTU 上报内容收口为统一 JSON 帧，这样新增设备时只需要补 DTU 解析器或点表映射，不需要改告警、时序入库和前端页面。

推荐 DTU 上报样例：

```json
{
  "protocol": "json_line",
  "payload_text": "{\"site_code\":\"SITE-001\",\"site_name\":\"站点A\",\"fsu_code\":\"DTU-001\",\"fsu_name\":\"DTU设备1\",\"collected_at\":\"2026-03-15T20:30:00+08:00\",\"metrics\":[{\"key\":\"room_temp\",\"name\":\"机房温度\",\"value\":26.5,\"unit\":\"C\",\"category\":\"env\"},{\"key\":\"mains_voltage\",\"name\":\"市电电压\",\"value\":220.1,\"unit\":\"V\",\"category\":\"power\"}]}"
}
```

如果 DTU 直接透传标准 JSON，也可以让平台收到的 `payload_text` 解出后是下面这种对象：

```json
{
  "site_code": "SITE-001",
  "site_name": "站点A",
  "fsu_code": "DTU-001",
  "fsu_name": "DTU设备1",
  "collected_at": "2026-03-15T20:30:00+08:00",
  "metrics": [
    {
      "key": "room_temp",
      "name": "机房温度",
      "value": 26.5,
      "unit": "C",
      "category": "env"
    },
    {
      "key": "mains_voltage",
      "name": "市电电压",
      "value": 220.1,
      "unit": "V",
      "category": "power"
    }
  ]
}
```

推荐约束：
- 每帧只上传一个站点/一个 FSU 的一次采样。
- `collected_at` 使用 ISO 8601 时间。
- `key` 保持平台统一监控项命名，不把厂商私有点号直接暴露到前端。
- 厂商私有点号、寄存器地址、二进制协议差异，尽量在 DTU 解析器内消化。

### 11.4 铁塔 B 接口抓包接收端

```powershell
cd C:\Users\Administrator\Desktop\fsu-platform\backend

# 生产抓包建议直接监听 80/21
python scripts\sc_b_interface_honeypot.py --host 0.0.0.0 --http-port 80 --ftp-port 21

# 本地验证可先用高位端口
python scripts\sc_b_interface_honeypot.py --host 127.0.0.1 --http-port 18080 --ftp-port 2121
```

说明：
- 该脚本用于模拟 `SC` 接收端，抓取 FSU 北向 `B接口` 原始上报。
- 当前同时提供：
  - HTTP/XML 接收与最小协议响应
  - FTP 被动模式上传接收
  - 可配置的 `GET_FSUINFO / GET_DATA` 主动轮询器
- 所有原始请求会落盘到 `backend/logs/sc-bait/`：
  - HTTP 请求头、路径、请求体
  - FTP 命令流水
  - FTP 上传文件原文
  - 轮询请求与响应 XML
- 适用方式：
  - 将 FSU 的 `SC服务器地址` 改为本机 IP
  - 保持设备北向端口按原配置不变
  - 观察设备先连 HTTP 还是 FTP，再据此整理真实 `B接口` 协议
  - 如果现场日志确认 `GET_FSUINFO / GET_DATA` 由 `SC` 主动发起，可补 `--poll-target-url` 开启轮询

注意：
- Windows 下监听 `80/21` 端口通常需要管理员权限。
- 这个脚本当前已经能按日志格式回 `SEND_ALARM_ACK`，但仍不等于完整铁塔 `B接口 SC` 实现。
- 如果设备要求更严格的 XML 字段、命令码或鉴权字段，需要根据抓到的真实请求继续补模板。

配套分析脚本：
- `backend/scripts/decode_pktmon_http.py`
- 作用：把 `pktmon format` 生成的 `UTF-16` 十六进制文本还原为 HTTP 请求/响应，直接列出 `commandid / resultCode / port / msgBody / response_body`
- 适用场景：设备 Web 页面或本机 CGI 调试流量已被 `pktmon` 抓到，但不想再手工抠十六进制

示例：

```powershell
cd C:\Users\Administrator\Desktop\fsu-platform\backend
python scripts\decode_pktmon_http.py .\logs\pktmon-fsu\fsu-hex.txt
python scripts\decode_pktmon_http.py .\logs\pktmon-fsu\fsu-hex.txt --json
```

轮询示例：

```powershell
cd C:\Users\Administrator\Desktop\fsu-platform\backend
python scripts\sc_b_interface_honeypot.py --host 0.0.0.0 --http-port 80 --ftp-port 21 --poll-target-url http://192.168.100.100:80/your-b-interface-path --poll-interval-seconds 300
```

### 11.5 2000 台设备压测

```powershell
cd C:\Users\Administrator\Desktop\fsu-platform\backend

# 突发压测（burst）
python scripts\load_test_2000.py --base-url http://127.0.0.1:8000 --devices 2000 --rounds 3 --concurrency 200 --max-connections 1200 --retries 1

# 实时节拍压测（按周期平铺发送，更接近现场）
python scripts\load_test_2000_realtime.py --base-url http://127.0.0.1:8000 --devices 2000 --rounds 1 --cycle-seconds 15 --concurrency 300 --max-connections 1200 --retries 1
```

### 11.6 TimescaleDB 性能对比（2026-03-06 实测）

脚本：
- `backend/scripts/benchmark_timescaledb_compare.py`（基础对比）
- `backend/scripts/benchmark_timescaledb_stress.py`（并发写入 + 压缩前后对比）

压力对比命令：

```powershell
cd C:\Users\Administrator\Desktop\fsu-platform\backend
python scripts\benchmark_timescaledb_stress.py --rows 1200000 --workers 8 --batch-rows 5000 --points 2000 --span-days 60 --runs 5
```

关键结果（`bench_pg_stress` vs `bench_ts_stress`）：
- 写入（120 万条，8 并发）：
  - PostgreSQL 普通表：`6.714s`
  - Timescale hypertable：`6.977s`（约慢 3.9%）
- 30 天范围计数查询：
  - PostgreSQL 普通表：`109.184ms`
  - Timescale（压缩前）：`99.535ms`（约快 8.8%）
  - Timescale（压缩后）：`25.148ms`（约快 77.0%）
- 单点近 7 天 Top1000 查询：
  - PostgreSQL 普通表：`0.107ms`
  - Timescale（压缩后）：`0.136ms`（接近）

结论：
- Timescale 在大范围历史查询，尤其压缩后，有明显优势。
- 高频小范围点查场景，普通表与 Timescale 差距较小。
- 建议生产开启 `TIMESCALEDB_AUTO_ENABLE=true` 并保留压缩策略。

---

## 12. 常见问题排查

### 12.1 登录失败

排查顺序：
1. 后端是否启动：访问 `http://127.0.0.1:8000/health`。
2. 是否使用系统中已存在的手机号，且账号状态不是 `DISABLED / LOCKED`。
3. 如果走短信登录，先确认 `/api/v1/auth/sms/send-code` 是否正常返回。
4. 数据库是否连通，启动日志是否有迁移/建表错误。
5. `SECRET_KEY` 变更后，旧 token 失效，需重新登录。

### 12.2 页面无数据或实时曲线不显示

1. 确认采集接口是否有持续写入（可用 `mock_curve_ingest.py`）。
2. 检查前端当前账号是否有该站点租户权限。
3. 检查时间窗口与采样间隔是否匹配（分钟级曲线建议至少持续采集几分钟）。

### 12.3 实时页面卡顿

建议优先：
1. 降低前端单屏渲染卡片数（分层折叠展示）。
2. 启用后端 `INGEST_MODE=queue` 并调优队列参数。
3. 提升 PostgreSQL 连接池与硬件资源。
4. 对高频查询使用批量接口（`history-batch`）并做分钟聚合。

### 12.4 权限看起来异常

1. 检查 `GET /api/v1/auth/me` 返回的 `roles`、`tenant_codes`、`tenant_roles`。
2. 确认 `core_role` 是否正确，以及是否被错误地创建到了其他公司。
3. 检查 `permissions` 和 `data_scopes` 是否符合预期。
4. 平台管理员只负责公司和公司管理员，普通员工需要单独授权业务权限。

---

## 13. 开发建议

- 新功能优先遵守“租户边界先行”：先定义可见范围，再写接口逻辑。
- 涉及权限变更时，同步更新：
  - `backend/app/services/access_control.py`
  - `backend/app/api/deps.py`
  - `docs/user-management-plan.md`
  - 本 README 的权限章节
- 每个阶段完成后，至少执行一次：
  - 后端语法检查（`py_compile`）
  - 前端构建（`npm run build`）
  - 核心接口回归（登录/策略/告警/租户隔离）

---

## 14. 快速入口清单

- 后端健康：`http://127.0.0.1:8000/health`
- 前端入口：`http://127.0.0.1:5173`
- 实时 WS：`ws://127.0.0.1:8000/ws/realtime?token=JWT`
- Prometheus 指标：`http://127.0.0.1:8000/metrics`

如需继续扩展（如工单系统、审计日志、策略审批流），建议沿用当前多租户权限模型，不跨层绕过权限依赖。

---

## 15. 最近改动说明（2026-03-06）

本次已完成并验证的改动：

- 版本升级到 `v0.21`：
  - 后端默认版本号更新为 `0.21`。
  - 前端 `package.json` 版本更新为 `0.21`。
- 企业微信群机器人告警推送（v0.21 第一版）：
  - 通知通道新增企业微信机器人地址规则校验（必须包含 `key`）。
  - 推送结果判定支持企业微信 `errcode/errmsg` 解析，不再仅依赖 HTTP 状态码。
  - 新增 `POST /notify/channels/{id}/test` 测试接口。
  - 通知策略页面新增“通道测试”按钮与测试消息输入。
- 腾讯云短信告警推送（v0.21 扩展）：
  - 通知通道新增 `sms_tencent` 类型，支持多手机号（逗号分隔）。
  - 重要告警可通过策略路由到短信通道（由策略 `min_alarm_level` 控制）。
  - 支持腾讯云短信 API（TC3-HMAC-SHA256）签名发送与错误码解析。
  - 支持短信通道测试发送（复用 `POST /notify/channels/{id}/test`）。
- 通知模块管理闭环补全：
  - 新增通知通道编辑、启停、删除接口。
  - 新增通知策略编辑、启停、删除接口。
  - 删除被策略引用的通道时增加保护，避免产生悬空策略。
  - 前端通知页已补齐编辑、启停、删除、测试交互。
- 权限系统第一阶段重构：
  - 后端访问上下文统一聚合 `roles / permissions / scopes / role_bindings`。
  - `GET /auth/me` 已返回权限点和数据范围，前端不再依赖角色名硬编码。
  - 前端 `auth store`、路由守卫、主导航已切换为 permission 驱动。
  - 站点页、通知页、实时监控关键项配置已改为按权限点控制。
- 权限系统第二阶段重构：
  - 新增 `authz` 路由，支持角色权限绑定和用户数据范围绑定。
  - 用户管理页已重做为“角色权限 + 数据范围”交互，不再围绕租户角色拼装逻辑。
  - 告警、规则、实时监控、历史查询接口已切换为 permission 驱动。
- 权限系统第三阶段收口：
  - 告警动作权限已细化为 `alarm.ack` / `alarm.close`。
  - 站点治理权限已细化为 `site.create` / `site.update`。
  - 通知治理权限已细化为 `notify.channel.*` / `notify.policy.*`。
  - 保留旧键 `alarm.view`、`site.manage`、`notify.view`、`notify.manage` 的兼容映射，避免升级时现网角色立刻失效。

- TimescaleDB 默认启用：
  - 新增配置项 `TIMESCALEDB_AUTO_ENABLE`（默认 `true`）。
  - 启动时自动尝试启用扩展、hypertable、压缩与保留策略。
- 启动性能与稳定性修复：
  - 修复了启动阶段每次都重建 `telemetry_history` 主键的问题。
  - 当前逻辑仅在主键不符合 `(id, collected_at)` 时才调整，避免大表反复锁表。
- 性能基准脚本与文档补充：
  - 新增 `backend/scripts/benchmark_timescaledb_compare.py`。
  - 新增 `backend/scripts/benchmark_timescaledb_stress.py`。
  - README 已补充实测参数与结果（并发写入、压缩前后查询对比）。
- 运行链路回归：
  - 已执行 `backend/scripts/test_all_metrics.py`，结果 `PASS`。
  - 覆盖登录、采集、实时最新值、历史查询、告警触发/恢复主链路。
  - 已执行 `backend/scripts/test_authz_permissions.py`，结果 `PASS`。
  - 覆盖 `/auth/me`、角色权限绑定、用户数据范围绑定、站点/通知/告警细粒度权限拦截。
  - 已执行 `backend/scripts/test_company_scope_resources.py`，结果 `PASS`。
  - 覆盖公司管理员对项目、设备组、自定义范围的 CRUD，以及总部用户越权拦截。
  - 同时覆盖公司员工批量创建与“不能分配平台级角色”的边界校验。
  - 同时覆盖批量创建结果统计与最小审计记录落库。


### 15.6 公司用户数据范围扩展（2026-03-07）
- 用户管理页的数据范围从“公司 / 站点 / 区域”扩展为“公司 / 项目 / 站点 / 设备组 / 自定义范围”。
- 后端新增接口：
  - `GET /api/v1/projects?tenant_code=...`
  - `GET /api/v1/device-groups?tenant_code=...`
  - `GET|POST|PUT|DELETE /api/v1/custom-scope-sets?tenant_code=...`
- 后端权限上下文新增识别：`project`、`device_group`、`custom` 三类范围。
- 前端 `用户管理` 页面已支持为员工配置上述范围类型，并会按当前公司动态加载选项。
- 公司详情新增“自定义范围”页签，可直接维护站点集合并供员工授权复用。
- 公司详情新增“项目 / 设备组”维护能力，可直接创建、编辑、删除这两类授权资源。
- 后端新增项目、设备组 CRUD：
  - `GET|POST /api/v1/projects?tenant_code=...`
  - `PUT|DELETE /api/v1/projects/{id}?tenant_code=...`
  - `GET|POST /api/v1/device-groups?tenant_code=...`
  - `PUT|DELETE /api/v1/device-groups/{id}?tenant_code=...`
- 公司详情“员工”页签新增“批量创建”，支持按当前公司一次性创建多名普通员工。
- 批量创建改为“部分成功”模式：
  - 后端会逐条返回成功/失败结果
  - 前端会弹出明细，方便管理员定位哪一行有问题
- 公司详情新增“操作记录”页签：
  - 可直接查看当前公司的用户、项目、设备组和自定义范围操作轨迹
  - 后端新增 `GET /api/v1/operation-logs?tenant_code=...`
  - 支持按动作、操作人、日期范围筛选
  - 前端支持本地分页浏览
  - 后端新增 `GET /api/v1/operation-logs/export?tenant_code=...` 导出 CSV
- 操作记录已独立为权限点 `audit.view`
  - 当前保留 `user.view -> audit.view` 的兼容映射，避免现有角色升级时立刻失效
- 员工“批量创建”新增模板下载入口，管理员可直接下载文本模板后录入
- 员工“批量创建”新增重复账号处理策略：
  - 跳过已存在账号
  - 只更新姓名
  - 更新姓名并重置密码
  - 当前版本不会覆盖既有角色和数据范围
- `/users` 主链路已加租户边界校验：
  - 公司管理员只能看到本公司账号
  - 公司管理员不能给员工分配平台级核心角色或历史兼容角色
  - 公司管理员不能借接口把用户创建到其他公司
- 新增最小审计记录：
  - 新表 `sys_operation_log`
  - 当前已记录项目、设备组、自定义范围，以及单个/批量用户创建相关操作
- `backend/scripts/test_company_scope_resources.py` 现已覆盖：
  - `GET /api/v1/operation-logs?tenant_code=...`
  - `GET /api/v1/operation-logs/export?tenant_code=...`
  - 审计日志查询结果包含预期动作
- 默认示例数据会自动补齐：
  - `PROJ-001 / A公司示例项目`
  - `DG-001 / 核心设备组`
  - `默认重点站点` 自定义范围
- 升级后需重启一次后端，让 `project / device_group / custom_scope_*` 新表自动创建。

### 15.7 监控项中文映射与遗留心跳点清理（2026-03-08）
- 已补齐历史查询页和实时监控页对在用监控项的中文映射，覆盖了空调、油机、电池、整流器、设备组别名等实际使用中的英文 key。
- 当前在用监控项已完成映射核对，不再存在“仍在使用但没有中文映射”的监控项 key。
- 新增维护脚本：
  - `backend/scripts/cleanup_stale_heartbeat_points.py`
- 该脚本用于清理 `system:fsu_heartbeat_timeout` 的遗留监控点，并采用保守策略：
  - 仅删除“无实时值、无历史值、无告警事件引用”的点
  - 同步删除对应的 `alarm_condition_state`
  - 保留仍被 `alarm_event` 引用的点，避免破坏告警链路
- 本次已实际执行清理：
  - 删除 `10` 条未使用心跳超时监控点
  - 删除 `10` 条对应状态记录
  - 当前库内仅保留 `1` 条仍被告警事件引用的心跳超时监控点

### 15.8 历史查询二级筛选与监控项巡检（2026-03-08）
- 历史数据查询页已改成二级交互：
  - 第一步只检索站点
  - 第二步按分类勾选监控项
  - 查询结果按“采集时间 + 多监控项栏目”展示
- 历史查询页新增能力：
  - 监控项按“动力监控 / 环境监控 / 智能设备 / 其他”分组展示
  - 支持“全选 / 清空 / 全选本组 / 清空本组”
  - 默认优先勾选后端配置的关键监控项；若当前站点未命中关键项，则回退到站点前 4 个监控项
  - 采集时间已统一按前端本地时间格式显示，修复原始时间字符串显示异常
  - 每个监控项栏目已带单位，例如“市电电压（V）”
  - 支持 CSV 导出
- 已将监控项中文映射抽成前端公共配置：
  - `frontend/src/constants/pointMetadata.js`
  - 历史查询页与实时监控页共用同一份映射和分类逻辑，避免两处维护不一致
- 新增巡检脚本：
  - `backend/scripts/audit_unnamed_points.py`
  - 用于扫描库中“未命名监控项”，区分在用项与未使用项
- 当前巡检结果：
  - `unknown_count=0`
  - 说明本轮补映射与遗留心跳点清理后，当前库里已没有未命名监控项

### 15.9 实时监控初始化加载修复（2026-03-08）
- 修复问题：
  - 首次进入“实时监控”页时，偶发提示“站点数据加载失败”，需要手动刷新后才显示站点
- 原因：
  - `frontend/src/views/RealtimeView.vue` 在首屏初始化时执行 `rebuildImportantOptions()`
  - 该函数内部直接使用了 `importantCategoryOrder` 和 `importantCategoryLabelMap`
  - 但页面脚本里没有定义这两个变量，导致首屏进入时抛出 `ReferenceError`
  - 异常落在 `onMounted -> ensureInitialSitesReady()` 链路中，因此页面统一提示“站点数据加载失败”
- 修复方案：
  - 保留初始化阶段的稳态等待和骨架屏
  - 在实时监控页中补齐：
    - `const importantCategoryOrder = pointCategoryOrder`
    - `const importantCategoryLabelMap = pointCategoryLabelMap`
  - 让关键监控项配置分组与首屏初始化共用同一份分类常量，避免再次出现未定义变量
- 修改文件：
  - `frontend/src/views/RealtimeView.vue`

### 15.10 告警规则模板补全（2026-03-09）
- 扩展了内置告警规则模板，新增覆盖：
  - 电池熔丝告警
  - 油机启动失败
  - 油机油位过低
  - 防雷器失效
  - 空调高压告警
  - 空调低压告警
  - 空调通信异常
  - 摄像头离线
- 前端“告警规则（模板）”页面已同步补齐对应的分类和告警名称选项。
- 本次只补充语义明确、状态位含义稳定的模板，不对含义不清晰的状态点位做臆测规则。
- 新模板已通过 `seed_alarm_rules` 补入数据库；若页面暂时看不到，先确认后端服务已正常启动，并使用具备模板权限的账号（如 `admin`）查看“告警规则（模板）”。

### 15.11 通知策略页面布局修复（2026-03-09）
- 修复“通知策略 -> 通知通道”区域在中等宽度窗口下显示不全的问题。
- 调整内容包括：
  - 通知通道表格增加横向滚动容器
  - 补充地址列并开启溢出提示
  - 操作按钮区支持换行，避免右侧被截断
  - 通知策略表格同步调整为可滚动布局
- 修改文件：
  - `frontend/src/views/NotifyView.vue`

### 15.12 通知策略页面交互重做（2026-03-09）
- 将通知页从“双栏内嵌表单”改为“页签 + 列表 + 右侧抽屉编辑”。
- 调整后：
  - 通知通道和通知策略分开浏览
  - 列表保持完整可读，不再与编辑表单互相挤占空间
  - 新增、编辑统一在右侧抽屉中完成
  - 通道测试保留在列表操作区，并在编辑抽屉底部提供入口
  - 删除操作移入“更多”菜单，避免列表主操作区过于拥挤
- 修改文件：
  - `frontend/src/views/NotifyView.vue`

### 15.13 PushPlus 聚合通道与多通道策略（2026-03-09）
- 新增 `pushplus` 通道类型，用于微信/短信/邮件等 PushPlus 聚合推送。
- PushPlus 通道约定：
  - `endpoint` 存储 PushPlus token
  - `secret` 存储 JSON 配置，例如 `channel/topic/template`
  - 后端固定请求 `https://www.pushplus.plus/send`
- 通知策略从“单通道”扩展为“多通道”：
  - 表单支持一次绑定多个通知通道
  - 后端兼容旧字段 `channel_id`
  - 新增 `notify_policy.channel_ids` 字段并在启动时自动回填旧数据
- 告警触发时会按策略绑定的通道列表逐个发送，当前支持：
  - 企业微信机器人
  - PushPlus
  - 腾讯云短信
  - 通用 Webhook
- 修改文件：
  - `backend/app/models/notify.py`
  - `backend/app/schemas/notify.py`
  - `backend/app/api/routes/notify.py`
  - `backend/app/services/notifier.py`
  - `backend/app/main.py`
  - `frontend/src/views/NotifyView.vue`

### 15.14 告警通知文案模板统一（2026-03-09）
- 将通知消息从“直接拼接原始告警内容”改为统一模板。
- 当前默认文案规则：
  - 触发：`当前{告警名称}（当前{值}{单位}）`
  - 恢复：`{告警名称}已恢复（恢复时{值}{单位}）`
  - 确认：`{告警名称}已确认（当前{值}{单位}）`
  - 关闭：`{告警名称}已关闭（当前{值}{单位}）`
- 各通道表现：
  - 企业微信机器人：标题 + 摘要 + 站点/设备/监控项/时间
  - 腾讯云短信：压缩摘要，仅发送关键信息
  - PushPlus：标题 + 摘要 + 站点/设备/监控项/告警级别
  - Webhook：新增 `summary` 与 `trigger_value_text`
- 修改文件：
  - `backend/app/services/notifier.py`

### 15.15 告警中心文案与角色管理弹窗收口（2026-03-09）
- 告警中心列表文案进一步精简：
  - 告警名称优先按 `alarm_code` 映射中文
  - 告警内容统一收敛为“当前{监控项}过高/过低/异常（当前{值}{单位}）”
  - 对冗长原始规则文案做截断与噪音字段清理
- 用户管理页角色管理弹窗调整：
  - 角色列表弹窗加宽并支持内部滚动
  - 角色编辑弹窗支持内部滚动，避免权限分组显示不全
  - 说明和权限预览列增加溢出提示
- 修改文件：
  - `frontend/src/views/AlarmsView.vue`
  - `frontend/src/views/UsersView.vue`

### 15.16 PushPlus 中文乱码修复（2026-03-09）
- 将 PushPlus 默认模板从 `txt` 调整为 `html`。
- PushPlus 正文在发送前会将换行转换成 `<br/>`，避免中文内容在部分客户端渲染异常。
- 同步调整通知页 PushPlus 通道的默认模板配置为 `html`。
- 修改文件：
  - `backend/app/services/notifier.py`
  - `frontend/src/views/NotifyView.vue`

### 15.17 通知通道测试文案改为示例告警（2026-03-09）
- 原“通道测试”默认只发送一句“这是一条通知通道测试消息”，无法体现真实告警样式。
- 现在留空测试消息时，后端会发送一条示例告警内容：
  - 当前机房温度过高（当前42℃）
  - 站点/设备/监控项/告警级别/告警状态
- 前端测试输入框占位文案同步调整为“留空则发送示例告警内容”。
- 修改文件：
  - `backend/app/api/routes/notify.py`
  - `frontend/src/views/NotifyView.vue`

### 15.18 通知通道/策略历史乱码名称修复（2026-03-09）
- 对历史测试数据中的乱码名称和弱语义名称做一次性修复：
  - `PushPlus??` -> `PushPlus微信`
  - `PushPlus????` -> `PushPlus默认策略`
  - `????` / `__dup_test__` -> `测试Webhook通道1/2`
  - `1` -> `测试通知策略`
- 新增修复脚本：
  - `backend/scripts/fix_notify_display_names.py`
- 该脚本用于修正本地数据库中已有的通知通道/策略名称，不影响业务逻辑。

### 15.19 公司级告警通知治理（2026-03-09）
- 在原有“通知通道 / 通知策略”基础上，补齐了公司级通知治理第一阶段能力：
  - 通知接收人
  - 通知组
  - 推送规则
- 页面入口仍复用 `通知管理`，但已改为统一的页签结构：
  - 通知通道
  - 通知策略
  - 通知接收人
  - 通知组
  - 推送规则
- 公司级页签按 `tenant_code` 隔离加载，前端先选择公司，再查看或维护对应数据。
- 新增权限点：
  - `notify.receiver.view`
  - `notify.receiver.manage`
  - `notify.group.view`
  - `notify.group.manage`
  - `notify.rule.view`
  - `notify.rule.manage`
- 历史内置角色的兼容默认权限已同步扩展：
  - `platform_admin` 兼容映射
  - `company_admin` 兼容映射
  - 历史角色别名映射
- 新增后端接口：
  - `GET/POST/PUT/DELETE /api/v1/notify-receivers?tenant_code=...`
  - `GET/POST/PUT/DELETE /api/v1/notify-groups?tenant_code=...`
  - `GET/POST/PUT/DELETE /api/v1/notify-rules?tenant_code=...`
- 推送规则支持的作用范围：
  - `TENANT`
  - `PROJECT`
  - `SITE`
  - `DEVICE_GROUP`
  - `CUSTOM`
- 后端约束：
  - 强制校验 `tenant_code` 对应租户
  - 强制校验项目 / 站点 / 设备组 / 自定义范围是否属于当前公司
  - 禁止跨租户修改接收人、通知组、推送规则
  - 删除通知组前会检查是否仍被推送规则引用
- 本轮主要修改文件：
  - `backend/app/models/notify_admin.py`
  - `backend/app/schemas/notify_admin.py`
  - `backend/app/services/notify_guard.py`
  - `backend/app/api/routes/notify_receivers.py`
  - `backend/app/api/routes/notify_groups.py`
  - `backend/app/api/routes/notify_rules.py`
  - `backend/app/api/routes/projects.py`
  - `backend/app/api/routes/device_groups.py`
  - `frontend/src/views/NotifyView.vue`

### 15.20 告警通知治理二期：值班表与推送日志（2026-03-09）
- 在公司级通知治理基础上，继续补齐第二阶段能力：
  - 值班表
  - 推送日志
  - 失败重发
- 新增权限点：
  - `notify.oncall.view`
  - `notify.oncall.manage`
  - `notify.push_log.view`
  - `notify.push_log.retry`
- `通知管理` 页面新增两个公司级页签：
  - `值班表`
  - `推送日志`
- 值班表能力：
  - 支持按公司、项目、站点、设备组、自定义范围维护值班表
  - 支持配置值班成员顺位
  - 支持新增、编辑、删除
- 推送日志能力：
  - 真实告警发送时写入 `alarm_push_log`
  - 记录策略名、通道名、目标、发送状态、错误信息、重试次数
  - 页面支持查看最近日志并对失败记录执行重发
- 新增接口：
  - `GET/POST/PUT/DELETE /api/v1/notify-oncall?tenant_code=...`
  - `GET /api/v1/notify-push-logs?tenant_code=...`
  - `POST /api/v1/notify-push-logs/{id}/retry?tenant_code=...`
- 后端约束：
  - 值班表成员必须属于当前公司
  - 值班表作用范围必须属于当前公司
  - 推送日志查看与重发同样叠加租户与数据范围校验
- 本轮主要修改文件：
  - `backend/app/models/notify_admin.py`
  - `backend/app/schemas/notify_admin.py`
  - `backend/app/services/notifier.py`
  - `backend/app/api/routes/notify_oncall.py`
  - `backend/app/api/routes/notify_push_logs.py`
  - `frontend/src/views/NotifyView.vue`

### 15.21 DTU 接入网关与 README 日期记录要求（2026-03-15）
- 平台新增 DTU 接入能力：
  - 新增 `POST /api/v1/ingest/dtu`
  - 新增 `backend/scripts/dtu_ingest_gateway.py`
  - 支持 `line / idle` 两种 TCP 拆帧模式
  - 原始 DTU 报文可落盘到 `backend/logs/dtu-raw/`
- 协议适配层已扩展为可注册结构：
  - 当前内置 `json_line`
  - 当前内置 `telemetry_json`
  - 当前内置 `estone_json`
  - 后续新增厂商 DTU 私有协议时，优先在 `backend/app/services/protocol_adapters.py` 内补解析器
- `FSU-2808IM` 采集脚本保留用于协议摸底与存量兼容：
  - `backend/scripts/fsu_2808im_bridge.py`
- README 维护约定更新：
  - 以后每次修改 `README.md`，都需要在“最近改动说明”中补充明确日期
  - 日期格式统一使用 `YYYY-MM-DD`

### 15.22 铁塔 B 接口抓包接收端（2026-03-16）
- 新增 `SC` 仿真接收脚本：
  - `backend/scripts/sc_b_interface_honeypot.py`
- 该脚本用于在未知铁塔 `B接口` 细节前，先抓取 FSU 对上级 `SC` 的真实上报：
  - HTTP/SOAP 请求抓取
  - FTP 命令抓取
  - FTP 上传文件留存
- 当前能力边界：
  - 支持 HTTP 最小成功响应
  - 支持 FTP 被动模式上传接收
  - 适合协议摸底、字段确认、交互顺序确认
  - 还不等于完整铁塔 `B接口 SC` 正式实现
- README 已补充该脚本的启动方式、抓包目录和使用注意事项。

### 15.23 铁塔 B 接口最小协议仿真增强（2026-03-16）
- 根据现场 `XML.log` 已确认的命令集，`SC` 抓包脚本补齐了第一版协议行为：
  - 收到 `SEND_ALARM` 时返回 `SEND_ALARM_ACK`
  - 支持把 HTTP/XML 报文按 `PK_Type/Name` 落盘
  - 新增可配置的主动轮询器，用于向 FSU 发 `GET_FSUINFO / GET_DATA`
- 当前轮询器支持：
  - 指定 `--poll-target-url`
  - 指定轮询周期
  - 自定义 `GET_FSUINFO / GET_DATA` 请求模板文件
- 这版能力的目标是先让平台具备“最小 SC”形态，后续再根据真实抓包把命令码、URL 和 XML 结构补齐。

### 15.24 FSU CGI 抓包离线解析与命令补充（2026-03-16）
- 新增 `backend/scripts/decode_pktmon_http.py`，用于离线解析 `pktmon` 抓到的 `web_main.cgi` HTTP 十六进制文本。
- 已确认一批 `FSU-2808IM` 私有 CGI 命令：
  - `0x0001 / resultCode=0 / port=9528`：登录，返回 `用户名`、`sessionid`、`用户级别`
  - `0x0002 / resultCode=0 / port=9528`：心跳，返回 `0` 或设备类型状态
  - `0x0003 / resultCode=0 / port=9528`：设备类型/设备列表相关查询
  - `0x0004 / resultCode=0 / port=9528`：页面初始化类空响应查询
  - `0x0060 / resultCode=18 / port=9528`：返回 `站点名`、`FSUID`、`FSU型号`
  - `0x0061 / resultCode=7 / port=9528`：返回本机账号列表与级别
  - `0x0010 / resultCode=0 / port=9527`：内部设备列表查询
- 这批结果来自本机对设备 `http://192.168.100.100/cgi-bin/web_main.cgi` 的真实抓包，不是凭空猜测。
- 当前结论：
  - 设备私有 CGI 仍可访问
  - `SCIP` 改到本机后，设备没有主动向本机 `80/8080/21` 发起连接
  - 后续继续摸铁塔 `B接口`，应优先从设备 CGI 配置和网关侧单播流量两条线并行推进

### 15.25 铁塔北向改判为 `tt_proxy` 原始 TCP 10378（2026-03-16）
- 通过设备终端确认真实北向代理进程为 `/modem/gprs_monitor/tt_proxy`，而不是 `httpd` 直接向 `SCIP` 发 `HTTP/FTP`。
- `tt_proxy` 当前工作目录与程序路径：
  - `/modem/gprs_monitor`
  - `/modem/gprs_monitor/tt_proxy`
- 关键配置已确认：
  - `/modem/gprs_monitor/tt_proxy.ini` 当前上送目标为 `172.17.0.75:10378,172.29.138.129:10378`
  - `/modem/gprs_monitor/gprs_monitor.ini` 仍保留铁塔域名 `sc.toweraiot.cn / zb-sc.toweraiot.cn`
  - `/modem/gprs_monitor/vpn_db.ini` 显示四川省分组默认 `SCIP=172.17.0.50`
- 这说明之前只改 `/home/idu/XmlCfg/init_list.ini` 里的 `SCIP=192.168.100.123` 并不足以把真实北向上送改到本机。
- 本地 `SC` 抓包脚本已补充原始 TCP 监听能力：
  - 默认新增 `10378` 端口监听
  - 原始 TCP 首包落盘到 `backend/logs/sc-bait/tcp/`
- 后续若要直接抓设备真实北向首包，应优先改 `tt_proxy.ini` 的 `server=` 指向本机 `192.168.100.123:10378`，再重启 `tt_proxy` 或整机。

### 15.26 铁塔北向进一步确认走 L2TP/PPP 隧道（2026-03-17）
- 新增本地 L2TP 诱捕与配置回写脚本：
  - `backend/scripts/l2tp_bait.py`
  - `backend/scripts/fsu_keep_l2tp_local.py`
  - `backend/scripts/l2tp_bait_capture.ps1`
- 通过设备 CGI 持续把 LNS 指向本机后，已稳定观察到设备向本机 `UDP/1701` 发起 `L2TP`：
  - 出现 `SCCRQ -> SCCRP -> SCCCN`
  - 后续出现 `ICRQ -> ICRP -> ICCN`
  - 会持续发送 `HELLO`
- 这说明设备与上级的真实北向承载不是“直接 HTTP/FTP 到 SCIP”，而是先建 `L2TP/PPP` 隧道。
- 在 `2026-03-17` 的最新抓包中，隧道内已经出现 `PPP/IP(0x0021)` 业务流量，当前可见：
  - `10.10.10.2 -> 8.8.8.8` 的 `ICMP Echo`
  - `10.10.10.2 -> 192.168.100.123` 的 `ICMP Echo`
- `l2tp_bait.py` 现已把 PPP 内层 IPv4 元数据直接写入 JSON，包括：
  - `src_ip / dst_ip`
  - `ICMP type/code`
  - `UDP/TCP 端口`
- 当前阶段结论：
  - 先把 `L2TP` 隧道接住，比继续猜 `SC` 应用层报文更接近真实链路
  - 下一步应继续观察隧道内是否出现到铁塔平台的私有 TCP 会话、明文 XML、或二次封装流量

### 15.27 L2TP 内层 HTTP 回放原型（2026-03-17）
- `backend/scripts/l2tp_bait.py` 新增可选 HTTP 回放模式：
  - 启动参数：`--http-replay-base-url http://127.0.0.1:8000`
- 当前能力：
  - 从 `PPP/IP/TCP` 中识别发往 `80/8080/8000` 的明文 HTTP
  - 以 TCP 流为单位拼接请求头和请求体
  - 自动把请求回放到指定目标，例如本地 `SC` 调试服务
  - 回放结果落盘到 `backend/logs/l2tp-bait/http-replay/`
- 适用场景：
  - 想验证“设备虽然先走 L2TP，但应用层是否本质仍是 HTTP/XML”
  - 想把隧道内明文 HTTP 请求快速导入本地接口做联调
- 能力边界：
  - 这不是完整 PPP 出口网关，也不是完整 NAT
  - 当前只做“单向提取并回放 HTTP 请求”，不会把 HTTP 响应重新封回 L2TP 发给设备
  - 如果隧道内上层协议不是明文 HTTP，或启用了私有封装/加密，这个模式不会生效

### 15.28 固件包确认铁塔主北向为 `tt_proxy -> UDP/10378`（2026-03-17）
- 从升级包 `Update/eStoneII` 提取出的关键配置和组件：
  - `modem/gprs_monitor/tt_proxy.ini`
  - `modem/gprs_monitor/gprs_monitor.default.ini`
  - `modem/gprs_monitor/tt_proxy`
  - `modem/gprs_monitor/ttb.so`
- 现已确认：
  - `tt_proxy.ini` 的正式目标为 `172.29.138.117:10378,172.29.138.129:10378`
  - `gprs_monitor.default.ini` 的 `monitor_type = 2`，即 `usb modem + l2tp`
  - `l2tp_lns = 180.153.49.166`
  - `start_gprs` 会先启动 `tt_proxy`，再启动 `gprs_monitor`
- `tt_proxy` 二进制字符串显示主北向传输不是原始 HTTP，而是私有 `UDP`：
  - `bind udp %d success.`
  - `send_realtime_data`
  - `recved heartbeat rsp.`
  - `set heartbeat interval to %d seconds.`
  - `QZ^&`
  - `%d|%s`
  - `200|`
  - `deviceId=%s\`ID=%s\`bGet=true\`status=%d\`value=%s;`
- `ttb.so` 二进制字符串显示业务层来自本地 SOAP：
  - `http://127.0.0.1:8080/services/FSUService`
  - `SendReqData`
  - `<Name>GET_DATA</Name>`
  - `<Code>401</Code>`
  - `<FsuId>%s</FsuId>`
  - `<FsuCode>%s</FsuCode>`
- 当前最合理的主链路模型：
  - 设备先建 `L2TP/PPP`
  - `tt_proxy` 通过 `ttb.so` 从本机 `FSUService` 拉取 `GET_DATA(Code=401)` 等业务数据
  - `tt_proxy` 再把业务点位转成 `deviceId=...` 文本片段
  - 最后封装成私有 `UDP/10378` 报文上送铁塔侧
- 配套离线工具：
  - `backend/scripts/decode_ttproxy_udp10378.py`
  - `backend/scripts/ttproxy_udp_bait.py`
  - `backend/scripts/analyze_ttproxy_udp10378.py`
  - 当前按 `QZ^& + <code>|<body>` 解析，已能识别 `200|` 实时数据与 `online/offline/unknown` 状态词
- 当前阶段结论：
  - 先前在 `L2TP` 内抓到的 `UDP/7000` 更像辅链路/状态协议，不是铁塔主北向最终格式
  - 要拿到主协议实锤，下一步应把设备 `tt_proxy.ini` 的 `server=` 改到本机并抓一份真实 `10378/UDP` 首包
- 本机诱捕命令：
  - `cd backend`
  - `python scripts/ttproxy_udp_bait.py --host 0.0.0.0 --port 10378 --decode`
  - 抓包会落到 `backend/logs/ttproxy-udp/`，每个包同时生成 `.bin / .json / .decoded.json`
- 抓到真实包后的离线汇总：
  - `python scripts/analyze_ttproxy_udp10378.py .\\logs\\ttproxy-udp`
  - 可快速查看远端来源、消息码分布、类型分布和最近报文样本
- 现场改配置建议：
  - 把设备 `tt_proxy.ini` 的 `server=` 临时改为 `192.168.100.123:10378`
  - 保留原铁塔地址作为第二个备份项，避免回切困难
  - 重启 `tt_proxy` 后优先观察本机是否收到首个 `QZ^&...` 或 `200|...` 报文

### 15.29 设备联机改配与串口阻塞记录（2026-03-20）
- 通过离线 `pktmon` HTTP 解析，已从真实 Web 会话中恢复出一个仍可用的 `operator` 会话：
  - `sessionid = 69b87796_2953ad92`
- 基于该会话，已对设备 `http://192.168.100.100/cgi-bin/web_main.cgi` 完成真实写操作：
  - `0x0050 / resultCode=1`：成功把主 `L2TP/VPN` 改到本机 `192.168.100.123`
  - `0x0050 / resultCode=23`：成功把集团灾备 `VPN` 改到本机 `192.168.100.123`
- 现场验证过一个重要入口：
  - `0x0050 / resultCode=27` 会真实触发后台预置的 `vpnUpdate.sh ...` 模板
  - 例如执行 `vpnUpdate.sh SiChuan 1 YM` 后，主 VPN 配置会被切回 `sc-r.toweraiot.cn / sc.toweraiot.cn`
- 当前对 `resultCode=27` 的边界判断：
  - 能执行后台白名单 VPN 模板
  - 但暂未证实可执行任意自定义 shell
  - 直接传 `/bin/sh ...`、`/bin/echo ...`、在合法模板后拼接 `; sed ...`，都没有观察到可验证的自定义副作用
- 当前恢复后的主 VPN 读回结果为：
  - `192.168.100.123`
  - `192.168.100.123`
  - `10.0.0.0/8`
  - `ttcw2015 / ttcw@2015`
  - `192.168.100.123`
  - `192.168.100.123`
  - `192.168.100.1/8`
  - 最后一个备份位仍为 `sc.toweraiot.cn`
- `admin` 密码已确认收到：
  - `Admin@123`
  - 但当前直接登录返回 `-11`，说明不是密码错，而是“登录会话已满”
- 当前 `COM3` 串口在 Windows 侧的状态：
  - `mode COM3` 可见，参数为 `115200 8N1`
  - 但 `SerialPort.Open()` 仍返回 `A device attached to the system is not functioning.`
  - 因此本轮尚未进入设备 shell，`/modem/gprs_monitor/tt_proxy.ini` 还没有被直接改写
- 当前阶段结论：
  - Web 侧已经能稳定把 `L2TP/VPN` 拉到本机
  - `10378/UDP` 诱捕器已就位，可继续等待真实北向首包
  - 要直接修改 `tt_proxy.ini`，仍需拿到以下任一条件：
    - 可用串口 shell
    - 可用 `admin` 会话
    - 或新的高权限文件/脚本入口

### 15.30 B 接口 2016 作为平台接入协议（2026-04-20）
- 明确平台当前 FSU 接入协议采用铁塔 B 接口 2016：
  - 真实设备入口：`/services/SCService`
  - 兼容入口：`/services/FSUService`
  - 调试入口：`/api/v1/b-interface/2016/invoke`
- 已移除 2024 版直连接口入口：
  - 不再注册 `/api/v1/openapi/*`
  - 删除对应路由和 Schema
  - 设备台账表仅作为 2016 接入后的 FSU 注册信息存储
- `B 接口 2016` 解析增强：
  - 支持裸 XML
  - 支持 gSOAP `invoke/xmlData`
  - 支持 SOAP `return` 回包解析，便于处理 FSU 主动查询响应
- 新增主动轮询接口：
  - `POST /api/v1/b-interface/2016/poll`
  - `POST /api/v1/b-interface/2016/vertiv/{fsu_code}/poll`
  - 默认可向 FSU 发 `GET_DATA(Code=401)`
  - 若返回 `GET_DATA_ACK/GET_HISDATA_ACK`，平台会立即解析 `TSemaphore` 并写入遥测
- 按维谛/Vertiv eStoneII 接入方式升级：
  - `LOGIN_ACK` 返回 `RightLevel=2`
  - 登录时保存 `FsuIP / FSUVendor / FSUManufactor / Version / DeviceList`
  - 维谛专用轮询接口会使用登录保存的 `FsuIP` 自动请求 `http://<FsuIP>:8080/services/FSUService`
  - 遥测解析兼容 `TSemaphore / Semaphore / Signal / TSignal`
  - 遥测值兼容 `MeasuredVal / SetupVal / Status / Value / Val`
- `docs/b-interface-2016.md` 已改为现场接入说明，包含：
  - FSU 侧 `SC` 地址配置
  - 平台入口列表
  - 支持报文
  - 数据映射规则
  - 主动 `GET_DATA` 调试示例

### 15.31 维谛 `tt_proxy -> UDP/10378` 现场联调记录（2026-04-21）
- 设备现场配置已确认收敛到本机：
  - `/modem/gprs_monitor/tt_proxy.ini` 当前为 `server=192.168.100.123:10378,192.168.100.123:10378,`
  - `/modem/gprs_monitor/gprs_monitor.ini` 当前主 `server_ip / l2tp_lns / disaster_recovery_*` 均指向 `192.168.100.123`
- 当前设备北向现状已明确分成两层：
  - `SiteUnit/XML` 侧 `m_SCLoginIP=192.168.100.123:8004`
  - `tt_proxy` 侧已真实向本机 `UDP/10378` 发包，远端源端口为 `10379`
- `gprs_monitor.log` 当前关键结论：
  - 设备运行模式为 `monitor_type=6`
  - 启动日志显示 `will monitor l2tp over eth0 or usb modem (prefer eth0)`
  - 仍持续出现 `detect usb device pid-0x0000 vid-0x0000`、`modem start failed`，说明 USB modem 识别仍异常
- 本轮已补齐现场分析工具：
  - `backend/scripts/decode_ttproxy_udp10378.py`
    - 新增对 `15` 字节私有头 + `GB18030` 字段记录格式的识别
    - 可直接解析 `register-status` 包，并提取 `site_code / site_name / DataSCIP / register status`
  - `backend/scripts/analyze_ttproxy_udp10378.py`
    - 新增 `register_statuses`、`data_scip_values` 汇总
  - `backend/scripts/ttproxy_udp_responder.py`
    - 新增 `UDP/10378` 监听 + 可控回包实验能力
- 已抓到的真实 `10378` 首包已不再只是“未知包”，而是可解析的注册状态包：
  - 文本体固定从偏移 `15` 开始
  - 典型字段包括：
    - `19|51050243802162`
    - `22|192.168.100.123:8004`
    - `26|离线`
  - 这说明设备确实已把北向状态上送到本机，但尚未进入实时数据阶段
- 现场触发与回包试验结果：
  - 不回包时，`SiteUnit` 重启后会稳定收到一组 `register-status`：
    - 先上送 `26|siteunit未运行`
    - 随后变为 `26|离线`
    - 未出现 `QZ^&200|deviceId=...` 实时数据包
  - 试过对每个状态帧回 `同头 + 文本 "60"`：
    - 设备仍只回 `register-status`
    - 状态未被推进到 `online`
    - 也未触发 `QZ^&200` 实时数据流
  - 追加试过两种更接近心跳字符串的回包：
    - 纯文本 `60|good`
    - `同头 + 文本 "60|good"`
    - 两种方式都未推动状态离开 `离线`，也未触发 `QZ^&200`
  - 追加验证过 `8004/SCService` 监听窗口：
    - 本机在 `0.0.0.0:8004` 启动 HTTP 诱捕器后，再次重启 `SiteUnit`
    - 监听目录无任何 `HTTP` 请求落盘
    - 说明当前设备并不会在这一路径上主动向本机 `SCService` 发 B 接口登录
- 当前最准确的阶段判断：
  - “设备没有把包发到平台”这个问题已经排除
  - 现在卡在 `tt_proxy` 注册/心跳阶段，设备状态仍为 `0-no_service / 离线`
  - 当前猜测的心跳回包格式不足以推动设备进入实时数据阶段
- 相关现场目录：
  - 首次整机重启后抓到的历史状态包：`backend/logs/full-reboot-20260421-190011/ttproxy-udp`
  - 不回包复现实验：`C:\Users\测试\device-analysis\reply-test-20260421-3`
  - 回 `header-text 60` 的试验：`C:\Users\测试\device-analysis\reply-test-20260421-4`
  - 回 `text 60|good` 的试验：`C:\Users\测试\device-analysis\reply-test-20260421-5`
  - 回 `header-text 60|good` 的试验：`C:\Users\测试\device-analysis\reply-test-20260421-6`
  - `8004` 监听空窗口：`C:\Users\测试\device-analysis\sc8004-test-20260421`
- 后续建议：
  - 继续逆向 `tt_proxy` 真正的心跳/注册响应格式，目标是把状态从 `离线` 推进到 `online`
  - 当前已初步排除“先主动打 `HTTP/8004` 再转实时数据”的路径，下一轮应把重点放回 `10378` 注册响应协议本身

### 15.32 eStoneII 固件刷入与 DS/SC 登录链路确认（2026-04-26）
- 使用完整升级包改造后，现场刷入结果已确认生效：
  - `/home/idu/XmlCfg/init_list.ini` 已被读取，`m_SCLoginIP=192.168.100.123`
  - `MonitorUnitsStationName=1.xml` 已被 `SiteUnit` 读取
  - 采集配置从 `0` 个采集端口恢复为 `3` 个采集端口
  - `2801BM.so` 与 `FSUIO.so` 均加载成功
  - `SiteUnit` 主模块初始化成功
- 本轮关键固件配置：
  - `tt_proxy.ini` 指向 `192.168.100.123:10378`
  - `gprs_monitor.ini / gprs_monitor.bak.ini / gprs_monitor.default.ini` 的 `monitor_type=0`
  - `SiteUnit_TT.ini` 设置 `NoModemTest=1`，现场日志显示“测试模式, 不获取猫IP”
  - `DscIp=udp://192.168.100.123:9000`
  - `RDSIp=udp://192.168.100.123:7000`
  - `Model SO_Path=/data2/web/WebProvider.so`
- 刷入后设备已发出标准 `LOGIN(Code=101)` XML：
  - `FsuId=51051243812345`
  - `FsuCode=51051243812345`
  - `FsuIP=192.168.100.100`
  - `MacId=00:09:F5:FD:85:85`
  - `Version=21.1.HQ.FSU.WD.AA44.R`
  - `DeviceList` 包含烟感、温湿度、水浸、电池与 FSU 本体设备
- 本机抓包已确认设备真实打到平台侧 DS 端口：
  - `192.168.100.100:6000 -> 192.168.100.123:9000`
  - 抓到的首包长度为 `245` 字节
  - 包体不是 XML 明文，而是 DS 私有 UDP 传输层握手
  - 包内可见 `udp://192.168.100.100:6000` 与 `ftp://root:hello@192.168.100.100`
- 已做过最小回包试验：
  - 对 `UDP/9000` 握手包不回包时，设备等待后继续登录失败
  - 对握手包做原包回显时，设备仍每约 `3` 秒重复发送相同握手包
  - 对握手包只回传 `22` 字节传输层头时，设备仍成对重复发送 `209/245` 字节握手包
  - 因此简单回显和传输层头回显都不是有效 DS 应答格式
- 新增 DS 登录握手抓包与回包实验脚本：
  - `backend/scripts/ds_udp9000_responder.py`
  - 可解析 `6d7e...` 私有 UDP 握手包
  - 可提取包内 `udp://192.168.100.100:600x` 与 `ftp://root:hello@192.168.100.100`
  - 支持 `none / echo / prefix / text / custom-hex / ds-address-table-ack` 等回包模式
  - `ds-address-table-ack` 已按反汇编修正为 `status_byte + u16le(table_len) + type/len/url...`
  - `status_byte=0` 对应 `LogToDS return ... Success`，`1` 为 Fail，`2` 为 UnRegister
  - 地址表成功掩码疑似要求 type `0,5,6,7,8,9` 全部出现，对应诊断、信号、发布、事件、实时、历史通道
- 新增联合实验脚本：
  - `backend/scripts/estoneii_sc_lab.py`
  - 同时监听 `UDP/9000,7000` 和 HTTP `SCService`
  - 当前能稳定收到 `cmd=17` 私有 DS 握手并返回合法校验应答
  - 设备重启时 `XML.log` 已生成 `[Send CMD:LOGIN]`，但平台 HTTP `80/8000` 未收到连接
  - 后续联调在 `UDP/7000` 捕获到 `cmd=0x8011` 30 字节状态包，在 `UDP/9000` 捕获到 `cmd=0x001f` 24 字节短包
  - 说明该固件的 B 接口 XML 仍可能封装在 DS/RDS 私有 UDP 通道里，而不是裸 HTTP POST
- 当前阶段结论：
  - 固件配置、XML 配置、SO 路径、测试直连模式已经打通
  - “设备没有向平台发包”的问题已经排除
  - `UDP/9000` 帧头、校验和、请求 body 和 DS 地址表应答结构已基本解析
  - 当前阻塞点是 `GetServiceAddr/LoginToDSC` 之后的 `0x8011/0x001f` 短心跳 ACK 格式
- 现场验证命令：
  - 查看设备业务日志：`http://192.168.100.100/fsu_log/XML.log`
  - 抓 `tt_proxy` 状态包：`python backend/scripts/ttproxy_udp_responder.py --host 0.0.0.0 --port 10378`
  - 抓 DS 登录握手：`python backend/scripts/ds_udp9000_responder.py --port 9000 --reply-mode none --verbose`
  - 联合试验 DS/SC：`python backend/scripts/estoneii_sc_lab.py --duration 120 --udp-ports 9000,7000 --http-ports 80,8000 --reply-mode ds-session-ack --reply-status 0`
