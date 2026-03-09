<template>
  <AppShell>
    <div class="bar">
      <h2>{{ isTemplateManager ? "告警规则（模板）" : "告警策略（本租户）" }}</h2>
      <el-button v-if="isTemplateManager" type="primary" @click="openCreate">新建规则</el-button>
    </div>

    <el-table :data="rows" stripe>
      <el-table-column prop="id" label="编号" width="70" />
      <el-table-column label="规则标识" min-width="180">
        <template #default="{ row }">{{ ruleKeyLabel(row.rule_key, row.alarm_code) }}</template>
      </el-table-column>
      <el-table-column label="规则名称" min-width="180">
        <template #default="{ row }">{{ ruleNameLabel(row.rule_name, row.rule_key, row.alarm_code) }}</template>
      </el-table-column>
      <el-table-column label="分类" width="90">
        <template #default="{ row }">{{ categoryLabel(row.category) }}</template>
      </el-table-column>
      <el-table-column label="测点名称" min-width="150">
        <template #default="{ row }">{{ metricLabel(row.metric_key) }}</template>
      </el-table-column>
      <el-table-column label="告警名称" min-width="140">
        <template #default="{ row }">{{ alarmCodeLabel(row.alarm_code) }}</template>
      </el-table-column>
      <el-table-column label="比较方式" width="140">
        <template #default="{ row }">{{ comparisonLabel(row.comparison) }}</template>
      </el-table-column>
      <el-table-column prop="threshold_value" label="阈值" width="100" />
      <el-table-column prop="duration_seconds" label="持续(秒)" width="100" />
      <el-table-column label="级别" width="70">
        <template #default="{ row }">{{ row.alarm_level }}级</template>
      </el-table-column>
      <el-table-column label="启用" width="80">
        <template #default="{ row }">{{ row.is_enabled ? "是" : "否" }}</template>
      </el-table-column>
      <el-table-column label="操作" width="90">
        <template #default="{ row }">
          <el-button size="small" @click="openEdit(row)">{{ isTemplateManager ? "编辑" : "编辑策略" }}</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog
      v-model="dialogVisible"
      :title="editingId ? (isTemplateManager ? '编辑规则' : '编辑策略') : '新建规则'"
      width="620px"
    >
      <el-form :model="form" label-width="110px">
        <el-form-item label="规则编码" v-if="!editingId && isTemplateManager">
          <el-input
            v-model="form.rule_key"
            placeholder="例如：room_temp_high（系统编码，建议英文下划线）"
          />
        </el-form-item>
        <el-form-item label="规则名称">
          <el-input v-model="form.rule_name" placeholder="例如：机房温度高" :disabled="isStrategyMode" />
        </el-form-item>
        <el-form-item label="分类">
          <el-select v-model="form.category" style="width: 100%" :disabled="isStrategyMode">
            <el-option label="动力" value="power" />
            <el-option label="环境" value="env" />
            <el-option label="智能" value="smart" />
            <el-option label="系统" value="system" />
          </el-select>
        </el-form-item>
        <el-form-item label="测点名称">
          <el-select
            v-model="form.metric_key"
            style="width: 100%"
            clearable
            filterable
            allow-create
            default-first-option
            placeholder="请选择测点（系统规则可留空）"
            :disabled="isStrategyMode"
          >
            <el-option
              v-for="item in pointOptions"
              :key="item.value"
              :label="item.label"
              :value="item.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="告警名称">
          <el-select
            v-model="form.alarm_code"
            style="width: 100%"
            clearable
            filterable
            allow-create
            default-first-option
            placeholder="请选择或输入告警编码"
            :disabled="isStrategyMode"
          >
            <el-option
              v-for="item in alarmCodeOptions"
              :key="item.value"
              :label="item.label"
              :value="item.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="比较方式">
          <el-select v-model="form.comparison" style="width: 100%" :disabled="isStrategyMode">
            <el-option label="大于" value="gt" />
            <el-option label="大于等于" value="ge" />
            <el-option label="小于" value="lt" />
            <el-option label="小于等于" value="le" />
            <el-option label="等于" value="eq" />
            <el-option label="不等于" value="ne" />
            <el-option label="超时分钟" value="stale_minutes" />
          </el-select>
        </el-form-item>
        <el-form-item label="阈值">
          <el-input-number v-model="form.threshold_value" :step="1" :precision="2" />
        </el-form-item>
        <el-form-item label="持续窗口(秒)">
          <el-input-number v-model="form.duration_seconds" :min="0" />
        </el-form-item>
        <el-form-item label="告警级别">
          <el-select v-model="form.alarm_level" style="width: 100%">
            <el-option label="1级" :value="1" />
            <el-option label="2级" :value="2" />
            <el-option label="3级" :value="3" />
            <el-option label="4级" :value="4" />
          </el-select>
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="form.is_enabled" />
        </el-form-item>
        <el-form-item label="说明">
          <el-input v-model="form.description" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button v-if="isStrategyMode && editingId" @click="restoreTemplate">恢复模板</el-button>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submit">保存</el-button>
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
const isTemplateManager = computed(() => auth.isTemplateManager);
const isStrategyMode = computed(() => !isTemplateManager.value);
const rows = ref([]);
const dialogVisible = ref(false);
const editingId = ref(null);
const currentTenantCode = ref("");
const form = reactive({
  rule_key: "",
  rule_name: "",
  category: "power",
  metric_key: "",
  alarm_code: "",
  comparison: "gt",
  threshold_value: null,
  duration_seconds: 0,
  alarm_level: 2,
  is_enabled: true,
  description: "",
});

const pointOptions = [
  { value: "mains_voltage", label: "市电电压" },
  { value: "mains_current", label: "市电电流" },
  { value: "mains_frequency", label: "市电频率" },
  { value: "mains_power_state", label: "市电状态" },
  { value: "rectifier_module_status", label: "整流模块状态" },
  { value: "rectifier_output_voltage", label: "整流输出电压" },
  { value: "rectifier_output_current", label: "整流输出电流" },
  { value: "rectifier_load_rate", label: "整流负载率" },
  { value: "rectifier_fault_status", label: "整流故障状态" },
  { value: "battery_group_voltage", label: "电池组电压" },
  { value: "battery_cell_voltage_min", label: "电池单体最小电压" },
  { value: "battery_cell_voltage_max", label: "电池单体最大电压" },
  { value: "battery_temp", label: "电池温度" },
  { value: "battery_fault_status", label: "电池故障状态" },
  { value: "battery_fuse_status", label: "电池熔丝状态" },
  { value: "gen_running_status", label: "油机运行状态" },
  { value: "gen_start_failed", label: "油机启动失败" },
  { value: "gen_fault_status", label: "油机故障状态" },
  { value: "gen_fuel_level", label: "油机油位" },
  { value: "dc_branch_current", label: "直流支路电流" },
  { value: "dc_breaker_status", label: "空开状态" },
  { value: "dc_overcurrent", label: "直流过流状态" },
  { value: "spd_failure", label: "防雷器失效" },
  { value: "room_temp", label: "机房温度" },
  { value: "room_humidity", label: "机房湿度" },
  { value: "water_leak_status", label: "水浸状态" },
  { value: "smoke_status", label: "烟雾状态" },
  { value: "ac_running_status", label: "空调运行状态" },
  { value: "ac_fault_status", label: "空调故障状态" },
  { value: "ac_high_pressure", label: "空调高压状态" },
  { value: "ac_low_pressure", label: "空调低压状态" },
  { value: "ac_comm_status", label: "空调通信状态" },
  { value: "fresh_air_running_status", label: "新风运行状态" },
  { value: "fresh_air_fault_status", label: "新风故障状态" },
  { value: "door_access_status", label: "门禁状态" },
  { value: "camera_online_status", label: "摄像头在线状态" },
  { value: "ups_bypass_status", label: "UPS旁路状态" },
];

const alarmCodeOptions = [
  { value: "mains_voltage_high", label: "市电电压过高" },
  { value: "mains_voltage_low", label: "市电电压过低" },
  { value: "mains_current_high", label: "市电电流过高" },
  { value: "mains_frequency_high", label: "市电频率过高" },
  { value: "mains_frequency_low", label: "市电频率过低" },
  { value: "room_temp_high", label: "机房温度过高" },
  { value: "room_temp_low", label: "机房温度过低" },
  { value: "room_humidity_low", label: "机房湿度过低" },
  { value: "room_humidity_high", label: "机房湿度过高" },
  { value: "battery_temp_high", label: "电池温度过高" },
  { value: "battery_group_voltage_high", label: "电池组电压过高" },
  { value: "battery_group_voltage_low", label: "电池组电压过低" },
  { value: "rectifier_output_voltage_high", label: "整流输出电压过高" },
  { value: "rectifier_output_voltage_low", label: "整流输出电压过低" },
  { value: "water_leak_alarm", label: "水浸告警" },
  { value: "smoke_alarm", label: "烟雾告警" },
  { value: "ac_fault_alarm", label: "空调故障" },
  { value: "fresh_air_fault_alarm", label: "新风故障" },
  { value: "gen_fault_alarm", label: "油机故障" },
  { value: "rectifier_fault_alarm", label: "整流故障" },
  { value: "battery_fault_alarm", label: "电池故障" },
  { value: "dc_overcurrent_alarm", label: "直流过流告警" },
  { value: "ups_bypass_alarm", label: "UPS旁路告警" },
  { value: "battery_fuse_alarm", label: "电池熔丝告警" },
  { value: "gen_start_failed_alarm", label: "油机启动失败" },
  { value: "gen_fuel_low", label: "油机油位过低" },
  { value: "spd_failure_alarm", label: "防雷器失效" },
  { value: "ac_high_pressure_alarm", label: "空调高压告警" },
  { value: "ac_low_pressure_alarm", label: "空调低压告警" },
  { value: "ac_comm_alarm", label: "空调通信异常" },
  { value: "camera_offline_alarm", label: "摄像头离线" },
  { value: "fsu_offline", label: "设备离线" },
];

const pointLabelMap = Object.fromEntries(pointOptions.map((item) => [item.value, item.label]));
const alarmCodeLabelMap = Object.fromEntries(
  alarmCodeOptions.map((item) => [item.value, item.label]),
);

const metricLabel = (key) => {
  if (!key) return "系统级规则";
  return pointLabelMap[key] || `测点（${key}）`;
};

const humanizeCode = (code) =>
  String(code || "")
    .replace(/_/g, " ")
    .replace(/\b\w/g, (ch) => ch.toUpperCase());

const alarmCodeLabel = (code) => {
  if (!code) return "-";
  return alarmCodeLabelMap[code] || `告警（${humanizeCode(code)}）`;
};

const hasChinese = (text) => /[\u4e00-\u9fa5]/.test(String(text || ""));

const englishWordMap = {
  mains: "市电",
  voltage: "电压",
  current: "电流",
  frequency: "频率",
  room: "机房",
  temp: "温度",
  temperature: "温度",
  humidity: "湿度",
  battery: "电池",
  rectifier: "整流",
  gen: "油机",
  generator: "油机",
  fault: "故障",
  failed: "失败",
  offline: "离线",
  high: "过高",
  low: "过低",
  timeout: "超时",
  heartbeat: "心跳",
  fsu: "设备",
  status: "状态",
  rule: "规则",
};

const translateCodeText = (raw) => {
  const parts = String(raw || "")
    .toLowerCase()
    .replace(/[^a-z0-9_ ]+/g, " ")
    .split(/[_\s]+/)
    .filter(Boolean);
  if (parts.length === 0) return "";
  return parts.map((part) => englishWordMap[part] || part).join("");
};

const ruleKeyLabel = (ruleKey, alarmCode) => {
  if (alarmCodeLabelMap[alarmCode]) return `${alarmCodeLabelMap[alarmCode]}规则`;
  if (!ruleKey) return "-";
  const translated = translateCodeText(ruleKey);
  if (translated) return `${translated}规则`;
  return `规则（${humanizeCode(ruleKey)}）`;
};

const ruleNameLabel = (ruleName, ruleKey, alarmCode) => {
  if (ruleName) {
    if (hasChinese(ruleName)) return ruleName;
    const translated = translateCodeText(ruleName);
    if (translated) return translated;
    return ruleName;
  }
  if (alarmCodeLabelMap[alarmCode]) return alarmCodeLabelMap[alarmCode];
  if (ruleKey) {
    const translated = translateCodeText(ruleKey);
    if (translated) return translated;
  }
  return "-";
};

const categoryLabel = (value) => {
  if (value === "power") return "动力";
  if (value === "env") return "环境";
  if (value === "smart") return "智能";
  if (value === "system") return "系统";
  return value || "-";
};

const comparisonLabel = (value) => {
  const map = {
    gt: "大于",
    ge: "大于等于",
    lt: "小于",
    le: "小于等于",
    eq: "等于",
    ne: "不等于",
    stale_minutes: "超时分钟",
  };
  return map[value] || value || "-";
};

const resetForm = () => {
  form.rule_key = "";
  form.rule_name = "";
  form.category = "power";
  form.metric_key = "";
  form.alarm_code = "";
  form.comparison = "gt";
  form.threshold_value = null;
  form.duration_seconds = 0;
  form.alarm_level = 2;
  form.is_enabled = true;
  form.description = "";
  currentTenantCode.value = "";
};

const loadData = async () => {
  if (isTemplateManager.value) {
    const res = await http.get("/alarm-rules");
    rows.value = res.data.map((item) => ({ ...item, _tenant_code: "" }));
    return;
  }

  const res = await http.get("/alarm-rules/tenant-policies");
  rows.value = res.data.map((item) => ({
    id: item.template_rule_id,
    rule_key: item.rule_key,
    rule_name: item.rule_name,
    category: item.category,
    metric_key: item.metric_key,
    alarm_code: item.alarm_code,
    comparison: item.comparison,
    threshold_value: item.effective_threshold_value,
    duration_seconds: item.effective_duration_seconds,
    alarm_level: item.effective_alarm_level,
    is_enabled: item.effective_is_enabled,
    description: "",
    _tenant_code: item.tenant_code,
  }));
};

const openCreate = () => {
  if (!isTemplateManager.value) return;
  editingId.value = null;
  resetForm();
  dialogVisible.value = true;
};

const openEdit = (row) => {
  editingId.value = row.id;
  currentTenantCode.value = row._tenant_code || "";
  form.rule_key = row.rule_key;
  form.rule_name = row.rule_name;
  form.category = row.category;
  form.metric_key = row.metric_key || "";
  form.alarm_code = row.alarm_code;
  form.comparison = row.comparison;
  form.threshold_value = row.threshold_value;
  form.duration_seconds = row.duration_seconds;
  form.alarm_level = row.alarm_level;
  form.is_enabled = row.is_enabled;
  form.description = row.description || "";
  dialogVisible.value = true;
};

const buildPayload = () => ({
  rule_name: form.rule_name.trim(),
  category: form.category,
  metric_key: form.metric_key.trim() || null,
  alarm_code: form.alarm_code.trim(),
  comparison: form.comparison,
  threshold_value: form.threshold_value,
  duration_seconds: Number(form.duration_seconds || 0),
  alarm_level: Number(form.alarm_level || 2),
  is_enabled: form.is_enabled,
  description: form.description.trim() || null,
});

const submit = async () => {
  if (!form.rule_name.trim() || !form.alarm_code.trim()) {
    ElMessage.warning("请填写规则名称和告警代码");
    return;
  }

  if (isTemplateManager.value) {
    if (editingId.value) {
      await http.put(`/alarm-rules/${editingId.value}`, buildPayload());
      ElMessage.success("规则已更新");
    } else {
      if (!form.rule_key.trim()) {
        ElMessage.warning("请填写规则编码");
        return;
      }
      await http.post("/alarm-rules", {
        rule_key: form.rule_key.trim(),
        ...buildPayload(),
      });
      ElMessage.success("规则已创建");
    }
  } else {
    if (!editingId.value) {
      ElMessage.warning("仅支持编辑已有策略");
      return;
    }
    await http.put(`/alarm-rules/tenant-policies/${editingId.value}`, {
      tenant_code: currentTenantCode.value || undefined,
      is_enabled_override: form.is_enabled,
      threshold_value_override: form.threshold_value,
      duration_seconds_override: Number(form.duration_seconds || 0),
      alarm_level_override: Number(form.alarm_level || 2),
    });
    ElMessage.success("策略已更新");
  }

  dialogVisible.value = false;
  await loadData();
};

const restoreTemplate = async () => {
  if (!isStrategyMode.value || !editingId.value) return;
  await http.put(`/alarm-rules/tenant-policies/${editingId.value}`, {
    tenant_code: currentTenantCode.value || undefined,
    is_enabled_override: null,
    threshold_value_override: null,
    duration_seconds_override: null,
    alarm_level_override: null,
  });
  ElMessage.success("已恢复模板默认值");
  dialogVisible.value = false;
  await loadData();
};

onMounted(async () => {
  if (!auth.user && auth.token) {
    await auth.fetchMe();
  }
  try {
    await loadData();
  } catch (_e) {
    ElMessage.error(isTemplateManager.value ? "加载规则失败（需要模板管理权限）" : "加载策略失败");
  }
});
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
</style>
