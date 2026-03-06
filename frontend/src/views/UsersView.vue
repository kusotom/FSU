<template>
  <AppShell>
    <div class="page-head">
      <div>
        <h2>用户与角色管理</h2>
        <p>角色负责功能权限，数据范围负责可见租户、站点和区域。</p>
      </div>
      <div class="head-actions">
        <el-button @click="openRoleManager">角色管理</el-button>
        <el-button type="primary" @click="openCreate">新建用户</el-button>
      </div>
    </div>

    <el-table :data="rows" stripe>
      <el-table-column prop="id" label="编号" width="72" />
      <el-table-column prop="username" label="用户名" min-width="120" />
      <el-table-column prop="full_name" label="姓名" min-width="120" />
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag :type="row.is_active ? 'success' : 'info'">{{ row.is_active ? "启用" : "停用" }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="角色" min-width="160">
        <template #default="{ row }">{{ formatRoleNames(row.roles) }}</template>
      </el-table-column>
      <el-table-column label="功能权限" min-width="260">
        <template #default="{ row }">{{ formatPermissions(row.permissions) }}</template>
      </el-table-column>
      <el-table-column label="数据范围" min-width="260">
        <template #default="{ row }">{{ formatDataScopes(row.data_scopes) }}</template>
      </el-table-column>
      <el-table-column prop="created_at" label="创建时间" min-width="180" />
      <el-table-column label="操作" width="220" fixed="right">
        <template #default="{ row }">
          <el-button size="small" @click="openEdit(row)">编辑</el-button>
          <el-button size="small" @click="toggleActive(row)">
            {{ row.is_active ? "停用" : "启用" }}
          </el-button>
          <el-button size="small" type="danger" @click="removeUser(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog
      v-model="dialogVisible"
      :title="editingUserId ? '编辑用户' : '新建用户'"
      width="920px"
      destroy-on-close
    >
      <el-form label-width="96px">
        <div class="grid grid-two">
          <el-form-item label="用户名" required>
            <el-input v-model="form.username" placeholder="例如：ops_zhangsan" />
          </el-form-item>
          <el-form-item label="姓名">
            <el-input v-model="form.full_name" placeholder="例如：张三" />
          </el-form-item>
        </div>

        <div class="grid grid-two">
          <el-form-item :label="editingUserId ? '新密码' : '密码'" required>
            <el-input
              v-model="form.password"
              type="password"
              show-password
              :placeholder="editingUserId ? '留空则不修改密码' : '至少 6 位'"
            />
          </el-form-item>
          <el-form-item label="用户状态">
            <el-switch
              v-model="form.is_active"
              active-text="启用"
              inactive-text="停用"
              :disabled="!editingUserId"
            />
          </el-form-item>
        </div>

        <el-form-item label="角色" required>
          <el-select
            v-model="form.role_names"
            multiple
            filterable
            style="width: 100%"
            placeholder="选择一个或多个角色"
          >
            <el-option
              v-for="role in roleDefs"
              :key="role.id"
              :label="roleLabel(role.name)"
              :value="role.name"
            />
          </el-select>
        </el-form-item>

        <div class="panel">
          <div class="panel-head">
            <div>
              <div class="panel-title">功能权限预览</div>
              <div class="panel-tip">权限由角色定义，不在用户上单独勾选。</div>
            </div>
          </div>
          <div class="chip-list">
            <el-tag v-for="item in selectedPermissionTags" :key="item" type="info" effect="plain">
              {{ permissionLabel(item) }}
            </el-tag>
            <span v-if="selectedPermissionTags.length === 0" class="empty-inline">请先选择角色</span>
          </div>
        </div>

        <div class="panel">
          <div class="panel-head">
            <div>
              <div class="panel-title">数据范围</div>
              <div class="panel-tip">决定这个用户可以看到哪些租户、站点和区域数据。</div>
            </div>
            <el-button size="small" @click="addScope">添加范围</el-button>
          </div>
          <div v-for="(scope, index) in form.data_scopes" :key="index" class="scope-row">
            <el-select v-model="scope.scope_type" style="width: 180px" @change="onScopeTypeChange(scope)">
              <el-option
                v-for="item in scopeTypeOptions"
                :key="item.key"
                :label="item.label"
                :value="item.key"
              />
            </el-select>
            <el-select
              v-if="scope.scope_type !== 'all'"
              v-model="scope.scope_value"
              filterable
              clearable
              style="flex: 1"
              :placeholder="scopePlaceholder(scope.scope_type)"
            >
              <el-option
                v-for="option in scopeValueOptions(scope.scope_type)"
                :key="`${scope.scope_type}-${option.value}`"
                :label="option.label"
                :value="option.value"
              />
            </el-select>
            <el-input v-else model-value="全部数据" disabled style="flex: 1" />
            <el-button text type="danger" @click="removeScope(index)">删除</el-button>
          </div>
        </div>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitLoading" @click="submitUser">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="roleDialogVisible" title="角色管理" width="960px">
      <div class="dialog-toolbar">
        <el-button type="primary" @click="openRoleCreate">新增角色</el-button>
      </div>
      <el-table :data="roleDefs" stripe>
        <el-table-column prop="name" label="角色标识" min-width="150">
          <template #default="{ row }">{{ roleLabel(row.name) }}</template>
        </el-table-column>
        <el-table-column prop="description" label="角色说明" min-width="180" />
        <el-table-column label="功能权限" min-width="300">
          <template #default="{ row }">{{ formatPermissions(row.permissions) }}</template>
        </el-table-column>
        <el-table-column label="类型" width="90">
          <template #default="{ row }">{{ row.is_builtin ? "内置" : "自定义" }}</template>
        </el-table-column>
        <el-table-column label="操作" width="170">
          <template #default="{ row }">
            <el-button size="small" @click="openRoleEdit(row)">编辑</el-button>
            <el-button size="small" type="danger" :disabled="row.is_builtin" @click="deleteRole(row)">
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>

    <el-dialog
      v-model="roleEditVisible"
      :title="roleEditingId ? '编辑角色' : '新增角色'"
      width="760px"
      destroy-on-close
    >
      <el-form label-width="96px">
        <el-form-item label="角色标识" required>
          <el-input
            v-model="roleForm.name"
            :disabled="roleForm.is_builtin"
            placeholder="例如：regional_manager"
          />
          <div class="field-tip">仅支持小写字母、数字、下划线，必须以字母开头。</div>
        </el-form-item>
        <el-form-item label="角色说明">
          <el-input v-model="roleForm.description" placeholder="例如：区域负责人" />
        </el-form-item>
        <el-form-item label="功能权限" required>
          <el-checkbox-group v-model="roleForm.permissions" :disabled="roleForm.is_builtin" class="permission-grid">
            <el-checkbox v-for="item in permissionOptions" :key="item.key" :label="item.key" :value="item.key">
              <span>{{ item.label }}</span>
              <small>{{ item.description }}</small>
            </el-checkbox>
          </el-checkbox-group>
          <div v-if="roleForm.is_builtin" class="field-tip">内置角色权限由系统维护，不允许手工修改。</div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="roleEditVisible = false">取消</el-button>
        <el-button type="primary" @click="submitRole">保存</el-button>
      </template>
    </el-dialog>
  </AppShell>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import AppShell from "../components/AppShell.vue";
import http from "../api/http";

const rows = ref([]);
const tenants = ref([]);
const sites = ref([]);
const roleDefs = ref([]);
const permissionOptions = ref([]);
const scopeTypeOptions = ref([]);
const dialogVisible = ref(false);
const roleDialogVisible = ref(false);
const roleEditVisible = ref(false);
const submitLoading = ref(false);
const editingUserId = ref(null);
const roleEditingId = ref(null);

const roleLabelMap = {
  admin: "管理员",
  operator: "运维人员",
  hq_noc: "总部监控组",
  sub_noc: "子公司监控组",
};

const scopeTypeLabelMap = {
  all: "全部数据",
  tenant: "公司/租户",
  site: "站点",
  region: "区域",
};

const form = reactive({
  username: "",
  full_name: "",
  password: "",
  is_active: true,
  role_names: [],
  data_scopes: [],
});

const roleForm = reactive({
  name: "",
  description: "",
  permissions: [],
  is_builtin: false,
});

const createScope = () => ({
  scope_type: "tenant",
  scope_value: "",
});

const roleLabel = (name) => roleLabelMap[name] || name;

const permissionLabel = (key) => {
  const item = permissionOptions.value.find((option) => option.key === key);
  return item?.label || key;
};

const selectedPermissionTags = computed(() => {
  const permissionSet = new Set();
  for (const roleName of form.role_names) {
    const role = roleDefs.value.find((item) => item.name === roleName);
    for (const key of role?.permissions || []) {
      permissionSet.add(key);
    }
  }
  return Array.from(permissionSet).sort();
});

const regionOptions = computed(() => {
  const map = new Map();
  for (const site of sites.value) {
    const region = String(site.region || "").trim();
    if (!region || map.has(region)) continue;
    map.set(region, { value: region, label: region });
  }
  return Array.from(map.values()).sort((a, b) => a.label.localeCompare(b.label));
});

const scopeValueOptions = (scopeType) => {
  if (scopeType === "tenant") {
    return tenants.value.map((item) => ({ value: item.code, label: `${item.name}（${item.code}）` }));
  }
  if (scopeType === "site") {
    return sites.value.map((item) => ({ value: item.code, label: `${item.name}（${item.code}）` }));
  }
  if (scopeType === "region") {
    return regionOptions.value;
  }
  return [];
};

const scopePlaceholder = (scopeType) => {
  if (scopeType === "tenant") return "选择公司/租户";
  if (scopeType === "site") return "选择站点";
  if (scopeType === "region") return "选择区域";
  return "";
};

const formatRoleNames = (roles) => (roles || []).map((item) => roleLabel(item)).join("、") || "-";

const formatPermissions = (permissions) =>
  (permissions || []).map((item) => permissionLabel(item)).join("、") || "-";

const formatDataScopes = (scopes) => {
  if (!Array.isArray(scopes) || scopes.length === 0) return "-";
  return scopes
    .map((item) => `${scopeTypeLabelMap[item.scope_type] || item.scope_type}：${item.scope_name || item.scope_value}`)
    .join("；");
};

const normalizeFormDataScopes = (scopes) => {
  if (!Array.isArray(scopes) || scopes.length === 0) return [createScope()];
  return scopes.map((item) => ({
    scope_type: item.scope_type || "tenant",
    scope_value: item.scope_type === "all" ? "*" : item.scope_value || "",
  }));
};

const resetForm = () => {
  editingUserId.value = null;
  form.username = "";
  form.full_name = "";
  form.password = "";
  form.is_active = true;
  form.role_names = [];
  form.data_scopes = [createScope()];
};

const resetRoleForm = () => {
  roleEditingId.value = null;
  roleForm.name = "";
  roleForm.description = "";
  roleForm.permissions = [];
  roleForm.is_builtin = false;
};

const buildPayload = () => {
  const username = String(form.username || "").trim();
  if (!username) {
    throw new Error("用户名不能为空");
  }
  if (username.length < 3 || username.length > 64) {
    throw new Error("用户名长度必须在 3-64 位之间");
  }
  if (!editingUserId.value && String(form.password || "").length < 6) {
    throw new Error("密码长度至少 6 位");
  }
  if ((form.password || "") && String(form.password).length < 6) {
    throw new Error("密码长度至少 6 位");
  }
  if (!Array.isArray(form.role_names) || form.role_names.length === 0) {
    throw new Error("请至少选择一个角色");
  }

  const scopeMap = new Map();
  for (const item of form.data_scopes) {
    const scopeType = String(item.scope_type || "").trim();
    let scopeValue = String(item.scope_value || "").trim();
    if (!scopeType) continue;
    if (scopeType === "all") {
      scopeValue = "*";
    }
    if (!scopeValue) {
      throw new Error("请完整填写数据范围");
    }
    scopeMap.set(`${scopeType}:${scopeValue}`, { scope_type: scopeType, scope_value: scopeValue });
  }
  const dataScopes = Array.from(scopeMap.values());
  if (dataScopes.length === 0) {
    throw new Error("请至少配置一个数据范围");
  }
  const tenantRoles = dataScopes
    .filter((item) => item.scope_type === "tenant")
    .flatMap((item) => form.role_names.map((roleName) => ({ tenant_code: item.scope_value, role_name: roleName })));

  return {
    username,
    full_name: String(form.full_name || "").trim() || null,
    password: editingUserId.value ? String(form.password || "") || null : String(form.password || ""),
    is_active: form.is_active,
    role_names: [...form.role_names],
    data_scopes: dataScopes,
    tenant_roles: tenantRoles,
  };
};

const loadRoleDefs = async () => {
  const res = await http.get("/users/role-defs");
  roleDefs.value = Array.isArray(res.data) ? res.data : [];
};

const loadMeta = async () => {
  const res = await http.get("/users/meta");
  permissionOptions.value = Array.isArray(res.data?.permission_options) ? res.data.permission_options : [];
  scopeTypeOptions.value = Array.isArray(res.data?.scope_type_options) ? res.data.scope_type_options : [];
};

const loadData = async () => {
  try {
    const [userRes, tenantRes, siteRes] = await Promise.all([
      http.get("/users"),
      http.get("/tenants"),
      http.get("/sites"),
    ]);
    rows.value = Array.isArray(userRes.data) ? userRes.data : [];
    tenants.value = Array.isArray(tenantRes.data) ? tenantRes.data : [];
    sites.value = Array.isArray(siteRes.data) ? siteRes.data : [];
    await Promise.all([loadRoleDefs(), loadMeta()]);
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || "加载用户管理数据失败");
  }
};

const openCreate = () => {
  resetForm();
  dialogVisible.value = true;
};

const openEdit = (row) => {
  editingUserId.value = row.id;
  form.username = row.username || "";
  form.full_name = row.full_name || "";
  form.password = "";
  form.is_active = Boolean(row.is_active);
  form.role_names = [...(row.roles || [])];
  form.data_scopes = normalizeFormDataScopes(row.data_scopes);
  dialogVisible.value = true;
};

const addScope = () => {
  form.data_scopes.push(createScope());
};

const removeScope = (index) => {
  if (form.data_scopes.length === 1) {
    form.data_scopes[0] = createScope();
    return;
  }
  form.data_scopes.splice(index, 1);
};

const onScopeTypeChange = (scope) => {
  scope.scope_value = scope.scope_type === "all" ? "*" : "";
};

const submitUser = async () => {
  try {
    submitLoading.value = true;
    const payload = buildPayload();
    if (editingUserId.value) {
      await http.put(`/users/${editingUserId.value}`, payload);
      ElMessage.success("用户已更新");
    } else {
      await http.post("/users", payload);
      ElMessage.success("用户已创建");
    }
    dialogVisible.value = false;
    await loadData();
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || e.message || "用户保存失败");
  } finally {
    submitLoading.value = false;
  }
};

const toggleActive = async (row) => {
  try {
    const payload = {
      username: row.username,
      full_name: row.full_name,
      password: null,
      is_active: !row.is_active,
      role_names: row.roles || [],
      data_scopes: (row.data_scopes || []).map((item) => ({
        scope_type: item.scope_type,
        scope_value: item.scope_value,
      })),
      tenant_roles: [],
    };
    await http.put(`/users/${row.id}`, payload);
    ElMessage.success(`用户已${row.is_active ? "停用" : "启用"}`);
    await loadData();
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || "状态更新失败");
  }
};

const removeUser = async (row) => {
  try {
    await ElMessageBox.confirm(`确定删除用户 ${row.username} 吗？`, "删除确认", { type: "warning" });
    await http.delete(`/users/${row.id}`);
    ElMessage.success("用户已删除");
    await loadData();
  } catch (e) {
    if (e === "cancel" || e === "close") return;
    ElMessage.error(e?.response?.data?.detail || "删除用户失败");
  }
};

const openRoleManager = async () => {
  await Promise.all([loadRoleDefs(), loadMeta()]);
  roleDialogVisible.value = true;
};

const openRoleCreate = () => {
  resetRoleForm();
  roleEditVisible.value = true;
};

const openRoleEdit = (row) => {
  roleEditingId.value = row.id;
  roleForm.name = row.name || "";
  roleForm.description = row.description || "";
  roleForm.permissions = [...(row.permissions || [])];
  roleForm.is_builtin = Boolean(row.is_builtin);
  roleEditVisible.value = true;
};

const submitRole = async () => {
  try {
    const name = String(roleForm.name || "").trim();
    if (!name) {
      throw new Error("角色标识不能为空");
    }
    if (!roleForm.is_builtin && (!Array.isArray(roleForm.permissions) || roleForm.permissions.length === 0)) {
      throw new Error("请至少选择一个功能权限");
    }
    const payload = {
      name,
      description: String(roleForm.description || "").trim() || null,
      permissions: roleForm.permissions,
    };
    if (roleEditingId.value) {
      await http.put(`/users/role-defs/${roleEditingId.value}`, payload);
      ElMessage.success("角色已更新");
    } else {
      await http.post("/users/role-defs", payload);
      ElMessage.success("角色已创建");
    }
    roleEditVisible.value = false;
    await Promise.all([loadRoleDefs(), loadData()]);
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || e.message || "角色保存失败");
  }
};

const deleteRole = async (row) => {
  try {
    await ElMessageBox.confirm(`确定删除角色 ${roleLabel(row.name)} 吗？`, "删除确认", { type: "warning" });
    await http.delete(`/users/role-defs/${row.id}`);
    ElMessage.success("角色已删除");
    await Promise.all([loadRoleDefs(), loadData()]);
  } catch (e) {
    if (e === "cancel" || e === "close") return;
    ElMessage.error(e?.response?.data?.detail || "删除角色失败");
  }
};

onMounted(() => {
  loadData();
});
</script>

<style scoped>
.page-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 16px;
}

.page-head h2 {
  margin: 0;
  font-size: 24px;
}

.page-head p {
  margin: 6px 0 0;
  color: #64748b;
}

.head-actions,
.dialog-toolbar {
  display: flex;
  gap: 8px;
}

.grid {
  display: grid;
  gap: 12px;
}

.grid-two {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.panel {
  padding: 14px;
  margin-bottom: 16px;
  border: 1px solid #dbe4f0;
  border-radius: 12px;
  background: linear-gradient(180deg, #fbfdff 0%, #f8fbff 100%);
}

.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.panel-title {
  font-size: 15px;
  font-weight: 700;
  color: #0f172a;
}

.panel-tip,
.field-tip {
  margin-top: 4px;
  color: #64748b;
  font-size: 12px;
}

.chip-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.empty-inline {
  color: #94a3b8;
  font-size: 13px;
}

.scope-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
}

.permission-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px 14px;
  width: 100%;
}

.permission-grid :deep(.el-checkbox) {
  display: flex;
  align-items: flex-start;
  margin-right: 0;
  padding: 10px 12px;
  border: 1px solid #dbe4f0;
  border-radius: 10px;
  background: #fff;
}

.permission-grid small {
  display: block;
  margin-top: 2px;
  color: #64748b;
  font-size: 12px;
}

@media (max-width: 960px) {
  .page-head {
    flex-direction: column;
  }

  .grid-two {
    grid-template-columns: 1fr;
  }

  .scope-row {
    flex-direction: column;
    align-items: stretch;
  }

  .permission-grid {
    grid-template-columns: 1fr;
  }
}
</style>
