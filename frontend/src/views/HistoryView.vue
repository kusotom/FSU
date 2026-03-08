<template>
  <AppShell>
    <div class="bar">
      <h2>{{ labels.title }}</h2>
      <p>{{ labels.subtitle }}</p>
    </div>

    <el-form inline class="query-form">
      <el-form-item :label="labels.siteSearch">
        <el-autocomplete
          v-model="form.site_keyword"
          :fetch-suggestions="querySiteSuggestions"
          value-key="label"
          clearable
          :placeholder="labels.sitePlaceholder"
          style="width: 320px"
          @select="handleSiteSelect"
          @change="handleSiteKeywordChange"
        />
      </el-form-item>
      <el-form-item :label="labels.startTime">
        <el-date-picker v-model="form.start" type="datetime" />
      </el-form-item>
      <el-form-item :label="labels.endTime">
        <el-date-picker v-model="form.end" type="datetime" />
      </el-form-item>
      <el-form-item>
        <el-button type="primary" @click="search">{{ labels.search }}</el-button>
      </el-form-item>
      <el-form-item v-if="tableRows.length > 0">
        <el-button @click="exportCsv">{{ labels.export }}</el-button>
      </el-form-item>
    </el-form>

    <div v-if="selectedSiteLabel" class="selected-site">
      {{ labels.currentSite }}{{ selectedSiteLabel }}
    </div>

    <div v-if="form.site_code" class="point-panel">
      <div class="point-panel-head">
        <div>
          <div class="point-panel-title">{{ labels.pointSectionTitle }}</div>
          <div class="point-panel-tip">{{ labels.pointSectionTip }}</div>
        </div>
        <div class="point-panel-actions">
          <el-input
            v-model="pointKeyword"
            clearable
            :placeholder="labels.pointFilterPlaceholder"
            style="width: 220px"
          />
          <el-button text @click="selectAllPoints">{{ labels.selectAll }}</el-button>
          <el-button text @click="clearSelectedPoints">{{ labels.clearAll }}</el-button>
        </div>
      </div>

      <div class="point-groups">
        <section v-for="group in filteredPointGroups" :key="group.key" class="point-group">
          <div class="point-group-head">
            <div class="point-group-title">{{ group.label }}（{{ group.options.length }}）</div>
            <div class="point-group-actions">
              <el-button text @click="selectGroupPoints(group.options)">{{ labels.selectGroup }}</el-button>
              <el-button text @click="clearGroupPoints(group.options)">{{ labels.clearGroup }}</el-button>
            </div>
          </div>
          <el-checkbox-group v-model="form.point_keys" class="point-checks" :max="12">
            <el-checkbox
              v-for="item in group.options"
              :key="item.point_key"
              :label="item.point_key"
              :value="item.point_key"
              class="point-check"
            >
              {{ item.display_name }}
            </el-checkbox>
          </el-checkbox-group>
        </section>
      </div>
    </div>

    <el-empty
      v-if="!form.site_code"
      :description="labels.emptySiteHint"
      class="page-empty"
    />

    <el-empty
      v-else-if="tableRows.length === 0 && hasSearched"
      :description="labels.emptyResultHint"
      class="page-empty"
    />

    <el-table v-else-if="tableRows.length > 0" :data="tableRows" stripe>
      <el-table-column prop="collected_at_label" :label="labels.collectedAt" min-width="180" fixed="left" />
      <el-table-column
        v-for="item in selectedPointColumns"
        :key="item.point_key"
        :label="columnLabel(item)"
        min-width="150"
      >
        <template #default="{ row }">
          {{ formatCellValue(row.values[item.point_key]) }}
        </template>
      </el-table-column>
    </el-table>
  </AppShell>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from "vue";
import { ElMessage } from "element-plus";
import AppShell from "../components/AppShell.vue";
import http from "../api/http";
import {
  inferPointCategory,
  pointCategoryLabelMap,
  pointCategoryOrder,
  resolvePointDisplayName,
} from "../constants/pointMetadata";

const labels = {
  title: "历史数据查询",
  subtitle: "先检索站点，再勾选要展示的监控项，按栏目对比历史数据。",
  siteSearch: "站点检索",
  sitePlaceholder: "输入站点编码或站点名称",
  startTime: "开始时间",
  endTime: "结束时间",
  search: "查询",
  export: "导出",
  currentSite: "当前站点：",
  pointSectionTitle: "监控项选择",
  pointSectionTip: "默认优先勾选关键监控项，最多同时对比 12 项。",
  pointFilterPlaceholder: "搜索监控项",
  selectAll: "全选",
  clearAll: "清空",
  selectGroup: "全选本组",
  clearGroup: "清空本组",
  collectedAt: "采集时间",
  chooseSiteFirst: "请先选择站点",
  choosePointFirst: "请至少勾选一个监控项",
  searchFailed: "查询失败",
  initFailed: "初始化历史查询失败",
  unnamedPoint: "未命名监控项",
  emptySiteHint: "请先检索并选择站点",
  emptyResultHint: "当前条件下暂无历史数据",
};

const now = new Date();
const oneHourAgo = new Date(now.getTime() - 60 * 60 * 1000);

const form = reactive({
  site_keyword: "",
  site_code: "",
  point_keys: [],
  start: oneHourAgo,
  end: now,
});

const rows = ref([]);
const siteOptions = ref([]);
const pointOptions = ref([]);
const pointOptionsLoading = ref(false);
const pointKeyword = ref("");
const hasSearched = ref(false);
const importantPointKeys = ref([]);

const selectedSiteLabel = computed(() => {
  const site = siteOptions.value.find((item) => item.code === form.site_code);
  if (!site) return form.site_code || "";
  return `${site.name}（${site.code}）`;
});

const filteredPointOptions = computed(() => {
  const keyword = String(pointKeyword.value || "").trim().toLowerCase();
  if (!keyword) return pointOptions.value;
  return pointOptions.value.filter((item) =>
    `${item.display_name} ${item.point_key}`.toLowerCase().includes(keyword)
  );
});

const filteredPointGroups = computed(() =>
  pointCategoryOrder
    .map((key) => ({
      key,
      label: pointCategoryLabelMap[key] || labels.unnamedPoint,
      options: filteredPointOptions.value.filter((item) => item.category === key),
    }))
    .filter((item) => item.options.length > 0)
);

const selectedPointColumns = computed(() => {
  const selectedSet = new Set(form.point_keys);
  return pointOptions.value.filter((item) => selectedSet.has(item.point_key));
});

const tableRows = computed(() => {
  const grouped = new Map();
  for (const item of rows.value) {
    const rawTs = String(item.collected_at || "");
    if (!grouped.has(rawTs)) {
      grouped.set(rawTs, {
        collected_at: rawTs,
        collected_at_label: formatDateTime(rawTs),
        values: {},
      });
    }
    grouped.get(rawTs).values[item.point_key] = item.value;
  }
  return Array.from(grouped.values()).sort(
    (a, b) => new Date(a.collected_at).getTime() - new Date(b.collected_at).getTime()
  );
});

const normalizeSiteOption = (item) => ({
  code: String(item?.code || "").trim(),
  name: String(item?.name || item?.code || "").trim(),
  label: `${String(item?.name || item?.code || "").trim()}（${String(item?.code || "").trim()}）`,
});

const querySiteSuggestions = (queryString, cb) => {
  const keyword = String(queryString || "").trim().toLowerCase();
  const list = !keyword
    ? siteOptions.value
    : siteOptions.value.filter((item) => `${item.code} ${item.name}`.toLowerCase().includes(keyword));
  cb(list.slice(0, 20));
};

const clearSelectedPoints = () => {
  form.point_keys = [];
};

const selectAllPoints = () => {
  form.point_keys = filteredPointOptions.value.slice(0, 12).map((item) => item.point_key);
};

const selectGroupPoints = (items) => {
  const current = new Set(form.point_keys);
  for (const item of items) {
    if (current.size >= 12) break;
    current.add(item.point_key);
  }
  form.point_keys = Array.from(current);
};

const clearGroupPoints = (items) => {
  const target = new Set(items.map((item) => item.point_key));
  form.point_keys = form.point_keys.filter((item) => !target.has(item));
};

const normalizePointOptions = (list) => {
  const map = new Map();
  for (const item of list) {
    const pointKey = String(item?.point_key || "").trim();
    if (!pointKey || map.has(pointKey)) continue;
    map.set(pointKey, {
      point_key: pointKey,
      point_name: String(item?.point_name || "").trim(),
      display_name: resolvePointDisplayName(pointKey, item?.point_name || "", labels.unnamedPoint),
      category: inferPointCategory(pointKey),
      unit: String(item?.unit || "").trim(),
    });
  }
  return Array.from(map.values()).sort((a, b) => a.display_name.localeCompare(b.display_name));
};

const handleSiteSelect = async (item) => {
  form.site_code = item.code;
  form.site_keyword = item.label;
  await loadPointOptions(item.code);
};

const handleSiteKeywordChange = async (value) => {
  const keyword = String(value || "").trim().toLowerCase();
  const matched = siteOptions.value.find(
    (item) => item.code.toLowerCase() === keyword || item.name.toLowerCase() === keyword
  );
  if (!matched) {
    if (!keyword) {
      form.site_code = "";
      pointOptions.value = [];
      form.point_keys = [];
      rows.value = [];
      hasSearched.value = false;
    }
    return;
  }
  form.site_code = matched.code;
  form.site_keyword = matched.label;
  await loadPointOptions(matched.code);
};

const loadSites = async () => {
  const res = await http.get("/sites");
  const list = Array.isArray(res.data) ? res.data : [];
  siteOptions.value = list.map(normalizeSiteOption).filter((item) => item.code);
};

const loadImportantPointKeys = async () => {
  const res = await http.get("/telemetry/important-point-keys");
  importantPointKeys.value = Array.isArray(res.data)
    ? res.data.map((item) => String(item || "").trim()).filter(Boolean)
    : [];
};

const loadPointOptions = async (siteCode) => {
  if (!siteCode) {
    pointOptions.value = [];
    form.point_keys = [];
    return;
  }
  pointOptionsLoading.value = true;
  try {
    const res = await http.get("/telemetry/latest", { params: { site_code: siteCode } });
    pointOptions.value = normalizePointOptions(Array.isArray(res.data) ? res.data : []);
    const availableKeys = new Set(pointOptions.value.map((item) => item.point_key));
    const defaults = importantPointKeys.value.filter((item) => availableKeys.has(item)).slice(0, 12);
    form.point_keys = defaults.length ? defaults : pointOptions.value.slice(0, 4).map((item) => item.point_key);
    rows.value = [];
    hasSearched.value = false;
  } finally {
    pointOptionsLoading.value = false;
  }
};

const search = async () => {
  try {
    if (!form.site_code) {
      ElMessage.warning(labels.chooseSiteFirst);
      return;
    }
    if (!form.point_keys.length) {
      ElMessage.warning(labels.choosePointFirst);
      return;
    }
    const res = await http.get("/telemetry/history-batch", {
      params: {
        site_code: form.site_code,
        point_keys: form.point_keys.join(","),
        start: form.start.toISOString(),
        end: form.end.toISOString(),
      },
    });
    rows.value = Array.isArray(res.data) ? res.data : [];
    hasSearched.value = true;
  } catch (_e) {
    ElMessage.error(labels.searchFailed);
  }
};

const formatCellValue = (value) => {
  if (value === null || value === undefined || value === "") return "-";
  const num = Number(value);
  if (Number.isNaN(num)) return String(value);
  return Number.isInteger(num) ? String(num) : num.toFixed(2);
};

const formatDateTime = (value) => {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  const hh = String(date.getHours()).padStart(2, "0");
  const mm = String(date.getMinutes()).padStart(2, "0");
  const ss = String(date.getSeconds()).padStart(2, "0");
  return `${y}-${m}-${d} ${hh}:${mm}:${ss}`;
};

const columnLabel = (item) => (item.unit ? `${item.display_name}（${item.unit}）` : item.display_name);

const exportCsv = () => {
  if (!tableRows.value.length || !selectedPointColumns.value.length) return;
  const headers = [labels.collectedAt, ...selectedPointColumns.value.map((item) => columnLabel(item))];
  const lines = [headers];
  for (const row of tableRows.value) {
    lines.push([
      row.collected_at_label,
      ...selectedPointColumns.value.map((item) => formatCellValue(row.values[item.point_key])),
    ]);
  }
  const csv = `\ufeff${lines
    .map((line) => line.map((cell) => `"${String(cell ?? "").replace(/"/g, '""')}"`).join(","))
    .join("\r\n")}`;
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
  const link = document.createElement("a");
  const url = URL.createObjectURL(blob);
  link.href = url;
  link.download = `${form.site_code || "history"}_${new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-")}.csv`;
  link.click();
  URL.revokeObjectURL(url);
};

onMounted(async () => {
  try {
    await loadSites();
    await loadImportantPointKeys();
  } catch (_e) {
    ElMessage.error(labels.initFailed);
  }
});
</script>

<style scoped>
.bar {
  margin-bottom: 12px;
}

.bar h2 {
  margin: 0;
}

.bar p {
  margin: 6px 0 0;
  color: #64748b;
}

.query-form {
  margin-bottom: 12px;
}

.selected-site {
  margin-bottom: 12px;
  color: #475569;
}

.point-panel {
  margin-bottom: 16px;
  padding: 14px 16px;
  border: 1px solid #dbe4f0;
  border-radius: 12px;
  background: linear-gradient(180deg, #fbfdff 0%, #f8fbff 100%);
}

.point-panel-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.point-panel-title {
  font-size: 15px;
  font-weight: 700;
  color: #0f172a;
}

.point-panel-tip {
  margin-top: 4px;
  color: #64748b;
  font-size: 12px;
}

.point-panel-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.point-groups {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.point-group {
  padding-top: 4px;
}

.point-group-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
}

.point-group-title {
  font-size: 13px;
  font-weight: 700;
  color: #1e293b;
}

.point-group-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.point-checks {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 8px 12px;
}

.point-check {
  margin-right: 0;
}

.page-empty {
  margin-top: 24px;
}

@media (max-width: 960px) {
  .point-panel-head {
    flex-direction: column;
    align-items: stretch;
  }

  .point-panel-actions {
    flex-wrap: wrap;
  }

  .point-group-head {
    flex-direction: column;
    align-items: stretch;
  }
}
</style>
