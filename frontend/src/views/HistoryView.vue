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
      <el-table-column prop="collected_at" :label="labels.collectedAt" min-width="180" fixed="left" />
      <el-table-column
        v-for="item in selectedPointColumns"
        :key="item.point_key"
        :label="item.display_name"
        min-width="150"
      >
        <template #default="{ row }">
          {{ formatCellValue(row[item.point_key]) }}
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
  title: "\u5386\u53f2\u6570\u636e\u67e5\u8be2",
  subtitle: "\u5148\u68c0\u7d22\u7ad9\u70b9\uff0c\u518d\u52fe\u9009\u9700\u8981\u5c55\u793a\u7684\u76d1\u63a7\u9879\uff0c\u6309\u680f\u76ee\u5bf9\u6bd4\u5386\u53f2\u6570\u636e\u3002",
  siteSearch: "\u7ad9\u70b9\u68c0\u7d22",
  sitePlaceholder: "\u8f93\u5165\u7ad9\u70b9\u7f16\u7801\u6216\u7ad9\u70b9\u540d\u79f0",
  startTime: "\u5f00\u59cb\u65f6\u95f4",
  endTime: "\u7ed3\u675f\u65f6\u95f4",
  search: "\u67e5\u8be2",
  export: "\u5bfc\u51fa",
  currentSite: "\u5f53\u524d\u7ad9\u70b9\uff1a",
  pointSectionTitle: "\u76d1\u63a7\u9879\u9009\u62e9",
  pointSectionTip: "\u7ad9\u70b9\u9009\u4e2d\u540e\u518d\u52fe\u9009\u9700\u8981\u5c55\u793a\u7684\u76d1\u63a7\u9879\uff0c\u6700\u591a\u540c\u65f6\u5bf9\u6bd4 12 \u9879\u3002",
  pointFilterPlaceholder: "\u641c\u7d22\u76d1\u63a7\u9879",
  selectAll: "\u5168\u9009",
  clearAll: "\u6e05\u7a7a",
  selectGroup: "\u5168\u9009\u672c\u7ec4",
  clearGroup: "\u6e05\u7a7a\u672c\u7ec4",
  collectedAt: "\u91c7\u96c6\u65f6\u95f4",
  chooseSiteFirst: "\u8bf7\u5148\u9009\u62e9\u7ad9\u70b9",
  choosePointFirst: "\u8bf7\u81f3\u5c11\u52fe\u9009\u4e00\u4e2a\u76d1\u63a7\u9879",
  searchFailed: "\u67e5\u8be2\u5931\u8d25",
  initFailed: "\u521d\u59cb\u5316\u5386\u53f2\u67e5\u8be2\u5931\u8d25",
  unnamedPoint: "\u672a\u547d\u540d\u76d1\u63a7\u9879",
  emptySiteHint: "\u8bf7\u5148\u68c0\u7d22\u5e76\u9009\u62e9\u7ad9\u70b9",
  emptyResultHint: "\u5f53\u524d\u6761\u4ef6\u4e0b\u6682\u65e0\u5386\u53f2\u6570\u636e",
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

const selectedSiteLabel = computed(() => {
  const site = siteOptions.value.find((item) => item.code === form.site_code);
  if (!site) return form.site_code || "";
  return `${site.name}\uff08${site.code}\uff09`;
});

const filteredPointOptions = computed(() => {
  const keyword = String(pointKeyword.value || "").trim().toLowerCase();
  if (!keyword) return pointOptions.value;
  return pointOptions.value.filter((item) =>
    `${item.display_name} ${item.point_key}`.toLowerCase().includes(keyword)
  );
});

const filteredPointGroups = computed(() => {
  return pointCategoryOrder
    .map((key) => ({
      key,
      label: pointCategoryLabelMap[key] || labels.unnamedPoint,
      options: filteredPointOptions.value.filter((item) => item.category === key),
    }))
    .filter((item) => item.options.length > 0);
});

const selectedPointColumns = computed(() => {
  const selectedSet = new Set(form.point_keys);
  return pointOptions.value.filter((item) => selectedSet.has(item.point_key));
});

const tableRows = computed(() => {
  const grouped = new Map();
  for (const item of rows.value) {
    const ts = item.collected_at;
    if (!grouped.has(ts)) {
      grouped.set(ts, { collected_at: ts });
    }
    grouped.get(ts)[item.point_key] = item.value;
  }
  return Array.from(grouped.values()).sort((a, b) => String(a.collected_at).localeCompare(String(b.collected_at)));
});

const normalizeSiteOption = (item) => ({
  code: String(item?.code || "").trim(),
  name: String(item?.name || item?.code || "").trim(),
  label: `${String(item?.name || item?.code || "").trim()}\uff08${String(item?.code || "").trim()}\uff09`,
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
    form.point_keys = pointOptions.value.slice(0, 4).map((item) => item.point_key);
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

const exportCsv = () => {
  if (!tableRows.value.length || !selectedPointColumns.value.length) return;
  const headers = [labels.collectedAt, ...selectedPointColumns.value.map((item) => item.display_name)];
  const lines = [headers];
  for (const row of tableRows.value) {
    lines.push([
      row.collected_at,
      ...selectedPointColumns.value.map((item) => formatCellValue(row[item.point_key])),
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

.point-checks {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 8px 12px;
}

.point-check {
  margin-right: 0;
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
