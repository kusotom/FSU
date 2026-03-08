<template>
  <AppShell>
    <div class="toolbar">
      <div>
        <h2>实时监控曲线</h2>
        <p>仅展示关键监控项，点击站点后展开对应曲线。</p>
      </div>
      <div class="actions">
        <el-input
          v-model="query"
          placeholder="筛选站点/测点/设备"
          clearable
          style="width: 240px"
        />
        <el-select v-model="windowMinutes" style="width: 130px">
          <el-option label="1分钟" :value="1" />
          <el-option label="5分钟" :value="5" />
          <el-option label="10分钟" :value="10" />
          <el-option label="15分钟" :value="15" />
          <el-option label="30分钟" :value="30" />
          <el-option label="60分钟" :value="60" />
        </el-select>
        <el-button @click="loadData(true)">刷新</el-button>
        <el-button v-if="canEditImportant" @click="openImportantDialog">关键项配置</el-button>
        <el-tag :type="wsTagType">{{ wsStatusText }}</el-tag>
      </div>
    </div>

    <div v-if="initialLoading" class="empty">
      <el-skeleton :rows="6" animated />
    </div>

    <div v-else-if="siteCards.length === 0" class="empty">
      <el-empty description="暂无站点数据" />
    </div>

    <el-collapse
      v-else
      v-model="expandedSite"
      accordion
      class="site-collapse"
      @change="handleSiteExpand"
    >
      <el-collapse-item
        v-for="site in siteCards"
        :key="site.site_code"
        :name="site.site_code"
        class="site-item"
        :class="siteItemClass(site.summary)"
      >
        <template #title>
          <div class="site-header">
            <div>
              <h3>{{ displaySiteName(site.site_name, site.site_code) }}</h3>
              <span>{{ site.site_code }}</span>
              <span v-if="site.region"> · {{ site.region }}</span>
            </div>
            <div class="site-stats">
              <el-tag>设备 {{ site.deviceCountText }}</el-tag>
              <el-tag type="success">测点 {{ site.metricCountText }}</el-tag>
              <el-tag :type="site.isLoaded ? 'info' : 'warning'">
                {{ site.isLoaded ? "已加载" : "点击展开加载" }}
              </el-tag>
            </div>
          </div>
          <div class="site-kpis">
            <el-tag :type="siteStatusTagType(site.summary)" :effect="siteStatusTagEffect(site.summary)">
              站点状态：{{ siteStatusLabel(site.summary) }}
            </el-tag>
            <el-tag
              v-if="siteActiveAlarmCount(site.summary) > 0"
              type="warning"
              effect="plain"
            >
              当前异常项：{{ siteActiveAlarmCount(site.summary) }} 项
            </el-tag>
          </div>
        </template>

        <div v-if="expandedSite === site.site_code" class="site-body">
          <el-skeleton v-if="site.loading" :rows="4" animated />
          <div v-else-if="!site.hasData" class="site-empty-hint">暂无监控数据</div>

          <section
            v-for="category in site.categoryOrder"
            v-else
            :key="`${site.site_code}-${category}`"
            class="category"
          >
            <div class="category-title">{{ categoryLabel(category) }}</div>
            <div class="metric-grid">
              <article
                v-for="metric in site.sections[category].primary"
                :key="metric.id"
                class="metric-card"
              >
                <header class="metric-top">
                  <div>
                    <h4>{{ displayPointName(metric.point_name, metric.point_key) }}</h4>
                  </div>
                  <div class="metric-value" :class="metricValueClass(metric)">
                    {{ formatPointValue(metric.point_key, metric.value) }}
                    <small>{{ metricUnitText(metric) }}</small>
                  </div>
                </header>
                <div v-trend-visible="metric.id" class="trend-shell">
                  <v-chart
                    v-if="isTrendVisible(metric.id)"
                    class="trend"
                    :option="buildChartOption(metric)"
                    :autoresize="{ throttle: 220 }"
                    :update-options="{ lazyUpdate: true }"
                  />
                  <div v-else class="trend trend-placeholder">滚动到可视区域后加载曲线</div>
                </div>
                <footer class="metric-foot">更新时间 {{ formatTime(metric.collected_at) }}</footer>
              </article>
            </div>
          </section>
        </div>
        <div v-else class="site-fold-hint">点击站点展开监控项</div>
      </el-collapse-item>
    </el-collapse>

    <el-dialog v-model="importantDialogVisible" title="关键监控项配置" width="760px">
      <div class="important-toolbar">
        <el-input
          v-model="importantSearch"
          clearable
          placeholder="搜索监控项名称"
          style="width: 320px"
        />
        <el-button @click="restoreDefaultImportant">恢复默认</el-button>
      </div>
      <div class="important-tip">勾选后将显示在实时监控页；未勾选项将不展示。</div>
      <div class="important-groups">
        <div v-for="group in filteredImportantGroups" :key="group.key" class="important-group">
          <div class="important-group-title">{{ group.label }}（{{ group.options.length }}）</div>
          <el-checkbox-group v-model="importantSelectedKeys" class="important-checks">
            <el-checkbox
              v-for="item in group.options"
              :key="item.key"
              :label="item.key"
              :value="item.key"
              class="important-check"
            >
              <span>{{ item.name }}</span>
            </el-checkbox>
          </el-checkbox-group>
        </div>
      </div>

      <div class="important-custom">
        <div class="important-group-title">自定义监控项（可选）</div>
        <el-input
          v-model="importantCustomInput"
          type="textarea"
          :rows="4"
          placeholder="每行或逗号分隔一个监控项编码"
        />
      </div>
      <template #footer>
        <el-button @click="importantDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="importantSaving" @click="saveImportantPointKeys">保存</el-button>
      </template>
    </el-dialog>
  </AppShell>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { ElMessage } from "element-plus";
import VChart from "vue-echarts";
import { use } from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import { LineChart } from "echarts/charts";
import { GridComponent, TooltipComponent, LegendComponent } from "echarts/components";
import AppShell from "../components/AppShell.vue";
import http from "../api/http";
import { useAuthStore } from "../stores/auth";
import {
  hasChineseText,
  inferPointCategory,
  pointCategoryLabelMap,
  pointCategoryOrder,
  pointNameZhMap,
  resolvePointDisplayName,
} from "../constants/pointMetadata";

use([CanvasRenderer, LineChart, GridComponent, TooltipComponent, LegendComponent]);

const auth = useAuthStore();
const canEditImportant = computed(() => auth.canEditImportant);

const query = ref("");
const windowMinutes = ref(10);
const wsStatus = ref("connecting");
const expandedSite = ref("");
const allSites = ref([]);
const siteOverviewMap = ref({});
const siteLoadingMap = ref({});
const siteRowsStore = new Map();
const siteLoadedAt = new Map();
const seriesStore = new Map();
const latestValueStore = new Map();
const uiTick = ref(0);
const chartTick = ref(0);
const initialLoading = ref(true);
const siteMetaLoadedAt = ref(0);
const siteOverviewLoadedAt = ref(0);
const trendVisibleMap = ref({});
const historyHydratedKeys = new Set();
let historyHydrateTimer = null;
let uiRaf = null;
let chartRaf = null;
let trendObserver = null;
const trendTargetMetricIdMap = new WeakMap();

const minuteMs = 60 * 1000;
const secondMs = 1000;
const maxPoints = 1800;
const wsRefreshMinIntervalMs = 5000;
const siteMetaRefreshIntervalMs = 30000;
const siteOverviewRefreshIntervalMs = 5000;
const maxRetainMs = 24 * 60 * minuteMs;
const maxHistoryPointKeysPerBatch = 48;
const maxRenderPoints = 240;
const continuousMaxMetrics = 80;
const continuousRenderIntervalMs = 1500;
let ws = null;
let refreshTimer = null;
let reconnectTimer = null;
let generateTimer = null;
let destroyed = false;
let refreshInFlight = false;
let refreshPending = false;
let lastRefreshAt = 0;
let lastContinuousRenderAt = 0;
const defaultImportantPointKeys = [
  "mains_voltage",
  "mains_current",
  "mains_frequency",
  "battery_group_voltage",
  "battery_temp",
  "dc_branch_current",
  "room_temp",
  "room_humidity",
  "water_leak_status",
  "smoke_status",
  "ac_running_status",
  "ac_fault_status",
  "gen_running_status",
  "gen_fault_status",
  "door_access_status",
];
const importantPointKeys = ref([...defaultImportantPointKeys]);
const importantDialogVisible = ref(false);
const importantSaving = ref(false);
const importantSearch = ref("");
const importantSelectedKeys = ref([]);
const importantCustomInput = ref("");
const importantOptionList = ref([]);
const mainsVoltageKeys = new Set(["mains_voltage"]);
const dcVoltageKeys = new Set(["rectifier_output_voltage", "battery_group_voltage"]);
const dcCurrentKeys = new Set(["rectifier_output_current", "dc_branch_current"]);

const siteNameZhMap = {
  "Demo Site": "示例站点",
};

const normalizePointKeyList = (items) =>
  Array.from(new Set((items || []).map((item) => String(item || "").trim()).filter(Boolean)));

const rebuildImportantOptions = () => {
  const optionMap = new Map();
  const upsert = (pointKey, pointName = "", category = "") => {
    const key = String(pointKey || "").trim();
    if (!key) return;
    const prev = optionMap.get(key);
    const rawName = String(pointName || "").trim();
    const displayName = pointNameZhMap[key] || (hasChineseText(rawName) ? rawName : "未命名监控项");
    optionMap.set(key, {
      key,
      name: displayName,
      category: category || prev?.category || inferPointCategory(key),
    });
  };

  for (const key of Object.keys(pointNameZhMap)) {
    upsert(key, pointNameZhMap[key], inferPointCategory(key));
  }
  for (const key of defaultImportantPointKeys) {
    upsert(key, pointNameZhMap[key] || key, inferPointCategory(key));
  }
  for (const key of importantPointKeys.value) {
    upsert(key, pointNameZhMap[key] || key, inferPointCategory(key));
  }

  for (const rows of siteRowsStore.values()) {
    for (const row of rows || []) {
      upsert(row.point_key, row.point_name, row.category || inferPointCategory(row.point_key));
    }
  }

  importantOptionList.value = Array.from(optionMap.values()).sort((a, b) => {
    const ai = importantCategoryOrder.indexOf(a.category);
    const bi = importantCategoryOrder.indexOf(b.category);
    const ca = ai === -1 ? 999 : ai;
    const cb = bi === -1 ? 999 : bi;
    if (ca !== cb) return ca - cb;
    return a.key.localeCompare(b.key);
  });
};

const filteredImportantGroups = computed(() => {
  const q = String(importantSearch.value || "").trim().toLowerCase();
  const groups = [];
  for (const category of importantCategoryOrder) {
    const options = importantOptionList.value.filter((item) => {
      if (item.category !== category) return false;
      if (!q) return true;
      return `${item.name} ${item.key}`.toLowerCase().includes(q);
    });
    if (options.length === 0) continue;
    groups.push({
      key: category,
      label: importantCategoryLabelMap[category] || "其他",
      options,
    });
  }
  return groups;
});

const wsStatusText = computed(() => {
  if (wsStatus.value === "connected") return "实时通道已连接";
  if (wsStatus.value === "connecting") return "实时通道连接中";
  if (wsStatus.value === "error") return "实时通道异常";
  return "实时通道已关闭";
});

const wsTagType = computed(() => {
  if (wsStatus.value === "connected") return "success";
  if (wsStatus.value === "connecting") return "warning";
  if (wsStatus.value === "error") return "danger";
  return "info";
});

const isImportantPointKey = (pointKey) => importantPointKeys.value.includes(pointKey);

const parseImportantPointKeysInput = (raw) => {
  return Array.from(
    new Set(
      String(raw || "")
        .split(/[\n,，\s]+/)
        .map((item) => item.trim())
        .filter(Boolean),
    ),
  );
};

const loadImportantPointKeys = async () => {
  try {
    const res = await http.get("/telemetry/important-point-keys");
    const keys = Array.isArray(res.data) ? res.data.map((item) => String(item || "").trim()).filter(Boolean) : [];
    if (keys.length > 0) {
      importantPointKeys.value = keys;
      rebuildImportantOptions();
      return;
    }
  } catch (_e) {
    // fallback to local defaults
  }
  importantPointKeys.value = [...defaultImportantPointKeys];
  rebuildImportantOptions();
};

const openImportantDialog = () => {
  rebuildImportantOptions();
  const optionKeys = new Set(importantOptionList.value.map((item) => item.key));
  const selected = [];
  const custom = [];
  for (const key of importantPointKeys.value) {
    if (optionKeys.has(key)) {
      selected.push(key);
    } else {
      custom.push(key);
    }
  }
  importantSelectedKeys.value = normalizePointKeyList(selected);
  importantCustomInput.value = normalizePointKeyList(custom).join("\n");
  importantSearch.value = "";
  importantDialogVisible.value = true;
};

const restoreDefaultImportant = () => {
  const optionKeys = new Set(importantOptionList.value.map((item) => item.key));
  importantSelectedKeys.value = defaultImportantPointKeys.filter((key) => optionKeys.has(key));
  importantCustomInput.value = defaultImportantPointKeys.filter((key) => !optionKeys.has(key)).join("\n");
};

const saveImportantPointKeys = async () => {
  const customKeys = parseImportantPointKeysInput(importantCustomInput.value);
  const keys = normalizePointKeyList([...importantSelectedKeys.value, ...customKeys]);
  if (keys.length === 0) {
    ElMessage.warning("关键监控项不能为空");
    return;
  }
  try {
    importantSaving.value = true;
    const res = await http.put("/telemetry/important-point-keys", { point_keys: keys });
    const saved = Array.isArray(res.data) ? res.data.map((item) => String(item || "").trim()).filter(Boolean) : [];
    if (saved.length > 0) {
      importantPointKeys.value = saved;
    } else {
      importantPointKeys.value = keys;
    }
    rebuildImportantOptions();
    importantDialogVisible.value = false;
    historyHydratedKeys.clear();
    scheduleHistoryHydrate();
    requestUiRender();
    requestChartRender();
    ElMessage.success("关键监控项已更新");
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || "关键监控项保存失败");
  } finally {
    importantSaving.value = false;
  }
};

const getSiteRows = (siteCode) => siteRowsStore.get(siteCode) || [];

const setSiteLoading = (siteCode, loading) => {
  const next = { ...siteLoadingMap.value };
  if (loading) {
    next[siteCode] = true;
  } else {
    delete next[siteCode];
  }
  siteLoadingMap.value = next;
};

const isSiteLoading = (siteCode) => !!siteLoadingMap.value[siteCode];

const matchQuery = (text, keyword) => String(text || "").toLowerCase().includes(keyword);

const pickLatestByKeys = (rows, keys) => {
  let chosen = null;
  let chosenTs = Number.NEGATIVE_INFINITY;
  for (const row of rows) {
    if (!keys.has(row.point_key)) continue;
    const ts = parseCollectedAtMs(row.collected_at);
    if (!Number.isFinite(ts) || ts < chosenTs) continue;
    chosenTs = ts;
    chosen = row;
  }
  return chosen;
};

const buildOverviewFromRows = (rows, previousOverview = null) => {
  const mains = pickLatestByKeys(rows, mainsVoltageKeys);
  const dcVoltage = pickLatestByKeys(rows, dcVoltageKeys);
  const dcCurrent = pickLatestByKeys(rows, dcCurrentKeys);
  const ts = Math.max(
    parseCollectedAtMs(mains?.collected_at),
    parseCollectedAtMs(dcVoltage?.collected_at),
    parseCollectedAtMs(dcCurrent?.collected_at),
  );
  return {
    site_status: previousOverview?.site_status || null,
    active_alarm_count: Number(previousOverview?.active_alarm_count || 0),
    mains_voltage: mains ? Number(mains.value) : null,
    dc_voltage: dcVoltage ? Number(dcVoltage.value) : null,
    dc_current: dcCurrent ? Number(dcCurrent.value) : null,
    collected_at: Number.isFinite(ts) ? new Date(ts).toISOString() : null,
  };
};

const updateSiteOverview = (siteCode, overview) => {
  if (!siteCode) return;
  const next = { ...siteOverviewMap.value };
  next[siteCode] = overview;
  siteOverviewMap.value = next;
};

const siteKeywordMatched = (site, rows, keyword) => {
  if (!keyword) return true;
  if (
    matchQuery(site.site_code, keyword) ||
    matchQuery(site.site_name, keyword) ||
    matchQuery(site.region, keyword)
  ) {
    return true;
  }
  return rows.some((row) =>
    matchQuery(
      `${row.point_name} ${row.point_key} ${row.device_name} ${row.device_code}`,
      keyword,
    ),
  );
};

const buildSiteView = (siteMeta, keyword) => {
  const allRows = getSiteRows(siteMeta.site_code);
  const importantRows = allRows.filter((row) => isImportantPointKey(row.point_key));
  const loaded = siteRowsStore.has(siteMeta.site_code);
  const summary = siteOverviewMap.value[siteMeta.site_code] || null;
  const site = {
    site_code: siteMeta.site_code,
    site_name: siteMeta.site_name,
    region: siteMeta.region || "",
    devices: new Set(),
    categories: {},
    sections: {},
    categoryOrder: [],
    metricCount: 0,
    deviceCount: 0,
    isLoaded: loaded,
    loading: isSiteLoading(siteMeta.site_code),
    hasData: false,
    metricCountText: loaded ? "0" : "--",
    deviceCountText: loaded ? "0" : "--",
    summary,
  };

  if (!siteKeywordMatched(siteMeta, importantRows, keyword)) return null;

  const rows = keyword
    ? importantRows.filter((row) =>
        siteKeywordMatched(siteMeta, [row], keyword),
      )
    : importantRows;

  for (const row of allRows) {
    site.devices.add(row.device_code);
  }
  site.deviceCount = site.devices.size;
  site.deviceCountText = loaded ? String(site.deviceCount) : "--";

  for (const row of rows) {
    site.metricCount += 1;
    const category = row.category || "other";
    if (!site.categories[category]) {
      site.categories[category] = [];
      site.categoryOrder.push(category);
    }
    site.categories[category].push({
      ...row,
      id: metricId(row),
    });
  }

  const preferred = ["power", "env", "smart", "other"];
  site.categoryOrder.sort((a, b) => {
    const ai = preferred.indexOf(a);
    const bi = preferred.indexOf(b);
    return (ai === -1 ? 999 : ai) - (bi === -1 ? 999 : bi);
  });
  for (const key of site.categoryOrder) {
    site.categories[key].sort((a, b) => a.point_name.localeCompare(b.point_name));
    site.sections[key] = splitMetrics(site.categories[key]);
  }

  site.hasData = site.metricCount > 0;
  site.metricCountText = loaded ? String(site.metricCount) : "--";
  return site;
};

const siteCards = computed(() => {
  uiTick.value;
  const keyword = query.value.trim().toLowerCase();
  return [...allSites.value]
    .sort((a, b) => a.site_code.localeCompare(b.site_code))
    .map((site) => buildSiteView(site, keyword))
    .filter((site) => !!site);
});

const categoryLabel = (key) => {
  return pointCategoryLabelMap[key] || "其他";
};

const displayPointName = (name, key) => {
  return resolvePointDisplayName(key, name, "测点（{key}）");
};

const displaySiteName = (name, code) => {
  if (siteNameZhMap[name]) return siteNameZhMap[name];
  if (name && !/^demo/i.test(name)) return name;
  return `站点 ${code || "未知"}`;
};

const formatValue = (value) => {
  if (value === null || value === undefined) return "-";
  const n = Number(value);
  if (Number.isNaN(n)) return String(value);
  if (Math.abs(n) >= 100) return n.toFixed(1);
  return n.toFixed(2);
};

const formatSiteKpi = (value, unit) => {
  if (value === null || value === undefined) return "--";
  const n = Number(value);
  if (Number.isNaN(n)) return "--";
  return `${formatValue(n)} ${unit}`.trim();
};

const resolveSiteStatus = (summary) => {
  const raw = String(summary?.site_status || "").trim().toLowerCase();
  if (raw === "alarm") return "alarm";
  if (raw === "offline") return "offline";
  if (raw === "normal") return "normal";

  const ts = parseCollectedAtMs(summary?.collected_at);
  if (!Number.isFinite(ts)) return "offline";
  if (Date.now() - ts > 5 * minuteMs) return "offline";
  return "normal";
};

const siteStatusLabel = (summary) => {
  const status = resolveSiteStatus(summary);
  if (status === "alarm") return "告警";
  if (status === "offline") return "离线";
  return "正常";
};

const siteStatusTagType = (summary) => {
  const status = resolveSiteStatus(summary);
  if (status === "alarm") return "warning";
  if (status === "offline") return "info";
  return "success";
};

const siteStatusTagEffect = (summary) => {
  const status = resolveSiteStatus(summary);
  if (status === "alarm") return "dark";
  return "light";
};

const siteItemClass = (summary) => {
  const status = resolveSiteStatus(summary);
  if (status === "alarm") return "site-item-alarm";
  if (status === "offline") return "site-item-offline";
  return "site-item-normal";
};

const siteActiveAlarmCount = (summary) => {
  const count = Number(summary?.active_alarm_count ?? 0);
  if (!Number.isFinite(count)) return 0;
  return Math.max(0, Math.floor(count));
};

const isFaultPointKey = (pointKey) => {
  if (!pointKey) return false;
  return (
    pointKey.includes("fault") ||
    pointKey.includes("failure") ||
    pointKey.includes("start_failed")
  );
};

const statusNormalValueMap = {
  mains_power_state: 1,
  rectifier_module_status: 1,
  battery_fuse_status: 0,
  gen_running_status: 0,
  dc_breaker_status: 1,
  dc_overcurrent: 0,
  water_leak_status: 0,
  smoke_status: 0,
  ac_running_status: 1,
  ac_high_pressure: 0,
  ac_low_pressure: 0,
  ac_comm_status: 1,
  fresh_air_running_status: 1,
  door_access_status: 1,
  camera_online_status: 1,
  ups_bypass_status: 0,
};

const isStatusPointKey = (pointKey) => {
  if (!pointKey) return false;
  if (Object.prototype.hasOwnProperty.call(statusNormalValueMap, pointKey)) return true;
  return pointKey.endsWith("_status") || pointKey.endsWith("_state");
};

const toBinaryFaultState = (value) => {
  const n = Number(value);
  if (!Number.isNaN(n)) return n >= 1;
  const text = String(value ?? "")
    .trim()
    .toLowerCase();
  if (["true", "fault", "failed", "error", "alarm", "yes", "on"].includes(text)) return true;
  if (["false", "normal", "ok", "no", "off"].includes(text)) return false;
  return null;
};

const formatPointValue = (pointKey, value) => {
  if (isFaultPointKey(pointKey)) {
    const fault = toBinaryFaultState(value);
    if (fault === null) return String(value ?? "-");
    return fault ? "故障" : "正常";
  }
  if (isStatusPointKey(pointKey)) {
    const state = toBinaryFaultState(value);
    if (state === null) return String(value ?? "-");
    const normalFlag = Number(statusNormalValueMap[pointKey] ?? 0) >= 1;
    return state === normalFlag ? "正常" : "报警";
  }
  return formatValue(value);
};

const metricValueClass = (metric) => {
  const pointKey = metric?.point_key;
  if (!pointKey) return "";
  const value = metric?.value;
  if (isFaultPointKey(pointKey)) {
    const fault = toBinaryFaultState(value);
    if (fault === true) return "metric-value-alert";
    if (fault === false) return "metric-value-normal";
    return "";
  }
  if (isStatusPointKey(pointKey)) {
    const state = toBinaryFaultState(value);
    if (state === null) return "";
    const normalFlag = Number(statusNormalValueMap[pointKey] ?? 0) >= 1;
    return state === normalFlag ? "metric-value-normal" : "metric-value-alert";
  }
  return "";
};

const metricUnitText = (metric) => {
  if (isFaultPointKey(metric?.point_key) || isStatusPointKey(metric?.point_key)) return "";
  return metric?.unit || "";
};

const parseCollectedAtMs = (value) => {
  if (value === null || value === undefined) return Number.NaN;
  if (typeof value === "number") {
    if (!Number.isFinite(value)) return Number.NaN;
    // ECharts tooltip commonly provides epoch milliseconds.
    return value > 1e12 ? value : value * 1000;
  }
  const text = String(value).trim();
  if (!text) return Number.NaN;
  if (/^\d+(\.\d+)?$/.test(text)) {
    const n = Number(text);
    if (!Number.isFinite(n)) return Number.NaN;
    return n > 1e12 ? n : n * 1000;
  }
  const hasTimezone = /(?:Z|[+-]\d{2}:\d{2})$/i.test(text);
  const normalized = hasTimezone ? text : `${text}Z`;
  return new Date(normalized).getTime();
};

const metricId = (row) => `${row.site_code}|${row.point_key}`;

const requestUiRender = () => {
  if (uiRaf !== null) return;
  uiRaf = window.requestAnimationFrame(() => {
    uiRaf = null;
    uiTick.value += 1;
  });
};

const requestChartRender = () => {
  if (chartRaf !== null) return;
  chartRaf = window.requestAnimationFrame(() => {
    chartRaf = null;
    chartTick.value += 1;
  });
};

const ensureTrendObserver = () => {
  if (trendObserver || typeof window === "undefined" || typeof IntersectionObserver === "undefined") {
    return;
  }
  trendObserver = new IntersectionObserver(
    (entries) => {
      let changed = false;
      const next = { ...trendVisibleMap.value };
      for (const entry of entries) {
        const metric = trendTargetMetricIdMap.get(entry.target);
        if (!metric) continue;
        if (entry.isIntersecting || entry.intersectionRatio > 0) {
          if (!next[metric]) {
            next[metric] = true;
            changed = true;
          }
        } else if (next[metric]) {
          delete next[metric];
          changed = true;
        }
      }
      if (changed) {
        trendVisibleMap.value = next;
        requestChartRender();
      }
    },
    {
      root: null,
      rootMargin: "240px 0px 240px 0px",
      threshold: [0, 0.01],
    },
  );
};

const observeTrend = (el, metricId) => {
  if (!el || !metricId) return;
  ensureTrendObserver();
  if (!trendObserver) {
    trendVisibleMap.value = { ...trendVisibleMap.value, [metricId]: true };
    return;
  }
  trendTargetMetricIdMap.set(el, metricId);
  trendObserver.observe(el);
};

const unobserveTrend = (el) => {
  if (!el || !trendObserver) return;
  trendObserver.unobserve(el);
  const metricId = trendTargetMetricIdMap.get(el);
  trendTargetMetricIdMap.delete(el);
  if (!metricId) return;
  if (trendVisibleMap.value[metricId]) {
    const next = { ...trendVisibleMap.value };
    delete next[metricId];
    trendVisibleMap.value = next;
  }
};

const vTrendVisible = {
  mounted(el, binding) {
    observeTrend(el, binding.value);
  },
  updated(el, binding) {
    if (binding.value === binding.oldValue) return;
    unobserveTrend(el);
    observeTrend(el, binding.value);
  },
  unmounted(el) {
    unobserveTrend(el);
  },
};

const isTrendVisible = (metricId) => !!trendVisibleMap.value[metricId];

const ensureSeries = (id) => {
  let arr = seriesStore.get(id);
  if (!arr) {
    arr = [];
    seriesStore.set(id, arr);
  }
  return arr;
};

const lowerBoundByTs = (arr, targetTs) => {
  let left = 0;
  let right = arr.length;
  while (left < right) {
    const mid = (left + right) >> 1;
    if (arr[mid].ts < targetTs) {
      left = mid + 1;
    } else {
      right = mid;
    }
  }
  return left;
};

const formatTime = (time) => {
  if (!time) return "-";
  const ts = parseCollectedAtMs(time);
  if (!Number.isFinite(ts)) return String(time);
  const dt = new Date(ts);
  if (Number.isNaN(dt.getTime())) return String(time);
  return dt.toLocaleString();
};

const formatAxisTime = (ts, includeDate = false) => {
  const d = new Date(ts);
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  const ss = String(d.getSeconds()).padStart(2, "0");
  if (!includeDate) return `${hh}:${mm}:${ss}`;
  const mon = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${mon}-${day} ${hh}:${mm}`;
};

const pickTooltipPoint = (params) => {
  const first = Array.isArray(params) ? params[0] : params;
  if (!first) return null;

  const fromArray = Array.isArray(first.data)
    ? first.data
    : Array.isArray(first.value)
      ? first.value
      : null;
  if (fromArray && fromArray.length >= 2) {
    const ts = Number(fromArray[0]);
    const value = Number(fromArray[1]);
    if (Number.isFinite(ts)) {
      return { ts, value: Number.isNaN(value) ? null : value };
    }
  }

  const axisTs = Number(first.axisValue);
  const itemValue = Number(first.value);
  if (Number.isFinite(axisTs)) {
    return { ts: axisTs, value: Number.isNaN(itemValue) ? null : itemValue };
  }

  const nameTs = parseCollectedAtMs(first.name);
  if (Number.isFinite(nameTs)) {
    return { ts: nameTs, value: Number.isNaN(itemValue) ? null : itemValue };
  }
  return null;
};

const appendSeriesPoint = (row) => {
  const id = metricId(row);
  const ts = parseCollectedAtMs(row.collected_at);
  if (!Number.isFinite(ts)) return;
  const value = Number(row.value);
  if (Number.isNaN(value)) return;
  latestValueStore.set(id, { value, ts });
  appendSeriesValue(id, ts, value);
};

const appendSeriesValue = (id, ts, value) => {
  const arr = ensureSeries(id);
  const last = arr[arr.length - 1];

  if (!last || ts > last.ts) {
    arr.push({ ts, value, lastTs: ts });
    if (arr.length > maxPoints) {
      arr.splice(0, arr.length - maxPoints);
    }
  } else if (ts === last.ts) {
    if (!last.lastTs || ts >= last.lastTs) {
      last.value = value;
      last.lastTs = ts;
      last.ts = ts;
    }
  } else {
    const index = arr.findIndex((item) => item.ts === ts);
    if (index >= 0 && (!arr[index].lastTs || ts >= arr[index].lastTs)) {
      arr[index].value = value;
      arr[index].lastTs = ts;
    }
  }
};

const lineColor = (category) => {
  if (category === "power") return "#2b6cb0";
  if (category === "env") return "#0f766e";
  if (category === "smart") return "#7c3aed";
  return "#475569";
};

const splitMetrics = (metrics) => {
  const primary = metrics.filter((metric) => isImportantPointKey(metric.point_key));
  return { primary, secondary: [] };
};

const expandedSiteCard = computed(() =>
  siteCards.value.find((site) => site.site_code === expandedSite.value) || null,
);

const visibleChartMetrics = computed(() => {
  const site = expandedSiteCard.value;
  if (!site) return [];
  const list = [];
  for (const category of site.categoryOrder) {
    const primaryRows = site.sections[category]?.primary || [];
    for (const row of primaryRows) {
      list.push(row);
    }
  }
  return list;
});

const normalizeSiteOption = (item) => {
  const siteCode = String(item?.site_code ?? item?.code ?? "").trim();
  if (!siteCode) return null;
  const siteName = item?.site_name ?? item?.name ?? siteCode;
  const region = String(item?.region ?? "").trim();
  return { site_code: siteCode, site_name: siteName, region };
};

const mergeSiteOptions = (nextList) => {
  const map = new Map();
  for (const item of allSites.value) {
    map.set(item.site_code, item);
  }
  for (const item of nextList) {
    if (!item || !item.site_code) continue;
    const prev = map.get(item.site_code);
    map.set(item.site_code, {
      site_code: item.site_code,
      site_name: item.site_name || prev?.site_name || item.site_code,
      region: item.region || prev?.region || "",
    });
  }
  allSites.value = Array.from(map.values());
};

const loadSites = async (force = false) => {
  const now = Date.now();
  if (
    !force &&
    allSites.value.length > 0 &&
    now - siteMetaLoadedAt.value < siteMetaRefreshIntervalMs
  ) {
    return;
  }
  try {
    const res = await http.get("/sites");
    const raw = Array.isArray(res.data) ? res.data : [];
    mergeSiteOptions(raw.map(normalizeSiteOption).filter((item) => !!item));
    siteMetaLoadedAt.value = now;
    requestUiRender();
  } catch (_e) {
    if (allSites.value.length === 0) {
      siteMetaLoadedAt.value = 0;
      requestUiRender();
    }
  }
};

const loadSiteOverview = async (force = false) => {
  const now = Date.now();
  if (
    !force &&
    Object.keys(siteOverviewMap.value).length > 0 &&
    now - siteOverviewLoadedAt.value < siteOverviewRefreshIntervalMs
  ) {
    return;
  }
  try {
    const res = await http.get("/telemetry/site-overview");
    const rows = Array.isArray(res.data) ? res.data : [];
    const overviewSites = [];
    const next = {};
    for (const row of rows) {
      const code = String(row?.site_code || "").trim();
      if (!code) continue;
      overviewSites.push({
        site_code: code,
        site_name: String(row?.site_name || code),
        region: "",
      });
      next[code] = {
        site_status: row?.site_status ?? null,
        active_alarm_count: Number(row?.active_alarm_count ?? 0),
        mains_voltage: row?.mains_voltage ?? null,
        dc_voltage: row?.dc_voltage ?? null,
        dc_current: row?.dc_current ?? null,
        collected_at: row?.collected_at ?? null,
      };
    }
    mergeSiteOptions(overviewSites);
    siteOverviewMap.value = next;
    siteOverviewLoadedAt.value = now;
    requestUiRender();
  } catch (_e) {
    // Site list should remain available even if overview request fails.
    if (Object.keys(siteOverviewMap.value).length === 0) {
      siteOverviewLoadedAt.value = 0;
    }
  }
};

const dedupeRowsBySitePoint = (list) => {
  const map = new Map();
  for (const row of list) {
    const key = `${row.site_code}|${row.point_key}`;
    const prev = map.get(key);
    if (!prev) {
      map.set(key, row);
      continue;
    }
    const currentTs = parseCollectedAtMs(row.collected_at);
    const prevTs = parseCollectedAtMs(prev.collected_at);
    if (!Number.isFinite(prevTs) || (Number.isFinite(currentTs) && currentTs >= prevTs)) {
      map.set(key, row);
    }
  }
  return Array.from(map.values());
};

const loadSiteData = async (siteCode, force = false) => {
  if (!siteCode || isSiteLoading(siteCode)) return;
  const lastLoaded = siteLoadedAt.get(siteCode) || 0;
  if (!force && Date.now() - lastLoaded < wsRefreshMinIntervalMs) return;

  setSiteLoading(siteCode, true);
  try {
    const res = await http.get("/telemetry/latest", { params: { site_code: siteCode } });
    const rows = dedupeRowsBySitePoint(Array.isArray(res.data) ? res.data : []);
    siteRowsStore.set(siteCode, rows);
    updateSiteOverview(siteCode, buildOverviewFromRows(rows, siteOverviewMap.value[siteCode] || null));
    siteLoadedAt.set(siteCode, Date.now());
    for (const row of rows) {
      appendSeriesPoint(row);
    }
    requestUiRender();
    requestChartRender();
    if (expandedSite.value === siteCode) {
      scheduleHistoryHydrate();
    }
  } finally {
    setSiteLoading(siteCode, false);
  }
};

const hydrateVisibleHistory = async () => {
  if (!expandedSite.value) return;
  const siteCode = expandedSite.value;
  const end = new Date();
  const start = new Date(end.getTime() - windowMinutes.value * minuteMs);
  const metricsByPointKey = new Map();
  for (const metric of visibleChartMetrics.value) {
    if (!metric?.point_key) continue;
    if (!metricsByPointKey.has(metric.point_key)) {
      metricsByPointKey.set(metric.point_key, []);
    }
    metricsByPointKey.get(metric.point_key).push(metric.id);
  }

  const pointKeys = Array.from(metricsByPointKey.keys()).filter((pointKey) => {
    const cacheKey = `${siteCode}|${pointKey}|${windowMinutes.value}`;
    return !historyHydratedKeys.has(cacheKey);
  });
  if (pointKeys.length === 0) return;

  for (let offset = 0; offset < pointKeys.length; offset += maxHistoryPointKeysPerBatch) {
    const chunk = pointKeys.slice(offset, offset + maxHistoryPointKeysPerBatch);
    try {
      const res = await http.get("/telemetry/history-batch", {
        params: {
          site_code: siteCode,
          point_keys: chunk.join(","),
          start: start.toISOString(),
          end: end.toISOString(),
          bucket_minutes: 1,
        },
      });
      const data = Array.isArray(res.data) ? res.data : [];
      for (const item of data) {
        const ids = metricsByPointKey.get(item.point_key) || [];
        if (ids.length === 0) continue;
        const ts = parseCollectedAtMs(item.collected_at);
        const value = Number(item.value);
        if (!Number.isFinite(ts) || Number.isNaN(value)) continue;
        for (const metricId of ids) {
          appendSeriesValue(metricId, ts, value);
        }
      }
      for (const pointKey of chunk) {
        historyHydratedKeys.add(`${siteCode}|${pointKey}|${windowMinutes.value}`);
      }
    } catch (_e) {
      // Keep UI responsive even if part of history preload fails.
    }
  }
  requestChartRender();
};

const scheduleHistoryHydrate = () => {
  if (historyHydrateTimer) clearTimeout(historyHydrateTimer);
  historyHydrateTimer = setTimeout(async () => {
    historyHydrateTimer = null;
    await hydrateVisibleHistory();
  }, 320);
};

const generateContinuousPoints = () => {
  if (!expandedSite.value) return;
  const now = Date.now();
  const hardMinTs = now - maxRetainMs;
  const visibleIds = new Set(
    visibleChartMetrics.value.slice(0, continuousMaxMetrics).map((item) => item.id),
  );

  for (const id of visibleIds) {
    const targetRow = latestValueStore.get(id);
    if (!targetRow) continue;
    const arr = ensureSeries(id);
    const last = arr[arr.length - 1];
    const prevValue = last ? Number(last.value) : Number(targetRow.value);
    const target = Number(targetRow.value);
    if (Number.isNaN(prevValue) || Number.isNaN(target)) continue;

    // Smoothly approach latest sampled value so the curve moves continuously.
    const nextValue = Math.abs(target - prevValue) < 0.001 ? target : prevValue + (target - prevValue) * 0.35;
    const nextTs = last ? Math.max(last.ts + secondMs, now) : now;
    arr.push({ ts: nextTs, value: nextValue, lastTs: nextTs });

    while (arr.length > maxPoints || (arr.length > 0 && arr[0].ts < hardMinTs)) {
      arr.shift();
    }
  }
  if (now - lastContinuousRenderAt >= continuousRenderIntervalMs) {
    lastContinuousRenderAt = now;
    requestChartRender();
  }
};

const startContinuousGenerator = () => {
  if (generateTimer) return;
  generateTimer = setInterval(generateContinuousPoints, secondMs);
};

const buildChartOption = (metric) => {
  chartTick.value;
  const now = Date.now();
  const startTs = now - windowMinutes.value * minuteMs;
  const source = seriesStore.get(metric.id) || [];
  const startIndex = lowerBoundByTs(source, startTs);
  const remaining = Math.max(source.length - startIndex, 0);
  const step = remaining > maxRenderPoints ? Math.ceil(remaining / maxRenderPoints) : 1;
  const points = [];
  for (let i = startIndex; i < source.length; i += step) {
    const item = source[i];
    if (item.ts > now) break;
    points.push([item.ts, item.value]);
  }
  if (remaining > 0 && step > 1) {
    const last = source[source.length - 1];
    if (last && last.ts <= now) {
      const lastPoint = points[points.length - 1];
      if (!lastPoint || Number(lastPoint[0]) !== last.ts) {
        points.push([last.ts, last.value]);
      }
    }
  }
  const validCount = points.length;
  const color = lineColor(metric.category);
  return {
    animation: false,
    grid: { top: 12, left: 6, right: 6, bottom: 16, containLabel: true },
    legend: { show: false },
    tooltip: {
      trigger: "axis",
      triggerOn: "mousemove|click",
      confine: true,
      transitionDuration: 0,
      axisPointer: {
        type: "line",
        snap: false,
        label: { show: false },
      },
      formatter: (params = []) => {
        try {
          const point = pickTooltipPoint(params);
          if (!point || !Number.isFinite(point.ts)) return "无可用数据";
          if (point.value === null || point.value === undefined) return `${formatTime(point.ts)}<br/>无数据`;
          const unit = metricUnitText(metric);
          const pointLabel = displayPointName(metric.point_name, metric.point_key);
          return `${pointLabel}<br/>${formatTime(point.ts)}<br/>${formatPointValue(metric.point_key, point.value)} ${unit}`.trim();
        } catch (_e) {
          return "无可用数据";
        }
      },
    },
    xAxis: {
      type: "time",
      min: startTs,
      max: now,
      splitNumber: windowMinutes.value <= 10 ? 4 : 3,
      axisLabel: {
        show: false,
        color: "#94a3b8",
        fontSize: 9,
        hideOverlap: true,
        showMinLabel: false,
        showMaxLabel: true,
        formatter: (value) => formatAxisTime(value, windowMinutes.value > 180),
      },
      axisTick: { show: false },
      axisLine: { show: false },
      splitLine: { show: false },
      axisPointer: {
        label: { show: false },
      },
    },
    yAxis: {
      type: "value",
      scale: true,
      axisLabel: { show: false },
      axisTick: { show: false },
      axisLine: { show: false },
      splitLine: { lineStyle: { color: "rgba(71,85,105,0.12)" } },
      axisPointer: {
        label: { show: false },
      },
    },
    series: [
      {
        name: "",
        type: "line",
        data: points,
        sampling: "lttb",
        progressive: 300,
        progressiveThreshold: 600,
        showSymbol: validCount <= 2,
        symbolSize: 5,
        connectNulls: false,
        smooth: true,
        hoverAnimation: false,
        label: { show: false },
        emphasis: { label: { show: false } },
        lineStyle: { width: 2, color },
        areaStyle: { color: `${color}22` },
      },
    ],
  };
};

const loadData = async (force = false) => {
  await Promise.allSettled([loadSiteOverview(force), loadSites(force)]);
  if (expandedSite.value) {
    await loadSiteData(expandedSite.value, true);
  }
};

const ensureInitialSitesReady = async () => {
  await loadImportantPointKeys();
  await loadData(true);
  if (allSites.value.length > 0) return;
  await new Promise((resolve) => window.setTimeout(resolve, 400));
  await loadData(true);
};

const refreshExpandedSite = async () => {
  if (!expandedSite.value) return;
  await loadSiteData(expandedSite.value, true);
};

const scheduleRefresh = () => {
  if (destroyed) return;
  if (!expandedSite.value) return;
  if (refreshInFlight) {
    refreshPending = true;
    return;
  }

  const waitMs = wsRefreshMinIntervalMs - (Date.now() - lastRefreshAt);
  if (waitMs > 0) {
    if (refreshTimer) return;
    refreshTimer = setTimeout(() => {
      refreshTimer = null;
      scheduleRefresh();
    }, waitMs);
    return;
  }

  refreshInFlight = true;
  refreshExpandedSite()
    .catch(() => {
      wsStatus.value = "error";
    })
    .finally(() => {
      refreshInFlight = false;
      lastRefreshAt = Date.now();
      if (refreshPending) {
        refreshPending = false;
        scheduleRefresh();
      }
    });
};

const handleSiteExpand = async (activeName) => {
  const siteCode = typeof activeName === "string" ? activeName : "";
  historyHydratedKeys.clear();
  if (!siteCode) {
    requestUiRender();
    return;
  }
  try {
    await loadSiteData(siteCode, true);
  } catch (_e) {
    ElMessage.error("站点监控数据加载失败");
  }
};

const connectWS = () => {
  const token = localStorage.getItem("fsu_token");
  if (!token || destroyed) return;

  wsStatus.value = "connecting";
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${protocol}://${window.location.host}/ws/realtime?token=${token}`);

  ws.onopen = () => {
    wsStatus.value = "connected";
    ws.send("ping");
  };

  ws.onmessage = () => {
    scheduleRefresh();
  };

  ws.onerror = () => {
    wsStatus.value = "error";
  };

  ws.onclose = () => {
    wsStatus.value = "closed";
    if (!destroyed) {
      reconnectTimer = setTimeout(connectWS, 3000);
    }
  };
};

onMounted(async () => {
  try {
    initialLoading.value = true;
    await ensureInitialSitesReady();
  } catch (_e) {
    ElMessage.error("站点数据加载失败");
  } finally {
    initialLoading.value = false;
  }
  startContinuousGenerator();
  connectWS();
});

watch(query, () => {
  requestUiRender();
});

watch(windowMinutes, () => {
  historyHydratedKeys.clear();
  scheduleHistoryHydrate();
  requestUiRender();
  requestChartRender();
});

watch(expandedSite, () => {
  historyHydratedKeys.clear();
  scheduleHistoryHydrate();
  requestUiRender();
  requestChartRender();
});

onBeforeUnmount(() => {
  destroyed = true;
  if (refreshTimer) clearTimeout(refreshTimer);
  if (reconnectTimer) clearTimeout(reconnectTimer);
  if (historyHydrateTimer) clearTimeout(historyHydrateTimer);
  if (generateTimer) clearInterval(generateTimer);
  if (uiRaf !== null) window.cancelAnimationFrame(uiRaf);
  if (chartRaf !== null) window.cancelAnimationFrame(chartRaf);
  if (trendObserver) {
    trendObserver.disconnect();
    trendObserver = null;
  }
  if (ws) ws.close();
});
</script>

<style scoped>
.toolbar {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
  padding: 14px 16px;
  border-radius: 12px;
  color: #0f172a;
  background:
    radial-gradient(circle at 5% 10%, rgba(14, 165, 233, 0.18), transparent 38%),
    linear-gradient(120deg, #f8fbff 0%, #eef4ff 45%, #f3faf8 100%);
}

h2 {
  margin: 0;
  font-size: 22px;
}

p {
  margin: 6px 0 0;
  color: #475569;
  font-size: 13px;
}

.actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.important-tip {
  margin: 10px 0;
  color: #475569;
  font-size: 12px;
}

.important-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.important-groups {
  max-height: 360px;
  overflow-y: auto;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 10px;
}

.important-group + .important-group {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px dashed #e2e8f0;
}

.important-group-title {
  font-weight: 600;
  color: #0f172a;
  margin-bottom: 8px;
}

.important-checks {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 8px;
}

.important-check {
  margin-right: 0;
}

.important-check :deep(.el-checkbox__label) {
  display: flex;
  flex-direction: column;
  line-height: 1.2;
}

.important-check small {
  color: #64748b;
  font-size: 11px;
  margin-top: 2px;
}

.important-custom {
  margin-top: 12px;
}

.site-collapse {
  margin-top: 8px;
  border-top: 0;
}

.site-item :deep(.el-collapse-item__header) {
  min-height: 72px;
  border-radius: 12px;
  border: 1px solid #d9e2ef;
  padding: 10px 14px;
  margin-bottom: 8px;
  background: #fff;
}

.site-item.site-item-alarm :deep(.el-collapse-item__header) {
  border-color: #f59e0b;
  background: linear-gradient(120deg, #fff8eb 0%, #fff3d6 100%);
}

.site-item.site-item-offline :deep(.el-collapse-item__header) {
  border-color: #94a3b8;
  background: linear-gradient(120deg, #f8fafc 0%, #eef2f7 100%);
}

.site-item :deep(.el-collapse-item__wrap) {
  border-bottom: 0;
  background: transparent;
}

.site-item :deep(.el-collapse-item__content) {
  padding-bottom: 10px;
}

.site-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  width: 100%;
}

.site-header h3 {
  margin: 0;
  font-size: 20px;
  color: #0f172a;
}

.site-header span {
  color: #64748b;
  font-size: 12px;
}

.site-stats {
  display: flex;
  gap: 8px;
}

.site-kpis {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 8px;
}

.site-body {
  margin: 0 2px 10px;
}

.site-empty-hint {
  background: #fff;
  border: 1px dashed #cbd5e1;
  border-radius: 10px;
  color: #64748b;
  font-size: 13px;
  padding: 12px;
}

.site-fold-hint {
  color: #64748b;
  font-size: 12px;
  padding: 4px 2px 10px;
}

.category {
  margin-top: 6px;
}

.category-title {
  font-size: 14px;
  font-weight: 700;
  color: #1e293b;
  margin: 8px 0;
}

.metric-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 12px;
  align-items: start;
  grid-auto-flow: row dense;
}

.metric-card {
  border-radius: 10px;
  border: 1px solid #e2e8f0;
  background: #fff;
  padding: 8px 10px;
}

.metric-top {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 4px;
}

.metric-top h4 {
  margin: 0;
  font-size: 13px;
  color: #0f172a;
}

.metric-value {
  font-size: 18px;
  font-weight: 700;
  color: #0b3b82;
  line-height: 1;
}

.metric-value-alert {
  color: #d97706;
}

.metric-value-normal {
  color: #0f766e;
}

.metric-value small {
  font-size: 11px;
  color: #64748b;
  font-weight: 500;
}

.trend {
  height: 92px;
}

.trend-shell {
  border-radius: 8px;
  overflow: hidden;
}

.trend-placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  color: #94a3b8;
  font-size: 11px;
  border: 1px dashed #dbe4f0;
  border-radius: 8px;
  background: linear-gradient(135deg, #f8fafc 0%, #f1f5f9 100%);
}

.metric-foot {
  color: #64748b;
  font-size: 11px;
}

.empty {
  margin-top: 24px;
  background: #fff;
  border-radius: 12px;
  padding: 24px;
}

@media (max-width: 980px) {
  .toolbar {
    flex-direction: column;
  }

  .actions {
    flex-wrap: wrap;
  }
}
</style>
