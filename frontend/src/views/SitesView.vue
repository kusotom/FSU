<template>
  <AppShell>
    <div class="bar">
      <h2>站点管理</h2>
      <div class="actions">
        <el-button @click="loadData">刷新</el-button>
        <el-button v-if="canCreate" type="primary" @click="openCreate">新建站点</el-button>
      </div>
    </div>

    <div class="filters">
      <el-input v-model="keyword" clearable placeholder="搜索站点编码/名称/区域" style="width: 320px" />
      <el-select v-model="tenantFilter" clearable filterable placeholder="筛选租户" style="width: 220px">
        <el-option
          v-for="item in tenants"
          :key="item.code"
          :label="`${item.name} (${item.code})`"
          :value="item.code"
        />
      </el-select>
    </div>

    <el-table :data="filteredRows" stripe>
      <el-table-column prop="id" label="编号" width="80" />
      <el-table-column prop="code" label="站点编码" min-width="150" />
      <el-table-column prop="name" label="站点名称" min-width="200" />
      <el-table-column prop="region" label="区域" min-width="120" />
      <el-table-column prop="tenant_code" label="租户" width="140" />
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="row.is_active ? 'success' : 'info'">
            {{ row.is_active ? "启用" : "停用" }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="创建时间" min-width="180">
        <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
      </el-table-column>
      <el-table-column v-if="canUpdate" label="操作" width="120">
        <template #default="{ row }">
          <el-button size="small" @click="openEdit(row)">编辑</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialogVisible" :title="editingId ? '编辑站点' : '新建站点'" width="560px">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="90px" status-icon>
        <el-form-item label="站点编码" prop="code">
          <el-input v-model="form.code" placeholder="例如：SITE-A-001" />
        </el-form-item>
        <el-form-item label="站点名称" prop="name">
          <el-input v-model="form.name" placeholder="例如：A公司-北京机房1" />
        </el-form-item>
        <el-form-item label="区域" prop="region">
          <el-input v-model="form.region" placeholder="例如：华北" />
        </el-form-item>
        <el-form-item label="租户" prop="tenant_code">
          <el-select v-model="form.tenant_code" filterable clearable placeholder="请选择租户" style="width: 100%">
            <el-option
              v-for="item in tenants"
              :key="item.code"
              :label="`${item.name} (${item.code})`"
              :value="item.code"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="启用状态" prop="is_active">
          <el-switch v-model="form.is_active" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submitSite">保存</el-button>
      </template>
    </el-dialog>
  </AppShell>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from "vue";
import { ElMessage } from "element-plus";
import AppShell from "../components/AppShell.vue";
import http from "../api/http";
import { useAuthStore } from "../stores/auth";

const auth = useAuthStore();
const canCreate = computed(() => auth.hasPermission("site.create"));
const canUpdate = computed(() => auth.hasPermission("site.update"));

const rows = ref([]);
const tenants = ref([]);
const keyword = ref("");
const tenantFilter = ref("");
const dialogVisible = ref(false);
const saving = ref(false);
const editingId = ref(null);
const formRef = ref();

const form = reactive({
  code: "",
  name: "",
  region: "",
  tenant_code: "",
  is_active: true,
});

const rules = {
  code: [
    { required: true, message: "请输入站点编码", trigger: "blur" },
    { min: 2, max: 64, message: "站点编码长度需在 2-64 位", trigger: "blur" },
  ],
  name: [{ required: true, message: "请输入站点名称", trigger: "blur" }],
  tenant_code: [{ required: true, message: "请选择租户", trigger: "change" }],
};

const formatTime = (value) => {
  if (!value) return "-";
  const dt = new Date(value);
  if (Number.isNaN(dt.getTime())) return String(value);
  return dt.toLocaleString("zh-CN", { hour12: false });
};

const filteredRows = computed(() => {
  const q = keyword.value.trim().toLowerCase();
  const t = String(tenantFilter.value || "").trim();
  return rows.value.filter((item) => {
    if (t && item.tenant_code !== t) return false;
    if (!q) return true;
    const bucket = [item.code, item.name, item.region, item.tenant_code]
      .map((x) => String(x || "").toLowerCase())
      .join("|");
    return bucket.includes(q);
  });
});

const loadTenants = async () => {
  const res = await http.get("/tenants");
  tenants.value = Array.isArray(res.data) ? res.data : [];
};

const loadSites = async () => {
  const res = await http.get("/sites");
  rows.value = Array.isArray(res.data) ? res.data : [];
};

const loadData = async () => {
  try {
    await Promise.all([loadSites(), loadTenants()]);
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || "加载站点数据失败");
  }
};

const resetForm = () => {
  editingId.value = null;
  form.code = "";
  form.name = "";
  form.region = "";
  form.tenant_code = tenants.value.length === 1 ? tenants.value[0].code : "";
  form.is_active = true;
};

const openCreate = () => {
  if (!canCreate.value) {
    ElMessage.error("无权创建站点");
    return;
  }
  resetForm();
  dialogVisible.value = true;
};

const openEdit = (row) => {
  if (!canUpdate.value) {
    ElMessage.error("无权编辑站点");
    return;
  }
  editingId.value = row.id;
  form.code = row.code || "";
  form.name = row.name || "";
  form.region = row.region || "";
  form.tenant_code = row.tenant_code || "";
  form.is_active = Boolean(row.is_active);
  dialogVisible.value = true;
};

const submitSite = async () => {
  if (editingId.value && !canUpdate.value) {
    ElMessage.error("无权编辑站点");
    return;
  }
  if (!editingId.value && !canCreate.value) {
    ElMessage.error("无权创建站点");
    return;
  }
  const ok = await formRef.value?.validate().catch(() => false);
  if (!ok) return;

  const payload = {
    code: String(form.code || "").trim(),
    name: String(form.name || "").trim(),
    region: String(form.region || "").trim() || null,
    tenant_code: String(form.tenant_code || "").trim(),
    is_active: Boolean(form.is_active),
  };

  try {
    saving.value = true;
    if (editingId.value) {
      await http.put(`/sites/${editingId.value}`, payload);
      ElMessage.success("站点已更新");
    } else {
      await http.post("/sites", payload);
      ElMessage.success("站点创建成功");
    }
    dialogVisible.value = false;
    await loadSites();
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || "站点保存失败");
  } finally {
    saving.value = false;
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

h2 {
  margin: 0;
}

.actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.filters {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}
</style>
