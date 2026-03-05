<template>
  <AppShell>
    <div class="bar">
      <h2>告警中心</h2>
      <div>
        <el-select v-model="filterStatus" placeholder="选择状态" style="width: 160px; margin-right: 8px">
          <el-option label="全部" value="" />
          <el-option label="活动" value="active" />
          <el-option label="已确认" value="acknowledged" />
          <el-option label="已恢复" value="recovered" />
          <el-option label="已关闭" value="closed" />
        </el-select>
        <el-button :loading="loading" @click="handleSearch">查询</el-button>
      </div>
    </div>

    <el-table :data="rows" stripe v-loading="loading">
      <el-table-column prop="id" label="编号" width="70" />
      <el-table-column label="告警名称" min-width="160">
        <template #default="{ row }">{{ alarmNameLabel(row) }}</template>
      </el-table-column>
      <el-table-column label="告警内容" min-width="280">
        <template #default="{ row }">{{ alarmContentLabel(row) }}</template>
      </el-table-column>
      <el-table-column label="级别" width="100">
        <template #default="{ row }">
          <el-tag :type="levelTagType(row.alarm_level)">{{ levelLabel(row.alarm_level) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="statusTagType(row.status)">{{ statusLabel(row.status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="trigger_value" label="触发值" width="100" />
      <el-table-column label="开始时间" min-width="170">
        <template #default="{ row }">{{ parseTimeText(row.started_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="180">
        <template #default="{ row }">
          <el-button
            size="small"
            @click="ack(row)"
            :loading="actionLoadingId === row.id"
            :disabled="row.status !== 'active' || actionLoadingId === row.id"
          >
            确认
          </el-button>
          <el-button
            size="small"
            type="danger"
            @click="closeAlarm(row)"
            :loading="actionLoadingId === row.id"
            :disabled="row.status === 'closed' || actionLoadingId === row.id"
          >
            关闭
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <div class="pager">
      <el-pagination
        background
        layout="total, sizes, prev, pager, next"
        :total="total"
        :current-page="page"
        :page-size="pageSize"
        :page-sizes="[50, 100, 200, 500]"
        @current-change="handlePageChange"
        @size-change="handlePageSizeChange"
      />
    </div>
  </AppShell>
</template>

<script setup>
import { onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import AppShell from "../components/AppShell.vue";
import http from "../api/http";

const rows = ref([]);
const filterStatus = ref("");
const loading = ref(false);
const actionLoadingId = ref(0);
const page = ref(1);
const pageSize = ref(100);
const total = ref(0);

const alarmNameMap = {
  fsu_offline: "设备离线告警",
  mains_voltage_high: "市电电压过高",
  room_temp_high: "机房温度过高",
  room_humidity_low: "机房湿度过低",
  battery_temp_high: "电池温度过高",
};

const metricNameMap = {
  "Mains Voltage": "市电电压",
  "Room Temperature": "机房温度",
  "Room Humidity": "机房湿度",
  "Battery Temperature": "电池温度",
};

const comparisonMap = {
  gt: "大于",
  ge: "大于等于",
  lt: "小于",
  le: "小于等于",
  eq: "等于",
  ne: "不等于",
};

const statusMap = {
  active: "活动",
  acknowledged: "已确认",
  recovered: "已恢复",
  closed: "已关闭",
};

const statusLabel = (status) => statusMap[status] || "未知";

const statusTagType = (status) => {
  if (status === "active") return "danger";
  if (status === "acknowledged") return "warning";
  if (status === "recovered") return "success";
  if (status === "closed") return "info";
  return "";
};

const levelLabel = (level) => {
  const named = {
    critical: "严重",
    major: "重要",
    minor: "次要",
    warning: "预警",
  };
  if (named[level]) return named[level];
  const n = Number(level);
  if (!Number.isNaN(n)) return `${n}级`;
  return level || "-";
};

const metricNameZh = (name) => metricNameMap[name] || name || "监控项";

const alarmNameLabel = (row) => {
  if (alarmNameMap[row.alarm_code]) return alarmNameMap[row.alarm_code];
  if (row.alarm_name === "FSU heartbeat timeout" || row.alarm_name === "设备心跳超时")
    return "设备心跳超时";
  return row.alarm_name || "未命名告警";
};

const parseTimeText = (value) => {
  if (!value) return "-";
  const dt = new Date(value);
  if (Number.isNaN(dt.getTime())) return String(value);
  return dt.toLocaleString();
};

const alarmContentLabel = (row) => {
  const text = row.content || "";
  if (!text) return "-";
  if (text.includes("触发规则") || text.includes("设备心跳超时")) return text;

  let matched = text.match(
    /^FSU heartbeat stale:\s*device=([^\s]+)\s+last_seen=([^\s]+)\s+threshold_minutes=([\d.]+)/i,
  );
  if (matched) {
    return `设备心跳超时：设备 ${matched[1]}，最后心跳 ${parseTimeText(matched[2])}，阈值 ${matched[3]} 分钟`;
  }

  matched = text.match(
    /^(.+?)\s+rule=([^\s]+)\s+value=([-\d.]+)\s+comparison=([^\s]+)\s+threshold=([-\d.]+)/i,
  );
  if (matched) {
    const metric = metricNameZh(matched[1]);
    const comparison = comparisonMap[matched[4]] || matched[4];
    return `${metric}触发规则 ${matched[2]}，当前值 ${matched[3]}，比较方式 ${comparison}，阈值 ${matched[5]}`;
  }

  matched = text.match(/^(.+?)\s+value=([-\d.]+)\s+exceeds\s+upper=([-\d.]+)/i);
  if (matched) {
    const metric = metricNameZh(matched[1]);
    return `${metric}当前值 ${matched[2]} 超过上限 ${matched[3]}`;
  }

  matched = text.match(/^(.+?)\s+value=([-\d.]+)\s+below\s+lower=([-\d.]+)/i);
  if (matched) {
    const metric = metricNameZh(matched[1]);
    return `${metric}当前值 ${matched[2]} 低于下限 ${matched[3]}`;
  }

  let replaced = text;
  replaced = replaced
    .replace(/FSU heartbeat stale/gi, "设备心跳超时")
    .replace(/rule=/gi, "规则=")
    .replace(/value=/gi, "当前值=")
    .replace(/comparison=/gi, "比较方式=")
    .replace(/threshold=/gi, "阈值=")
    .replace(/threshold_minutes=/gi, "阈值分钟=")
    .replace(/device=/gi, "设备=")
    .replace(/last_seen=/gi, "最后心跳=");
  for (const [en, zh] of Object.entries(metricNameMap)) {
    replaced = replaced.replace(new RegExp(en, "g"), zh);
  }
  replaced = replaced
    .replace(/\bgt\b/g, "大于")
    .replace(/\bge\b/g, "大于等于")
    .replace(/\blt\b/g, "小于")
    .replace(/\ble\b/g, "小于等于")
    .replace(/\beq\b/g, "等于")
    .replace(/\bne\b/g, "不等于");
  return replaced;
};

const levelTagType = (level) => {
  const n = Number(level);
  if (!Number.isNaN(n)) {
    if (n <= 1) return "danger";
    if (n === 2) return "warning";
    if (n === 3) return "success";
    return "info";
  }
  if (level === "critical") return "danger";
  if (level === "major") return "warning";
  if (level === "minor") return "success";
  return "info";
};

const loadData = async () => {
  loading.value = true;
  try {
    const res = await http.get("/alarms", {
      params: {
        status: filterStatus.value || undefined,
        page: page.value,
        page_size: pageSize.value,
      },
    });
    rows.value = Array.isArray(res.data) ? res.data : [];
    const headerTotal = Number(res.headers?.["x-total-count"]);
    total.value = Number.isFinite(headerTotal) ? headerTotal : rows.value.length;
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || "告警数据加载失败");
  } finally {
    loading.value = false;
  }
};

const handleSearch = async () => {
  page.value = 1;
  await loadData();
};

const handlePageChange = async (nextPage) => {
  page.value = nextPage;
  await loadData();
};

const handlePageSizeChange = async (nextSize) => {
  pageSize.value = nextSize;
  page.value = 1;
  await loadData();
};

const ack = async (row) => {
  actionLoadingId.value = row.id;
  try {
    await http.post(`/alarms/${row.id}/ack`);
    ElMessage.success("告警已确认");
    await loadData();
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || "告警确认失败");
  } finally {
    actionLoadingId.value = 0;
  }
};

const closeAlarm = async (row) => {
  actionLoadingId.value = row.id;
  try {
    await http.post(`/alarms/${row.id}/close`);
    ElMessage.success("告警已关闭");
    await loadData();
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || "告警关闭失败");
  } finally {
    actionLoadingId.value = 0;
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

.pager {
  margin-top: 12px;
  display: flex;
  justify-content: flex-end;
}
</style>
