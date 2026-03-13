<template>
  <AppShell>
    <div class="page-head">
      <div>
        <h2>{{ auth.isPlatformAdmin ? "公司与公司管理员" : "员工管理" }}</h2>
        <p>
          {{
            auth.isPlatformAdmin
              ? "平台管理员只负责创建公司和公司管理员。"
              : "公司管理员只负责维护本公司员工的手机号、权限和数据范围。"
          }}
        </p>
      </div>
      <div class="head-actions">
        <el-button v-if="auth.isPlatformAdmin" @click="openCreateTenant">新增公司</el-button>
        <el-button
          v-if="auth.isPlatformAdmin && selectedTenant"
          type="primary"
          @click="openCreateCompanyAdmin"
        >
          新增公司管理员
        </el-button>
        <el-button v-if="auth.isCompanyAdmin" type="primary" @click="openCreateEmployee">
          新增员工
        </el-button>
      </div>
    </div>

    <div class="layout" :class="{ compact: auth.isCompanyAdmin }">
      <aside v-if="auth.isPlatformAdmin" class="tenant-pane">
        <el-input v-model="tenantKeyword" clearable placeholder="搜索公司名称或编码" />
        <div class="tenant-list">
          <button
            v-for="tenant in filteredTenants"
            :key="tenant.code"
            type="button"
            class="tenant-item"
            :class="{ active: selectedTenantCode === tenant.code }"
            @click="selectedTenantCode = tenant.code"
          >
            <strong>{{ tenant.name }}</strong>
            <small>{{ tenant.code }}</small>
          </button>
          <div v-if="filteredTenants.length === 0" class="empty-block">暂无公司</div>
        </div>
      </aside>

      <section class="content-pane">
        <template v-if="selectedTenant">
          <div class="tenant-summary">
            <div>
              <h3>{{ selectedTenant.name }}</h3>
              <p>{{ selectedTenant.code }}</p>
            </div>
            <div class="summary-tags">
              <el-tag>{{ auth.isPlatformAdmin ? "平台视角" : "当前公司" }}</el-tag>
              <el-tag type="success">用户 {{ visibleUsers.length }}</el-tag>
            </div>
          </div>

          <el-table :data="visibleUsers" stripe>
            <el-table-column prop="phone" label="手机号" min-width="140" />
            <el-table-column prop="full_name" label="姓名" min-width="120" />
            <el-table-column label="核心角色" min-width="120">
              <template #default="{ row }">{{ coreRoleLabel(row.core_role) }}</template>
            </el-table-column>
            <el-table-column label="权限" min-width="220">
              <template #default="{ row }">{{ formatPermissions(row.permissions) }}</template>
            </el-table-column>
            <el-table-column label="数据范围" min-width="180">
              <template #default="{ row }">{{ formatScopes(row.data_scopes) }}</template>
            </el-table-column>
            <el-table-column label="账号状态" min-width="120">
              <template #default="{ row }">
                <el-tag :type="statusTag(row.status)">{{ statusLabel(row.status) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="最近登录" min-width="170">
              <template #default="{ row }">{{ formatDateTime(row.last_login_at) }}</template>
            </el-table-column>
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
        </template>

        <div v-else class="empty-state">
          <h3>{{ auth.isPlatformAdmin ? "先选择一个公司" : "当前账号未绑定公司" }}</h3>
          <p>{{ auth.isPlatformAdmin ? "创建公司后，再在公司下创建公司管理员。" : "请确认当前账号已正确归属公司。" }}</p>
        </div>
      </section>
    </div>

    <el-dialog v-model="tenantDialogVisible" title="新增公司" width="520px">
      <el-form label-width="88px">
        <el-form-item label="公司名称" required>
          <el-input v-model="tenantForm.name" placeholder="例如：A公司" />
        </el-form-item>
        <el-form-item label="公司编码" required>
          <el-input v-model="tenantForm.code" placeholder="例如：COMP-A" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="tenantDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="tenantSubmitting" @click="submitTenant">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="userDialogVisible" :title="dialogTitle" width="760px" destroy-on-close>
      <el-form label-width="96px">
        <div class="grid grid-two">
          <el-form-item label="所属公司">
            <el-input :model-value="selectedTenant ? `${selectedTenant.name}（${selectedTenant.code}）` : '-'" disabled />
          </el-form-item>
          <el-form-item label="核心角色">
            <el-input :model-value="coreRoleLabel(userForm.core_role)" disabled />
          </el-form-item>
        </div>

        <div class="grid grid-two">
          <el-form-item label="手机号" required>
            <el-input v-model="userForm.phone" maxlength="20" placeholder="请输入手机号" />
          </el-form-item>
          <el-form-item label="姓名">
            <el-input v-model="userForm.full_name" placeholder="请输入姓名" />
          </el-form-item>
        </div>

        <div class="grid grid-two">
          <el-form-item label="账号启用">
            <el-switch v-model="userForm.is_active" />
          </el-form-item>
          <el-form-item label="说明">
            <span class="form-tip">创建后员工使用手机号验证码首次激活登录</span>
          </el-form-item>
        </div>

        <div v-if="userForm.core_role === 'employee'" class="panel">
          <div class="panel-head">
            <div>
              <div class="panel-title">权限模板</div>
              <div class="panel-tip">先选模板，再按需微调权限点。</div>
            </div>
          </div>
          <el-form-item label="模板">
            <el-select v-model="userForm.template_key" clearable filterable style="width: 100%" @change="applyTemplate">
              <el-option v-for="item in employeeTemplates" :key="item.key" :label="item.label" :value="item.key" />
            </el-select>
          </el-form-item>
          <el-form-item label="权限点">
            <el-checkbox-group v-model="userForm.permission_keys" class="permission-grid">
              <el-checkbox v-for="item in employeePermissionOptions" :key="item.key" :value="item.key">
                <div>
                  <strong>{{ item.label }}</strong>
                  <small>{{ item.description }}</small>
                </div>
              </el-checkbox>
            </el-checkbox-group>
          </el-form-item>
        </div>

        <div v-if="userForm.core_role === 'employee'" class="panel">
          <div class="panel-head">
            <div>
              <div class="panel-title">数据范围</div>
              <div class="panel-tip">第一版仅支持本公司全部或指定站点。</div>
            </div>
          </div>
          <el-form-item label="授权方式">
            <el-radio-group v-model="userForm.scope_mode">
              <el-radio-button label="tenant">本公司全部</el-radio-button>
              <el-radio-button label="site">指定站点</el-radio-button>
            </el-radio-group>
          </el-form-item>
          <el-form-item v-if="userForm.scope_mode === 'site'" label="站点">
            <el-select
              v-model="userForm.site_codes"
              multiple
              filterable
              clearable
              style="width: 100%"
              placeholder="选择站点"
            >
              <el-option
                v-for="item in siteOptions"
                :key="item.code"
                :label="`${item.name}（${item.code}）`"
                :value="item.code"
              />
            </el-select>
          </el-form-item>
        </div>
      </el-form>
      <template #footer>
        <el-button @click="userDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="userSubmitting" @click="submitUser">保存</el-button>
      </template>
    </el-dialog>
  </AppShell>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import AppShell from "../components/AppShell.vue";
import http from "../api/http";
import { useAuthStore } from "../stores/auth";

const auth = useAuthStore();

const tenants = ref([]);
const users = ref([]);
const meta = ref({ permission_options: [], permission_templates: [], scope_type_options: [], core_role_options: [] });
const siteOptions = ref([]);
const tenantKeyword = ref("");
const selectedTenantCode = ref("");
const tenantDialogVisible = ref(false);
const tenantSubmitting = ref(false);
const userDialogVisible = ref(false);
const userSubmitting = ref(false);
const editingUserId = ref(null);

const tenantForm = reactive({ name: "", code: "" });
const userForm = reactive({
  core_role: "employee",
  phone: "",
  full_name: "",
  is_active: true,
  template_key: "",
  permission_keys: [],
  scope_mode: "tenant",
  site_codes: [],
});

const filteredTenants = computed(() => {
  const keyword = tenantKeyword.value.trim().toLowerCase();
  if (!keyword) return tenants.value;
  return tenants.value.filter((item) => `${item.name} ${item.code}`.toLowerCase().includes(keyword));
});

const selectedTenant = computed(() => tenants.value.find((item) => item.code === selectedTenantCode.value) || null);
const employeeTemplates = computed(() => meta.value.permission_templates || []);
const employeePermissionOptions = computed(() =>
  (meta.value.permission_options || []).filter((item) => item.key !== "user.manage_company")
);
const visibleUsers = computed(() => {
  if (!selectedTenant.value) return [];
  if (auth.isPlatformAdmin) {
    return users.value.filter((item) => item.tenant_code === selectedTenant.value.code && item.core_role === "company_admin");
  }
  return users.value.filter((item) => item.tenant_code === selectedTenant.value.code && item.core_role === "employee");
});
const dialogTitle = computed(() => {
  if (editingUserId.value) return "编辑账号";
  return userForm.core_role === "company_admin" ? "新增公司管理员" : "新增员工";
});

const templateMap = computed(() =>
  Object.fromEntries((employeeTemplates.value || []).map((item) => [item.key, item.permission_keys || []]))
);

const coreRoleLabel = (value) => {
  if (value === "platform_admin") return "平台管理员";
  if (value === "company_admin") return "公司管理员";
  return "普通员工";
};

const statusLabel = (value) => {
  if (value === "ACTIVE") return "已激活";
  if (value === "PENDING") return "待激活";
  if (value === "LOCKED") return "已锁定";
  if (value === "DISABLED") return "已停用";
  return value || "-";
};

const statusTag = (value) => {
  if (value === "ACTIVE") return "success";
  if (value === "PENDING") return "warning";
  if (value === "LOCKED") return "danger";
  return "info";
};

const formatPermissions = (permissions = []) => {
  if (!permissions.length) return "-";
  const map = Object.fromEntries((meta.value.permission_options || []).map((item) => [item.key, item.label]));
  return permissions.map((item) => map[item] || item).join("、");
};

const formatScopes = (scopes = []) => {
  if (!scopes.length) return "-";
  return scopes.map((item) => item.scope_name || item.scope_value).join("、");
};

const formatDateTime = (value) => {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  return date.toLocaleString();
};

const resetTenantForm = () => {
  tenantForm.name = "";
  tenantForm.code = "";
};

const resetUserForm = () => {
  editingUserId.value = null;
  userForm.core_role = auth.isPlatformAdmin ? "company_admin" : "employee";
  userForm.phone = "";
  userForm.full_name = "";
  userForm.is_active = true;
  userForm.template_key = "";
  userForm.permission_keys = [];
  userForm.scope_mode = "tenant";
  userForm.site_codes = [];
};

const applyTemplate = (templateKey) => {
  const keys = templateMap.value[templateKey] || [];
  userForm.permission_keys = [...keys];
};

const openCreateTenant = () => {
  resetTenantForm();
  tenantDialogVisible.value = true;
};

const openCreateCompanyAdmin = () => {
  resetUserForm();
  userForm.core_role = "company_admin";
  userDialogVisible.value = true;
};

const openCreateEmployee = () => {
  resetUserForm();
  userForm.core_role = "employee";
  userDialogVisible.value = true;
};

const openEdit = (row) => {
  resetUserForm();
  editingUserId.value = row.id;
  userForm.core_role = row.core_role || "employee";
  userForm.phone = row.phone || "";
  userForm.full_name = row.full_name || "";
  userForm.is_active = row.is_active !== false;
  userForm.template_key = row.template_key || "";
  userForm.permission_keys = [...(row.permissions || [])];
  const siteScopes = (row.data_scopes || []).filter((item) => item.scope_type === "site");
  userForm.scope_mode = siteScopes.length ? "site" : "tenant";
  userForm.site_codes = siteScopes.map((item) => item.scope_value);
  userDialogVisible.value = true;
};

const buildUserPayload = () => {
  if (!selectedTenant.value) throw new Error("请先选择公司");
  const phone = userForm.phone.trim();
  if (!phone) throw new Error("手机号不能为空");
  const payload = {
    username: phone,
    phone_country_code: "+86",
    phone,
    full_name: userForm.full_name.trim() || null,
    password: null,
    is_active: userForm.is_active,
    core_role: userForm.core_role,
    tenant_code: selectedTenant.value.code,
    template_key: userForm.core_role === "employee" ? userForm.template_key || null : null,
    permission_keys: userForm.core_role === "employee" ? [...new Set(userForm.permission_keys)] : [],
    data_scopes: [],
  };
  if (userForm.core_role === "employee") {
    if (userForm.scope_mode === "site") {
      if (!userForm.site_codes.length) throw new Error("请选择至少一个站点");
      payload.data_scopes = userForm.site_codes.map((code) => ({ scope_type: "site", scope_value: code }));
    } else {
      payload.data_scopes = [{ scope_type: "tenant", scope_value: selectedTenant.value.code }];
    }
  }
  return payload;
};

const loadMeta = async () => {
  const res = await http.get("/users/meta");
  meta.value = res.data || { permission_options: [], permission_templates: [], scope_type_options: [], core_role_options: [] };
};

const loadTenants = async () => {
  const res = await http.get("/tenants");
  tenants.value = Array.isArray(res.data) ? res.data : [];
  if (!selectedTenantCode.value && tenants.value.length) {
    selectedTenantCode.value = auth.isCompanyAdmin
      ? auth.tenantCodes[0] || tenants.value[0].code
      : tenants.value[0].code;
  }
};

const loadUsers = async () => {
  const res = await http.get("/users");
  users.value = Array.isArray(res.data) ? res.data : [];
};

const loadSites = async (tenantCode) => {
  if (!tenantCode || !auth.isCompanyAdmin) {
    siteOptions.value = [];
    return;
  }
  try {
    const res = await http.get(`/sites?tenant_code=${tenantCode}`);
    siteOptions.value = Array.isArray(res.data) ? res.data : [];
  } catch (_error) {
    siteOptions.value = [];
  }
};

const loadData = async () => {
  await Promise.all([loadMeta(), loadTenants(), loadUsers()]);
  if (selectedTenantCode.value) {
    await loadSites(selectedTenantCode.value);
  }
};

const submitTenant = async () => {
  try {
    const name = tenantForm.name.trim();
    const code = tenantForm.code.trim().toUpperCase();
    if (!name) throw new Error("公司名称不能为空");
    if (!code) throw new Error("公司编码不能为空");
    tenantSubmitting.value = true;
    await http.post("/tenants", { name, code });
    tenantDialogVisible.value = false;
    resetTenantForm();
    await loadTenants();
    selectedTenantCode.value = code;
    ElMessage.success("公司已创建");
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || error.message || "创建公司失败");
  } finally {
    tenantSubmitting.value = false;
  }
};

const submitUser = async () => {
  try {
    const payload = buildUserPayload();
    userSubmitting.value = true;
    if (editingUserId.value) {
      await http.put(`/users/${editingUserId.value}`, payload);
      ElMessage.success("账号已更新");
    } else {
      await http.post("/users", payload);
      ElMessage.success(userForm.core_role === "company_admin" ? "公司管理员已创建" : "员工已创建");
    }
    userDialogVisible.value = false;
    await loadUsers();
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || error.message || "保存账号失败");
  } finally {
    userSubmitting.value = false;
  }
};

const toggleActive = async (row) => {
  try {
    const dataScopes = Array.isArray(row.data_scopes) ? row.data_scopes : [];
    await http.put(`/users/${row.id}`, {
      username: row.username || row.phone,
      phone_country_code: row.phone_country_code || "+86",
      phone: row.phone,
      full_name: row.full_name,
      password: null,
      is_active: !row.is_active,
      core_role: row.core_role,
      tenant_code: row.tenant_code,
      permission_keys: row.permissions || [],
      data_scopes: dataScopes.map((item) => ({ scope_type: item.scope_type, scope_value: item.scope_value })),
    });
    ElMessage.success(`账号已${row.is_active ? "停用" : "启用"}`);
    await loadUsers();
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || "状态更新失败");
  }
};

const removeUser = async (row) => {
  try {
    await ElMessageBox.confirm(`确定删除账号 ${row.phone || row.username} 吗？`, "删除确认", { type: "warning" });
    await http.delete(`/users/${row.id}`);
    ElMessage.success("账号已删除");
    await loadUsers();
  } catch (error) {
    if (error === "cancel" || error === "close") return;
    ElMessage.error(error?.response?.data?.detail || "删除账号失败");
  }
};

watch(selectedTenantCode, async (tenantCode) => {
  await loadSites(tenantCode);
});

onMounted(() => {
  loadData().catch((error) => {
    ElMessage.error(error?.response?.data?.detail || "加载用户数据失败");
  });
});
</script>

<style scoped>
.page-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
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
.summary-tags {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.layout {
  display: grid;
  grid-template-columns: 280px 1fr;
  gap: 16px;
}

.layout.compact {
  grid-template-columns: 1fr;
}

.tenant-pane,
.content-pane {
  background: #fff;
  border: 1px solid #dbe4f0;
  border-radius: 16px;
  padding: 16px;
}

.tenant-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-top: 12px;
}

.tenant-item {
  text-align: left;
  border: 1px solid #dbe4f0;
  border-radius: 12px;
  padding: 12px;
  background: #f8fbff;
  cursor: pointer;
}

.tenant-item.active {
  border-color: #2563eb;
  background: #eff6ff;
}

.tenant-item strong {
  display: block;
  color: #0f172a;
}

.tenant-item small {
  color: #64748b;
}

.tenant-summary {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 16px;
}

.tenant-summary h3 {
  margin: 0;
  font-size: 22px;
}

.tenant-summary p {
  margin: 6px 0 0;
  color: #64748b;
}

.panel {
  margin-top: 12px;
  padding: 14px;
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
.form-tip {
  color: #64748b;
  font-size: 12px;
}

.grid {
  display: grid;
  gap: 12px;
}

.grid-two {
  grid-template-columns: repeat(2, minmax(0, 1fr));
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

.empty-state,
.empty-block {
  color: #94a3b8;
}

.empty-state {
  display: grid;
  place-items: center;
  min-height: 320px;
  text-align: center;
}

@media (max-width: 1080px) {
  .layout {
    grid-template-columns: 1fr;
  }

  .page-head,
  .tenant-summary {
    flex-direction: column;
    align-items: stretch;
  }

  .grid-two,
  .permission-grid {
    grid-template-columns: 1fr;
  }
}
</style>
