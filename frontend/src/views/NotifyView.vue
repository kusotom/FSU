<template>
  <AppShell>
    <div class="bar">
      <h2>通知策略（管理员）</h2>
    </div>

    <el-row :gutter="16">
      <el-col :xs="24" :md="12">
        <el-card>
          <template #header>
            <div class="card-title">
              <span>通知通道</span>
              <div class="actions">
                <el-button v-if="editingChannelId" size="small" @click="resetChannelForm">取消</el-button>
                <el-button size="small" type="primary" @click="submitChannel">
                  {{ editingChannelId ? "保存" : "新增" }}
                </el-button>
              </div>
            </div>
          </template>
          <el-form :model="channelForm" label-width="92px" class="inline-form">
            <el-form-item label="名称">
              <el-input v-model="channelForm.name" placeholder="例如：主群机器人" />
            </el-form-item>
            <el-form-item label="类型">
              <el-select v-model="channelForm.channel_type" style="width: 100%">
                <el-option label="企业微信机器人" value="wechat_robot" />
                <el-option label="腾讯云短信" value="sms_tencent" />
                <el-option label="通用回调" value="webhook" />
              </el-select>
            </el-form-item>
            <el-form-item label="地址">
              <el-input v-model="channelForm.endpoint" :placeholder="endpointPlaceholder" />
            </el-form-item>
            <el-form-item label="测试消息">
              <el-input v-model="channelTestContent" placeholder="留空则使用默认测试文案" />
            </el-form-item>
            <el-alert
              v-if="channelForm.channel_type === 'wechat_robot'"
              type="info"
              :closable="false"
              show-icon
              title="企业微信机器人地址示例：https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxxx"
            />
            <el-alert
              v-if="channelForm.channel_type === 'sms_tencent'"
              type="warning"
              :closable="false"
              show-icon
              title="腾讯云短信地址填写手机号，多个号码用逗号分隔，例如：+8613800138000,+8613900139000"
            />
          </el-form>

          <el-table :data="channels" size="small" stripe>
            <el-table-column prop="id" label="编号" width="70" />
            <el-table-column prop="name" label="名称" />
            <el-table-column label="类型" width="130">
              <template #default="{ row }">{{ channelTypeLabel(row.channel_type) }}</template>
            </el-table-column>
            <el-table-column prop="is_enabled" label="启用" width="90">
              <template #default="{ row }">{{ row.is_enabled ? "是" : "否" }}</template>
            </el-table-column>
            <el-table-column label="操作" width="110">
              <template #default="{ row }">
                <div class="row-actions">
                  <el-button size="small" text @click="editChannel(row)">编辑</el-button>
                  <el-button size="small" text @click="toggleChannel(row)">
                    {{ row.is_enabled ? "停用" : "启用" }}
                  </el-button>
                  <el-button size="small" text :loading="testingChannelId === row.id" @click="testChannel(row)">
                    测试
                  </el-button>
                  <el-button size="small" text type="danger" @click="removeChannel(row)">删除</el-button>
                </div>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>

      <el-col :xs="24" :md="12">
        <el-card>
          <template #header>
            <div class="card-title">
              <span>通知策略</span>
              <div class="actions">
                <el-button v-if="editingPolicyId" size="small" @click="resetPolicyForm">取消</el-button>
                <el-button size="small" type="primary" @click="submitPolicy">
                  {{ editingPolicyId ? "保存" : "新增" }}
                </el-button>
              </div>
            </div>
          </template>
          <el-form :model="policyForm" label-width="92px" class="inline-form">
            <el-form-item label="策略名称">
              <el-input v-model="policyForm.name" placeholder="例如：一级告警策略" />
            </el-form-item>
            <el-form-item label="通知通道">
              <el-select v-model="policyForm.channel_id" style="width: 100%">
                <el-option
                  v-for="item in channels"
                  :key="item.id"
                  :label="`${item.name} (${channelTypeLabel(item.channel_type)})`"
                  :value="item.id"
                />
              </el-select>
            </el-form-item>
            <el-form-item label="最小级别">
              <el-input-number v-model="policyForm.min_alarm_level" :min="1" :max="4" />
            </el-form-item>
            <el-form-item label="事件类型">
              <el-checkbox-group v-model="policyForm.event_type_list">
                <el-checkbox-button
                  v-for="item in eventTypeOptions"
                  :key="item.value"
                  :label="item.value"
                >
                  {{ item.label }}
                </el-checkbox-button>
              </el-checkbox-group>
            </el-form-item>
          </el-form>

          <el-table :data="policies" size="small" stripe>
            <el-table-column prop="id" label="编号" width="70" />
            <el-table-column prop="name" label="策略名称" />
            <el-table-column prop="channel_id" label="通道编号" width="90" />
            <el-table-column label="级别" width="80">
              <template #default="{ row }">{{ row.min_alarm_level }}级</template>
            </el-table-column>
            <el-table-column label="事件">
              <template #default="{ row }">{{ eventTypesLabel(row.event_types) }}</template>
            </el-table-column>
            <el-table-column prop="is_enabled" label="启用" width="80">
              <template #default="{ row }">{{ row.is_enabled ? "是" : "否" }}</template>
            </el-table-column>
            <el-table-column label="操作" width="140">
              <template #default="{ row }">
                <div class="row-actions">
                  <el-button size="small" text @click="editPolicy(row)">编辑</el-button>
                  <el-button size="small" text @click="togglePolicy(row)">
                    {{ row.is_enabled ? "停用" : "启用" }}
                  </el-button>
                  <el-button size="small" text type="danger" @click="removePolicy(row)">删除</el-button>
                </div>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>
    </el-row>
  </AppShell>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import AppShell from "../components/AppShell.vue";
import http from "../api/http";

const channels = ref([]);
const policies = ref([]);
const testingChannelId = ref(null);
const channelTestContent = ref("");
const editingChannelId = ref(null);
const editingPolicyId = ref(null);

const channelForm = reactive({
  name: "",
  channel_type: "wechat_robot",
  endpoint: "",
  secret: "",
  is_enabled: true,
});

const policyForm = reactive({
  name: "",
  channel_id: null,
  min_alarm_level: 2,
  event_type_list: ["trigger", "recover"],
  is_enabled: true,
});

const eventTypeOptions = [
  { label: "触发", value: "trigger" },
  { label: "恢复", value: "recover" },
  { label: "确认", value: "ack" },
  { label: "关闭", value: "close" },
];

const eventTypeLabelMap = {
  trigger: "触发",
  recover: "恢复",
  ack: "确认",
  close: "关闭",
};

const endpointPlaceholder = computed(() =>
  channelForm.channel_type === "wechat_robot"
    ? "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=..."
    : channelForm.channel_type === "sms_tencent"
      ? "+8613800138000,+8613900139000"
      : "https://..."
);

const channelTypeLabel = (type) => {
  if (type === "wechat_robot") return "企业微信机器人";
  if (type === "sms_tencent") return "腾讯云短信";
  if (type === "webhook") return "通用回调";
  return "未知";
};

const eventTypesLabel = (raw) => {
  const list = Array.isArray(raw)
    ? raw
    : String(raw || "")
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);
  if (list.length === 0) return "-";
  return list.map((item) => eventTypeLabelMap[item] || item).join("、");
};

const loadData = async () => {
  const [channelRes, policyRes] = await Promise.all([
    http.get("/notify/channels"),
    http.get("/notify/policies"),
  ]);
  channels.value = channelRes.data;
  policies.value = policyRes.data;
};

const resetChannelForm = () => {
  editingChannelId.value = null;
  channelForm.name = "";
  channelForm.channel_type = "wechat_robot";
  channelForm.endpoint = "";
  channelForm.secret = "";
  channelForm.is_enabled = true;
};

const resetPolicyForm = () => {
  editingPolicyId.value = null;
  policyForm.name = "";
  policyForm.channel_id = null;
  policyForm.min_alarm_level = 2;
  policyForm.event_type_list = ["trigger", "recover"];
  policyForm.is_enabled = true;
};

const submitChannel = async () => {
  if (!channelForm.name || !channelForm.endpoint) {
    ElMessage.warning("请填写通道名称和地址");
    return;
  }
  if (channelForm.channel_type === "wechat_robot") {
    const endpoint = String(channelForm.endpoint || "");
    if (
      !endpoint.startsWith("https://qyapi.weixin.qq.com/cgi-bin/webhook/send") ||
      !endpoint.includes("key=")
    ) {
      ElMessage.warning("企业微信机器人地址格式不正确");
      return;
    }
  }
  if (channelForm.channel_type === "sms_tencent") {
    const phones = String(channelForm.endpoint || "")
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    if (!phones.length) {
      ElMessage.warning("请填写至少一个手机号");
      return;
    }
    const invalid = phones.filter((s) => !/^\+?\d{6,20}$/.test(s.replace(/\s|-/g, "")));
    if (invalid.length) {
      ElMessage.warning("手机号格式不正确，请检查");
      return;
    }
  }
  try {
    if (editingChannelId.value) {
      await http.put(`/notify/channels/${editingChannelId.value}`, channelForm);
      ElMessage.success("通道保存成功");
    } else {
      await http.post("/notify/channels", channelForm);
      ElMessage.success("通道创建成功");
    }
    resetChannelForm();
    await loadData();
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || "通道创建失败");
  }
};

const submitPolicy = async () => {
  if (!policyForm.name || !policyForm.channel_id) {
    ElMessage.warning("请填写策略名称并选择通知通道");
    return;
  }
  if (!policyForm.event_type_list.length) {
    ElMessage.warning("请至少选择一种事件类型");
    return;
  }
  try {
    const payload = {
      name: policyForm.name,
      channel_id: policyForm.channel_id,
      min_alarm_level: policyForm.min_alarm_level,
      event_types: policyForm.event_type_list.join(","),
      is_enabled: policyForm.is_enabled,
    };
    if (editingPolicyId.value) {
      await http.put(`/notify/policies/${editingPolicyId.value}`, payload);
      ElMessage.success("策略保存成功");
    } else {
      await http.post("/notify/policies", payload);
      ElMessage.success("策略创建成功");
    }
    resetPolicyForm();
    await loadData();
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || "策略创建失败");
  }
};

const editChannel = (row) => {
  editingChannelId.value = row.id;
  channelForm.name = row.name;
  channelForm.channel_type = row.channel_type;
  channelForm.endpoint = row.endpoint;
  channelForm.secret = row.secret || "";
  channelForm.is_enabled = row.is_enabled;
};

const editPolicy = (row) => {
  editingPolicyId.value = row.id;
  policyForm.name = row.name;
  policyForm.channel_id = row.channel_id;
  policyForm.min_alarm_level = row.min_alarm_level;
  policyForm.event_type_list = String(row.event_types || "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
  policyForm.is_enabled = row.is_enabled;
};

const toggleChannel = async (row) => {
  try {
    await http.put(`/notify/channels/${row.id}`, {
      name: row.name,
      channel_type: row.channel_type,
      endpoint: row.endpoint,
      secret: row.secret || "",
      is_enabled: !row.is_enabled,
    });
    ElMessage.success(`通道已${row.is_enabled ? "停用" : "启用"}`);
    await loadData();
    if (editingChannelId.value === row.id) editChannel({ ...row, is_enabled: !row.is_enabled });
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || "通道状态更新失败");
  }
};

const togglePolicy = async (row) => {
  try {
    await http.put(`/notify/policies/${row.id}`, {
      name: row.name,
      channel_id: row.channel_id,
      min_alarm_level: row.min_alarm_level,
      event_types: row.event_types,
      is_enabled: !row.is_enabled,
    });
    ElMessage.success(`策略已${row.is_enabled ? "停用" : "启用"}`);
    await loadData();
    if (editingPolicyId.value === row.id) editPolicy({ ...row, is_enabled: !row.is_enabled });
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || "策略状态更新失败");
  }
};

const removeChannel = async (row) => {
  try {
    await ElMessageBox.confirm(`确认删除通知通道“${row.name}”吗？`, "删除确认", { type: "warning" });
    await http.delete(`/notify/channels/${row.id}`);
    ElMessage.success("通道已删除");
    if (editingChannelId.value === row.id) resetChannelForm();
    await loadData();
  } catch (e) {
    if (e === "cancel" || e === "close") return;
    ElMessage.error(e?.response?.data?.detail || "通道删除失败");
  }
};

const removePolicy = async (row) => {
  try {
    await ElMessageBox.confirm(`确认删除通知策略“${row.name}”吗？`, "删除确认", { type: "warning" });
    await http.delete(`/notify/policies/${row.id}`);
    ElMessage.success("策略已删除");
    if (editingPolicyId.value === row.id) resetPolicyForm();
    await loadData();
  } catch (e) {
    if (e === "cancel" || e === "close") return;
    ElMessage.error(e?.response?.data?.detail || "策略删除失败");
  }
};

const testChannel = async (row) => {
  testingChannelId.value = row.id;
  try {
    const payload = {};
    const content = String(channelTestContent.value || "").trim();
    if (content) payload.content = content;
    const res = await http.post(`/notify/channels/${row.id}/test`, payload);
    ElMessage.success(res?.data?.detail || "测试发送成功");
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || "测试发送失败");
  } finally {
    testingChannelId.value = null;
  }
};

onMounted(async () => {
  try {
    await loadData();
  } catch (_e) {
    ElMessage.error("加载通知配置失败（需要管理员权限）");
  }
});
</script>

<style scoped>
.bar {
  margin-bottom: 12px;
}

h2 {
  margin: 0;
}

.card-title {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.actions,
.row-actions {
  display: flex;
  gap: 8px;
  align-items: center;
}

.inline-form {
  margin-bottom: 12px;
}
</style>
