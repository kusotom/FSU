<template>
  <AppShell>
    <div class="bar">
      <h2>用户管理（管理员）</h2>
      <div class="actions">
        <el-button @click="openRoleManager">角色管理</el-button>
        <el-button type="primary" @click="openCreate">新建用户</el-button>
      </div>
    </div>

    <el-table :data="rows" stripe>
      <el-table-column prop="id" label="编号" width="70" />
      <el-table-column prop="username" label="用户名" />
      <el-table-column prop="full_name" label="姓名" />
      <el-table-column prop="roles" label="角色">
        <template #default="{ row }">{{ formatRoles(row.roles) }}</template>
      </el-table-column>
      <el-table-column label="租户角色" min-width="260">
        <template #default="{ row }">{{ formatTenantRoles(row.tenant_roles) }}</template>
      </el-table-column>
      <el-table-column prop="created_at" label="创建时间" />
    </el-table>

    <el-dialog v-model="dialogVisible" title="新建用户" width="760px" destroy-on-close>
      <el-alert
        v-if="formErrorSummary.length"
        type="error"
        :closable="false"
        class="form-error-summary"
      >
        <template #title>请先修正以下问题：</template>
        <template #default>
          <ul class="form-error-list">
            <li v-for="(item, idx) in formErrorSummary" :key="idx">{{ item }}</li>
          </ul>
        </template>
      </el-alert>

      <el-form
        ref="formRef"
        :model="form"
        :rules="formRules"
        label-width="90px"
        status-icon
        :validate-on-rule-change="false"
        scroll-to-error
      >
        <el-form-item label="用户名" prop="username">
          <el-input v-model="form.username" placeholder="例如：ops_zhangsan" />
        </el-form-item>
        <el-form-item label="姓名" prop="full_name"><el-input v-model="form.full_name" /></el-form-item>
        <el-form-item label="密码" prop="password">
          <el-input v-model="form.password" type="password" show-password placeholder="至少6位" />
        </el-form-item>
        <el-form-item label="角色" prop="role_names">
          <el-select
            v-model="form.role_names"
            multiple
            filterable
            style="width: 100%"
            placeholder="选择已有角色"
          >
            <el-option
              v-for="role in roleOptions"
              :key="role"
              :label="roleLabel(role)"
              :value="role"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="租户角色">
          <div class="binding-wrap">
            <div class="binding-actions">
              <el-button size="small" @click="addBinding">添加绑定</el-button>
              <span class="binding-tip">支持为同一用户绑定多个公司/租户角色</span>
            </div>
            <div v-for="(binding, idx) in form.tenant_roles" :key="idx" class="binding-item">
              <div class="binding-row">
                <el-select
                  v-model="binding.tenant_code"
                  clearable
                  filterable
                  @change="onBindingTenantChange(binding)"
                  placeholder="选择租户"
                  style="width: 46%"
                >
                  <el-option
                    v-for="item in tenants"
                    :key="item.code"
                    :label="`${item.name} (${item.code})`"
                    :value="item.code"
                    :disabled="isTenantDisabledForRole(item.code, binding.role_name)"
                  />
                </el-select>
                <el-select
                  v-model="binding.role_name"
                  clearable
                  filterable
                  @change="onBindingRoleChange(binding)"
                  placeholder="选择角色"
                  style="width: 46%"
                >
                  <el-option
                    v-for="role in roleOptions"
                    :key="`binding-${idx}-${role}`"
                    :label="roleLabel(role)"
                    :value="role"
                    :disabled="isRoleDisabledForTenant(role, binding.tenant_code)"
                  />
                </el-select>
                <el-button
                  text
                  type="danger"
                  :disabled="form.tenant_roles.length === 1"
                  @click="removeBinding(idx)"
                >
                  删除
                </el-button>
              </div>
              <div v-if="getBindingHint(binding)" class="binding-warning">{{ getBindingHint(binding) }}</div>
            </div>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitLoading" @click="createUser">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="roleDialogVisible" title="角色管理" width="760px">
      <div class="role-bar">
        <el-button type="primary" @click="openRoleCreate">新增角色</el-button>
      </div>
      <el-table :data="roleDefs" stripe>
        <el-table-column prop="name" label="角色标识" min-width="180" />
        <el-table-column prop="description" label="角色说明" min-width="220" />
        <el-table-column label="类型" width="100">
          <template #default="{ row }">{{ row.is_builtin ? "内置" : "自定义" }}</template>
        </el-table-column>
        <el-table-column label="操作" width="180">
          <template #default="{ row }">
            <el-button size="small" @click="openRoleEdit(row)">编辑</el-button>
            <el-button
              size="small"
              type="danger"
              :disabled="row.is_builtin"
              @click="deleteRole(row)"
            >
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>

    <el-dialog v-model="roleEditVisible" :title="roleEditingId ? '编辑角色' : '新增角色'" width="460px">
      <el-form :model="roleForm" label-width="90px">
        <el-form-item label="角色标识">
          <el-input
            v-model="roleForm.name"
            :disabled="roleForm.is_builtin"
            placeholder="例如：maintainer"
          />
          <div class="role-tip">仅支持小写字母/数字/下划线，以字母开头，2-64位</div>
        </el-form-item>
        <el-form-item label="角色说明">
          <el-input v-model="roleForm.description" placeholder="例如：区域运维负责人" />
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
import { onMounted, reactive, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import AppShell from "../components/AppShell.vue";
import http from "../api/http";

const HQ_TENANT_CODE = "HQ-GROUP";
const GLOBAL_ROLE_NAMES = new Set(["admin", "hq_noc"]);

const rows = ref([]);
const tenants = ref([]);
const roleDefs = ref([]);
const roleOptions = ref(["admin", "operator", "hq_noc", "sub_noc"]);
const dialogVisible = ref(false);
const submitLoading = ref(false);
const formRef = ref();
const formErrorSummary = ref([]);
const roleDialogVisible = ref(false);
const roleEditVisible = ref(false);
const roleEditingId = ref(null);

const roleLabelMap = {
  admin: "管理员",
  operator: "运维",
  hq_noc: "总部监控组",
  sub_noc: "子公司监控组",
};

const roleForm = reactive({
  name: "",
  description: "",
  is_builtin: false,
});

const createBinding = () => ({
  tenant_code: "",
  role_name: "",
});

const form = reactive({
  username: "",
  full_name: "",
  password: "",
  role_names: [],
  tenant_roles: [createBinding()],
});

const formRules = {
  username: [
    { required: true, message: "请输入用户名", trigger: "blur" },
    {
      min: 3,
      max: 64,
      message: "用户名长度需在 3-64 位之间",
      trigger: "blur",
    },
  ],
  password: [
    { required: true, message: "请输入密码", trigger: "blur" },
    {
      min: 6,
      max: 128,
      message: "密码长度需在 6-128 位之间",
      trigger: "blur",
    },
  ],
  role_names: [
    {
      validator: (_rule, value, callback) => {
        const hasDirectRoles = Array.isArray(value) && value.length > 0;
        const hasTenantRoles = form.tenant_roles.some((item) => {
          const tenantCode = String(item.tenant_code || "").trim();
          const roleName = String(item.role_name || "").trim();
          return tenantCode && roleName;
        });
        if (!hasDirectRoles && !hasTenantRoles) {
          callback(new Error("请至少选择一个角色"));
          return;
        }
        callback();
      },
      trigger: "change",
    },
  ],
};

const roleLabel = (role) => roleLabelMap[role] || role;

const formatRoles = (roles) => (roles || []).map((role) => roleLabel(role)).join("、");

const formatTenantRoles = (items) => {
  if (!Array.isArray(items) || items.length === 0) return "-";
  return items
    .map((item) => {
      const role = formatRoles([item.role_name]) || item.role_name;
      return `${item.tenant_name}(${item.tenant_code})/${role}`;
    })
    .join("；");
};

const syncRoleOptions = () => {
  const names = roleDefs.value.map((item) => item.name).filter(Boolean);
  roleOptions.value = Array.from(new Set(["admin", "operator", "hq_noc", "sub_noc", ...names])).sort();
};

const loadRoleDefs = async () => {
  const res = await http.get("/users/role-defs");
  roleDefs.value = Array.isArray(res.data) ? res.data : [];
  syncRoleOptions();
};

const loadData = async () => {
  try {
    const [userRes, tenantRes] = await Promise.all([http.get("/users"), http.get("/tenants")]);
    rows.value = userRes.data;
    tenants.value = tenantRes.data;
    await loadRoleDefs();
  } catch (_e) {
    ElMessage.error("需要管理员权限");
  }
};

const addBinding = () => {
  form.tenant_roles.push(createBinding());
};

const removeBinding = (idx) => {
  if (form.tenant_roles.length === 1) {
    form.tenant_roles[0].tenant_code = "";
    form.tenant_roles[0].role_name = "";
    return;
  }
  form.tenant_roles.splice(idx, 1);
};

const isRoleDisabledForTenant = (roleName, tenantCode) => {
  if (!roleName || !tenantCode) return false;
  if ((roleName === "admin" || roleName === "hq_noc") && tenantCode !== HQ_TENANT_CODE) return true;
  if (roleName === "sub_noc" && tenantCode === HQ_TENANT_CODE) return true;
  return false;
};

const isTenantDisabledForRole = (tenantCode, roleName) => {
  if (!tenantCode || !roleName) return false;
  if ((roleName === "admin" || roleName === "hq_noc") && tenantCode !== HQ_TENANT_CODE) return true;
  if (roleName === "sub_noc" && tenantCode === HQ_TENANT_CODE) return true;
  return false;
};

const getBindingHint = (binding) => {
  const roleName = String(binding.role_name || "").trim();
  const tenantCode = String(binding.tenant_code || "").trim();
  if (!roleName || !tenantCode) return "";
  if ((roleName === "admin" || roleName === "hq_noc") && tenantCode !== HQ_TENANT_CODE) {
    return `角色 ${roleName} 仅允许绑定到 ${HQ_TENANT_CODE}`;
  }
  if (roleName === "sub_noc" && tenantCode === HQ_TENANT_CODE) {
    return "角色 sub_noc 不能绑定到总部租户";
  }
  return "";
};

const onBindingRoleChange = (binding) => {
  if (!binding.role_name || !binding.tenant_code) return;
  if (isTenantDisabledForRole(binding.tenant_code, binding.role_name)) {
    binding.tenant_code = "";
  }
};

const onBindingTenantChange = (binding) => {
  if (!binding.role_name || !binding.tenant_code) return;
  if (isRoleDisabledForTenant(binding.role_name, binding.tenant_code)) {
    binding.role_name = "";
  }
};

const validateTenantRoles = (tenantRoles) => {
  const errors = [];
  const pairSet = new Set();
  form.tenant_roles.forEach((item, idx) => {
    const tenantCode = String(item.tenant_code || "").trim();
    const roleName = String(item.role_name || "").trim();
    if ((tenantCode && !roleName) || (!tenantCode && roleName)) {
      errors.push(`租户角色第 ${idx + 1} 行需同时选择租户和角色`);
    }
  });
  tenantRoles.forEach((item) => {
    const pairKey = `${item.tenant_code}::${item.role_name}`;
    if (pairSet.has(pairKey)) {
      errors.push(`存在重复绑定：${item.tenant_code}/${item.role_name}`);
    }
    pairSet.add(pairKey);
    if ((item.role_name === "admin" || item.role_name === "hq_noc") && item.tenant_code !== HQ_TENANT_CODE) {
      errors.push(`角色 ${item.role_name} 仅允许绑定到 ${HQ_TENANT_CODE}`);
    }
    if (item.role_name === "sub_noc" && item.tenant_code === HQ_TENANT_CODE) {
      errors.push("角色 sub_noc 不能绑定到总部租户");
    }
  });
  return errors;
};

const resetForm = () => {
  form.username = "";
  form.full_name = "";
  form.password = "";
  form.role_names = [];
  form.tenant_roles = [createBinding()];
  formErrorSummary.value = [];
};

const openCreate = () => {
  resetForm();
  dialogVisible.value = true;
};

const createUser = async () => {
  formErrorSummary.value = [];
  const validated = await formRef.value?.validate().catch(() => false);
  if (!validated) {
    formErrorSummary.value = ["请检查用户名、密码和角色必填项"];
    return;
  }

  const tenantRoles = form.tenant_roles
    .map((item) => ({
      tenant_code: String(item.tenant_code || "").trim(),
      role_name: String(item.role_name || "").trim(),
    }))
    .filter((item) => item.tenant_code && item.role_name);

  const roleSet = new Set([
    ...(form.role_names || []).map((item) => String(item || "").trim()).filter(Boolean),
    ...tenantRoles.map((item) => item.role_name),
  ]);
  if (roleSet.size === 0) {
    formErrorSummary.value = ["请至少添加一个角色"];
    return;
  }

  const invalidRoleNames = Array.from(roleSet).filter((item) => !roleOptions.value.includes(item));
  if (invalidRoleNames.length > 0) {
    formErrorSummary.value = [`存在未定义角色：${invalidRoleNames.join("、")}，请先在角色管理中创建`];
    return;
  }

  const hasNonGlobalRole = Array.from(roleSet).some((item) => !GLOBAL_ROLE_NAMES.has(item));
  if (hasNonGlobalRole && tenantRoles.length === 0) {
    formErrorSummary.value = ["非总部角色必须绑定至少一个租户（公司）"];
    ElMessage.warning("请先绑定租户角色");
    return;
  }

  const tenantRoleErrors = validateTenantRoles(tenantRoles);
  if (tenantRoleErrors.length > 0) {
    formErrorSummary.value = tenantRoleErrors;
    ElMessage.warning("请先修正租户角色配置");
    return;
  }

  const payload = {
    username: form.username.trim(),
    full_name: String(form.full_name || "").trim() || null,
    password: form.password,
    role_names: Array.from(roleSet),
    tenant_roles: tenantRoles,
  };

  try {
    submitLoading.value = true;
    await http.post("/users", payload);
    ElMessage.success("创建成功");
    dialogVisible.value = false;
    resetForm();
    await loadData();
  } catch (e) {
    const msg = e?.response?.data?.detail || "创建失败";
    ElMessage.error(msg);
  } finally {
    submitLoading.value = false;
  }
};

const resetRoleForm = () => {
  roleForm.name = "";
  roleForm.description = "";
  roleForm.is_builtin = false;
  roleEditingId.value = null;
};

const openRoleManager = async () => {
  try {
    await loadRoleDefs();
    roleDialogVisible.value = true;
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || "加载角色失败");
  }
};

const openRoleCreate = () => {
  resetRoleForm();
  roleEditVisible.value = true;
};

const openRoleEdit = (row) => {
  roleEditingId.value = row.id;
  roleForm.name = row.name || "";
  roleForm.description = row.description || "";
  roleForm.is_builtin = Boolean(row.is_builtin);
  roleEditVisible.value = true;
};

const submitRole = async () => {
  const roleName = String(roleForm.name || "").trim();
  if (!roleName) {
    ElMessage.warning("请输入角色标识");
    return;
  }
  if (!/^[a-z][a-z0-9_]{1,63}$/.test(roleName)) {
    ElMessage.warning("角色标识仅支持小写字母/数字/下划线，且以字母开头（2-64位）");
    return;
  }
  const payload = {
    name: roleName,
    description: String(roleForm.description || "").trim() || null,
  };
  try {
    if (roleEditingId.value) {
      await http.put(`/users/role-defs/${roleEditingId.value}`, payload);
      ElMessage.success("角色已更新");
    } else {
      await http.post("/users/role-defs", payload);
      ElMessage.success("角色已创建");
    }
    roleEditVisible.value = false;
    await loadRoleDefs();
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || "保存角色失败");
  }
};

const deleteRole = async (row) => {
  try {
    await ElMessageBox.confirm(
      `确定删除角色 ${row.name} 吗？删除后不可恢复。`,
      "删除角色确认",
      {
        type: "warning",
        confirmButtonText: "删除",
        cancelButtonText: "取消",
      },
    );
  } catch (_e) {
    return;
  }

  try {
    await http.delete(`/users/role-defs/${row.id}`);
    ElMessage.success("角色已删除");
    await loadRoleDefs();
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || "删除角色失败");
  }
};

onMounted(loadData);
</script>

<style scoped>
.bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

h2 {
  margin: 0;
}

.binding-wrap {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.binding-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.binding-tip {
  color: #64748b;
  font-size: 12px;
}

.binding-warning {
  color: #dc2626;
  font-size: 12px;
  margin-top: 4px;
}

.binding-item {
  display: flex;
  flex-direction: column;
}

.binding-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.role-bar {
  margin-bottom: 10px;
}

.role-tip {
  margin-top: 4px;
  color: #64748b;
  font-size: 12px;
}

.form-error-summary {
  margin-bottom: 12px;
}

.form-error-list {
  margin: 0;
  padding-left: 18px;
}
</style>
