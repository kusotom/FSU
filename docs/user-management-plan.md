# 用户与租户权限规划（Multi-tenant）

> 目标：明确“谁可以看什么、谁可以改什么”，并把规则落到 API 与代码依赖中，避免跨租户越权。

---

## 1. 文档目的与适用范围

本规划用于指导以下模块的权限设计与验收：
- 认证与会话：登录、身份识别、角色加载。
- 租户与站点：租户可见范围、站点创建归属。
- 监控数据：最新值、历史曲线、批量查询。
- 告警处理：告警列表、确认、关闭。
- 规则策略：总部模板、租户覆盖策略。
- 用户角色：用户创建、角色定义、绑定租户。

适用环境：
- 当前 `fsu-platform` 项目后端（FastAPI）与前端（Vue）。
- 当前内置租户与角色（`HQ-GROUP` / `SUB-A`，`admin/hq_noc/sub_noc/operator`）。

---

## 2. 核心原则

1. **租户数据隔离优先**
   - 非全局角色仅可访问自身租户绑定范围内的站点、数据、告警、策略。
2. **总部治理与生产操作分离**
   - `hq_noc` 可跨租户查看与模板治理，但不直接修改子公司生产策略。
3. **最小权限原则**
   - 默认不给权限，按能力位逐项授予。
4. **接口依赖统一收口**
   - 权限在后端依赖层集中判断，不在前端“仅靠隐藏按钮”实现安全。
5. **显式租户目标**
   - 全局角色查看租户策略时必须传 `tenant_code`，避免误操作默认租户。

---

## 3. 组织与租户模型

### 3.1 租户层级

- `HQ-GROUP`：集团/总部租户（`tenant_type=group`）。
- `SUB-A`：子公司 A 租户（`tenant_type=subsidiary`，`parent=HQ-GROUP`）。

### 3.2 资源归属关系

- 站点（Site）通过 `tenant_site_binding` 绑定到租户。
- 设备、测点、告警、历史数据以站点归属间接落租户边界。
- 用户通过 `user_tenant_role` 获得“租户范围 + 角色能力”。

---

## 4. 角色定义

- `admin`
  - 平台管理员。
  - 可全局查看、全局配置、全局应急修改。
- `hq_noc`
  - 集团/总部监控组。
  - 负责跨租户汇总、模板与基线治理。
  - 不直接修改子公司租户策略，不创建站点。
- `sub_noc`
  - 子公司监控组。
  - 仅在本租户范围内处理告警、维护策略、管理本租户资产。
- `operator`
  - 基础运维角色。
  - 通常作为附加角色，能力由组合角色决定。

---

## 5. 权限矩阵（当前生效规则）

| 能力 | admin | hq_noc | sub_noc |
|---|---|---|---|
| 跨租户查看站点/监控/告警 | 是 | 是 | 否 |
| 查看租户列表 | 是 | 是 | 否（仅自身租户） |
| 模板规则管理（`/alarm-rules`） | 是 | 是 | 否 |
| 租户策略查看（`/alarm-rules/tenant-policies`） | 是（需 `tenant_code`） | 是（需 `tenant_code`） | 是（仅本租户） |
| 租户策略修改（`PUT tenant-policies`） | 是 | 否 | 是（仅本租户） |
| 新建站点（指定任意租户） | 是 | 否 | 否 |
| 新建站点（本租户） | 是 | 否 | 是 |
| 告警确认/关闭 | 是 | 是 | 是（仅本租户） |
| 用户与角色管理 | 是 | 否 | 否 |

说明：
- `hq_noc` 的定位是“治理与监督”，不是“代替子公司执行生产策略变更”。
- `sub_noc` 允许改本租户策略，但禁止跨租户。

---

## 6. 后端能力位映射（代码语义）

当前通过 `AccessContext` 暴露能力位，主要包括：
- `can_global_read`
- `can_manage_templates`
- `can_view_tenant_strategy`
- `can_edit_tenant_strategy`
- `can_manage_tenant_assets`

建议阅读文件：
- `backend/app/services/access_control.py`
- `backend/app/api/deps.py`

这些能力位由角色集合与租户绑定共同决定，再由路由依赖统一拦截。

---

## 7. API 与权限依赖映射（关键）

### 7.1 认证

- `POST /api/v1/auth/login`：匿名可用。
- `GET /api/v1/auth/me`：登录后可用。

### 7.2 租户/站点

- `GET /api/v1/tenants`
  - 全局角色：可看全部租户。
  - 非全局角色：仅返回自身绑定租户。
- `GET /api/v1/sites`
  - 按站点所属租户自动裁剪。
- `POST /api/v1/sites`
  - `admin`：可指定任意租户。
  - `sub_noc`：仅允许创建到自身租户。
  - `hq_noc`：拒绝（403）。

### 7.3 监控数据

- `GET /api/v1/telemetry/latest`
- `GET /api/v1/telemetry/history`
- `GET /api/v1/telemetry/history-batch`

以上接口均按“可访问站点集合”裁剪，避免跨租户读取。

### 7.4 告警

- `GET /api/v1/alarms`
- `POST /api/v1/alarms/{id}/ack`
- `POST /api/v1/alarms/{id}/close`

告警处理会先校验告警所属站点是否在当前用户可访问范围。

### 7.5 规则与策略

- 模板规则（总部治理）：
  - `GET/POST/PUT /api/v1/alarm-rules`
  - 仅 `admin/hq_noc`。
- 租户策略（生产策略）：
  - `GET /api/v1/alarm-rules/tenant-policies`
    - `admin/hq_noc/sub_noc` 可查看。
    - `admin/hq_noc` 必须显式传 `tenant_code`。
  - `PUT /api/v1/alarm-rules/tenant-policies/{id}`
    - 仅 `admin/sub_noc`。
    - `sub_noc` 仅可操作本租户。

### 7.6 用户与角色

- `GET /api/v1/users`
- `POST /api/v1/users`
- `GET /api/v1/users/roles`
- `GET/POST/PUT/DELETE /api/v1/users/role-defs`

以上均为 `admin` 权限。

---

## 8. 用户创建与绑定约束

### 8.1 创建约束

- 必须至少有一个角色。
- 允许同时提交：
  - 全局角色列表 `role_names`
  - 多租户角色绑定 `tenant_roles`
- 后端会合并并校验角色集合，避免“只传绑定不传角色”导致失败。

### 8.2 租户绑定边界

- `admin` / `hq_noc`：仅允许绑定 `HQ-GROUP`。
- `sub_noc`：禁止绑定 `HQ-GROUP`。
- 对于非全局角色（`operator/sub_noc` 及自定义角色），必须显式传 `tenant_roles`。
- `admin/hq_noc` 若未显式绑定，后端默认绑定 `HQ-GROUP`。

### 8.3 角色定义管理

- 支持新增、编辑、删除自定义角色。
- 内置角色（`admin/operator/hq_noc/sub_noc`）不可改名、不可删除。
- 被用户或租户关系引用的角色不可删除（返回 409 并提示引用计数）。

---

## 9. 前端交互约束（建议与现状）

1. 菜单展示应与后端权限一致。
2. `hq_noc` 进入规则页应默认模板治理视图，不提供租户策略编辑入口。
3. `sub_noc` 进入规则页应默认本租户策略视图，不提供模板新增/编辑入口。
4. 用户管理页仅 `admin` 可见。
5. 即使前端误放出按钮，后端依赖仍必须拦截（安全兜底）。

---

## 10. 验证清单（验收用）

### 10.1 基础登录

- `admin / admin123` 登录成功。
- `hq_noc / noc12345` 登录成功。
- `suba_noc / noc12345` 登录成功。

### 10.2 策略权限

- `hq_noc`：
  - `GET /alarm-rules` => 200
  - `PUT /alarm-rules/tenant-policies/{id}` => 403
  - `GET /alarm-rules/tenant-policies`（不带 `tenant_code`）=> 400
- `sub_noc`：
  - `GET /alarm-rules` => 403
  - `GET /alarm-rules/tenant-policies` => 200（仅本租户）
  - `PUT /alarm-rules/tenant-policies/{id}`（本租户）=> 200
  - `PUT /alarm-rules/tenant-policies/{id}`（跨租户）=> 403

### 10.3 站点权限

- `hq_noc`：`POST /sites` => 403
- `sub_noc`：`POST /sites`（本租户）=> 200，跨租户 => 403

### 10.4 数据隔离

- `sub_noc` 在 `GET /sites` / `GET /alarms` / `GET /telemetry/*` 中不应看到非本租户数据。

---

## 11. 变更流程建议

每次权限变更建议按以下顺序执行：
1. 更新能力位定义：`access_control.py`
2. 更新依赖层：`deps.py`
3. 更新路由依赖与边界校验：`api/routes/*.py`
4. 更新文档：本文件 + `README.md`
5. 执行回归：
   - 后端语法检查（`py_compile`）
   - 核心权限接口回归（3类账号）
   - 前端构建（`npm run build`）

---

## 12. 后续增强建议

1. 引入策略审批流：总部“建议/发布”，子公司“确认执行”。
2. 增加策略审计日志：记录谁在何时修改了哪些阈值。
3. 增加租户管理员角色：支持子公司自主管理本租户账号。
4. 增加工单模块并纳入同一租户边界（创建、派单、处理、报表）。

---

如本规划与业务组织结构变更冲突，以“租户隔离优先、模板治理与生产执行分离”作为最终裁决原则。
