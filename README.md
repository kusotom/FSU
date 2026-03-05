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
- 消息接入：HTTP Ingest（内置）+ MQTT Bridge（可选）

---

## 2. 系统架构与数据流

```text
采集设备/FSU
   │
   ├─ HTTP: /api/v1/ingest/telemetry
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
    sql/                   # PostgreSQL 初始化 SQL
  frontend/                # Vue 前端
    src/views/             # 页面（实时监控、告警、规则、用户管理等）
    src/stores/            # Pinia 状态（登录态、权限）
  deploy/                  # Prometheus/Alertmanager/Grafana/MQTT 配置
  scripts/                 # Windows 本地启动/检查/安装脚本
  docs/
    user-management-plan.md # 用户与租户权限规划（中文）
```

---

## 4. 多租户隔离与权限模型（重点）

### 4.1 设计原则

平台采用“多租户隔离 + 总部治理”模型：
- 每个租户（公司）只看/只管自己的站点、设备、数据、告警和策略。
- 集团/总部角色可跨租户查看汇总与模板，但不直接改子公司生产策略。
- 管理员保留全局运维能力（用于平台治理和应急）。

### 4.2 内置角色

- `admin`：平台管理员（全局读写）。
- `hq_noc`：总部监控组（跨租户查看 + 模板治理）。
- `sub_noc`：子公司监控组（仅本租户范围内管理）。
- `operator`：基础运维角色（可与 `hq_noc` / `sub_noc` 组合使用）。

### 4.3 权限边界矩阵

| 能力 | admin | hq_noc | sub_noc |
|---|---|---|---|
| 跨租户查看站点/数据/告警 | 是 | 是 | 否 |
| 模板规则管理（`/alarm-rules`） | 是 | 是 | 否 |
| 租户策略查看（`/alarm-rules/tenant-policies`） | 是（需指定 `tenant_code`） | 是（需指定 `tenant_code`） | 是（仅本租户） |
| 租户策略修改（`PUT tenant-policies`） | 是 | 否 | 是（仅本租户） |
| 站点创建 | 是（可指定租户） | 否 | 是（仅本租户） |
| 告警确认/关闭 | 是 | 是 | 是（仅本租户） |
| 用户与角色管理 | 是 | 否 | 否 |

说明：
- 全局角色（`admin` / `hq_noc`）查询租户策略时，必须显式传 `tenant_code`，避免误操作。
- `hq_noc` 不能创建站点，也不能修改租户策略，符合“总部治理不直接改生产策略”的边界。

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

# （可选）如果你希望显式执行迁移
python -m alembic upgrade head

# 启动服务
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

健康检查：
- `http://127.0.0.1:8000/health`

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

| 用户名 | 密码 | 角色说明 |
|---|---|---|
| `admin` | `admin123` | 平台管理员 |
| `hq_noc` | `noc12345` | 总部监控组（跨租户查看、模板治理） |
| `suba_noc` | `noc12345` | 子公司 A 监控组（仅本租户） |

权限规划文档：
- `docs/user-management-plan.md`

---

## 7. 核心接口（按模块）

以下均为 `API_V1_PREFIX=/api/v1` 下的路径。

### 7.1 认证与会话

- `POST /auth/login`：登录获取 JWT。
- `GET /auth/me`：获取当前用户、角色、租户范围。
- `WS /ws/realtime?token=JWT`：实时推送通道。

### 7.2 租户与站点

- `GET /tenants`：查询可见租户列表（按权限裁剪）。
- `GET /sites`：查询可见站点列表（按权限裁剪）。
- `POST /sites`：创建站点（`admin` 全局可建，`sub_noc` 仅本租户可建）。

### 7.3 数据采集与查询

- `POST /ingest/telemetry`：标准采集入口。
- `POST /ingest/estone`：兼容适配入口。
- `GET /ingest/queue-status`：采集队列状态。
- `GET /telemetry/latest`：最新值查询。
- `GET /telemetry/history`：历史曲线查询。
- `GET /telemetry/history-batch`：批量历史查询（默认支持分钟聚合）。

### 7.4 告警

- `GET /alarms`：告警列表（支持分页与状态筛选，返回 `X-Total-Count`）。
- `POST /alarms/{id}/ack`：确认告警。
- `POST /alarms/{id}/close`：关闭告警。

### 7.5 规则与策略

- `GET /alarm-rules`：模板规则列表（`admin/hq_noc`）。
- `POST /alarm-rules`：新增模板规则（`admin/hq_noc`）。
- `PUT /alarm-rules/{id}`：修改模板规则（`admin/hq_noc`）。
- `GET /alarm-rules/tenant-policies`：查看租户策略（`admin/hq_noc/sub_noc`）。
  - `admin/hq_noc` 必须传 `tenant_code`。
- `PUT /alarm-rules/tenant-policies/{id}`：修改租户策略（`admin/sub_noc`）。

### 7.6 用户与角色

- `GET /users`：用户列表（`admin`）。
- `POST /users`：创建用户（`admin`）。
- `GET /users/roles`：角色名列表（`admin`）。
- `GET /users/role-defs`：角色定义列表（`admin`）。
- `POST /users/role-defs`：新增角色定义（`admin`）。
- `PUT /users/role-defs/{id}`：修改角色定义（`admin`）。
- `DELETE /users/role-defs/{id}`：删除角色定义（`admin`，内置/被引用角色会被保护）。

### 7.7 通知与报表

- `GET /notify/channels`、`POST /notify/channels`：通知通道管理（模板管理权限）。
- `GET /notify/policies`、`POST /notify/policies`：通知策略管理（模板管理权限）。
- `GET /reports/alarm-summary`：告警统计报表（按权限裁剪）。

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

# 10分钟、15秒间隔采集回归
python scripts\test_ingest_10min_15s.py --base-url http://127.0.0.1:8000 --interval-seconds 15 --duration-minutes 10

# 20分钟持续稳定性测试
python scripts\test_soak_20min.py --base-url http://127.0.0.1:8000 --duration-minutes 20

# 平滑曲线数据生成（用于实时曲线展示）
python scripts\mock_curve_ingest.py --base-url http://127.0.0.1:8000 --duration-minutes 20 --interval-seconds 5
```

### 11.2 2000 台设备压测

```powershell
cd C:\Users\Administrator\Desktop\fsu-platform\backend

# 突发压测（burst）
python scripts\load_test_2000.py --base-url http://127.0.0.1:8000 --devices 2000 --rounds 3 --concurrency 200 --max-connections 1200 --retries 1

# 实时节拍压测（按周期平铺发送，更接近现场）
python scripts\load_test_2000_realtime.py --base-url http://127.0.0.1:8000 --devices 2000 --rounds 1 --cycle-seconds 15 --concurrency 300 --max-connections 1200 --retries 1
```

### 11.3 TimescaleDB 性能对比（2026-03-06 实测）

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
2. 是否使用默认账号（见“默认账号”章节）。
3. 数据库是否连通，启动日志是否有迁移/建表错误。
4. `SECRET_KEY` 变更后，旧 token 失效，需重新登录。

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
2. 确认角色是否绑定到了正确租户（如 `sub_noc` 不可绑定总部租户）。
3. 当前策略规则：`hq_noc` 可看策略但不能改；`sub_noc` 仅能改本租户策略。

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
