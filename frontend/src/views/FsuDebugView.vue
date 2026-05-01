<template>
  <div class="fsu-debug">
    <div class="page-head">
      <div>
        <h1>FSU 接入诊断页</h1>
        <p>只读逆向分析视图：候选 ACK 未确认，线上 ACK/回包未启用。</p>
      </div>
      <el-button :loading="loading" type="primary" @click="loadData">刷新</el-button>
    </div>

    <el-alert
      class="notice"
      type="warning"
      :closable="false"
      show-icon
      title="只读模式：仅读取 raw log、readonly parse 和日报；不发送 UDP，不新增 ACK，不修改 fsu-gateway 回包逻辑，不写业务主表。当前注释为逆向分析结果，不代表厂商协议确认；ACK_WAIT_INFERRED 只是推断，线上 ACK/回包未启用。"
    />

    <el-row :gutter="12" class="stat-row">
      <el-col :span="6"><metric-card label="扫描日志" :value="data.logs?.length || 0" /></el-col>
      <el-col :span="6"><metric-card label="保留记录" :value="data.recordsRetained || 0" /></el-col>
      <el-col :span="6"><metric-card label="UNKNOWN" :value="data.summary?.unknownCount || 0" /></el-col>
      <el-col :span="6"><metric-card label="候选业务帧" :value="data.businessFrameCandidates?.length || 0" /></el-col>
    </el-row>

    <el-row :gutter="12">
      <el-col :span="12">
        <section class="panel">
          <div class="panel-title">设备在线状态</div>
          <div class="status-grid">
            <status-line title="UDP_DSC" :item="data.onlineStatus?.UDP_DSC" />
            <status-line title="UDP_RDS" :item="data.onlineStatus?.UDP_RDS" />
            <status-line title="HTTP_SOAP" :item="data.onlineStatus?.HTTP_SOAP" />
          </div>
          <p class="muted">超过 {{ data.onlineStatus?.thresholdSeconds || 60 }} 秒无包显示为离线/异常。</p>
        </section>
      </el-col>
      <el-col :span="12">
        <section class="panel">
          <div class="panel-title">当前阶段</div>
          <p class="stage-summary">{{ data.currentDeviceStage?.summary || "暂无阶段判断" }}</p>
          <div class="chips">
            <el-tag :type="data.currentDeviceStage?.stillLoginConfigRepeatStage ? 'warning' : 'info'">
              登录/配置重复: {{ yesNo(data.currentDeviceStage?.stillLoginConfigRepeatStage) }}
            </el-tag>
            <el-tag :type="data.currentDeviceStage?.businessDataStageSignals ? 'success' : 'info'">
              疑似业务数据: {{ yesNo(data.currentDeviceStage?.businessDataStageSignals) }}
            </el-tag>
            <el-tag :type="data.currentDeviceStage?.abnormalSignals ? 'danger' : 'info'">
              异常阶段: {{ yesNo(data.currentDeviceStage?.abnormalSignals) }}
            </el-tag>
          </div>
        </section>
      </el-col>
    </el-row>

    <el-row :gutter="12">
      <el-col :span="12">
        <section class="panel">
          <div class="panel-title">诊断建议</div>
          <div v-if="data.diagnosticSuggestions?.length" class="suggestion-list">
            <el-alert
              v-for="item in data.diagnosticSuggestions"
              :key="item.code"
              :type="item.level"
              :closable="false"
              show-icon
              class="suggestion"
              :title="item.title"
              :description="item.detail"
            />
          </div>
          <span v-else class="empty">暂无建议</span>
        </section>
      </el-col>
      <el-col :span="12">
        <section class="panel">
          <div class="panel-title">一键导出</div>
          <div class="export-grid">
            <el-button @click="exportBundle('recentRawPackets')">最近 100 条 raw packet</el-button>
            <el-button @click="exportBundle('latestDailyReports')">最近日报</el-button>
            <el-button @click="exportBundle('unknownSamples')">UNKNOWN 样本</el-button>
            <el-button @click="exportBundle('dscConfigSamples')">DSC_CONFIG 样本</el-button>
          </div>
          <p class="muted">导出内容来自当前只读接口响应，不会触发发包或入库。</p>
        </section>
      </el-col>
    </el-row>

    <el-row :gutter="12">
      <el-col :span="12">
        <section class="panel">
          <div class="panel-title">近 24 小时信号</div>
          <div class="chips">
            <el-tag :type="data.last24hSignals?.hasNewFrame ? 'warning' : 'info'">
              新帧: {{ yesNo(data.last24hSignals?.hasNewFrame) }}
            </el-tag>
            <el-tag :type="data.last24hSignals?.hasBusinessFrameCandidate ? 'success' : 'info'">
              疑似业务帧: {{ yesNo(data.last24hSignals?.hasBusinessFrameCandidate) }}
            </el-tag>
            <el-tag :type="data.last24hSignals?.stillRepeatingConfigLongFrames ? 'warning' : 'info'">
              重复配置长帧: {{ yesNo(data.last24hSignals?.stillRepeatingConfigLongFrames) }}
            </el-tag>
            <el-tag type="info">DSC_CONFIG {{ data.last24hSignals?.dscConfigCount || 0 }}</el-tag>
          </div>
        </section>
      </el-col>
      <el-col :span="12">
        <section class="panel alert-panel">
          <div class="panel-title">新类型告警</div>
          <div class="chips">
            <span>新 frameClass</span>
            <el-tag v-for="item in data.summary?.newFrameClassesInLast10Minutes || []" :key="item" type="warning">
              {{ item }}
            </el-tag>
            <el-tag v-if="!(data.summary?.newFrameClassesInLast10Minutes || []).length" type="info">无</el-tag>
          </div>
          <div class="chips">
            <span>新 typeA</span>
            <el-tag v-for="item in data.summary?.newTypeAInLast10Minutes || []" :key="item" type="warning">
              {{ item }}
            </el-tag>
            <el-tag v-if="!(data.summary?.newTypeAInLast10Minutes || []).length" type="info">无</el-tag>
          </div>
          <div class="chips">
            <span>新 length</span>
            <el-tag v-for="item in data.summary?.newLengthsInLast10Minutes || []" :key="item" type="warning">
              {{ item }}
            </el-tag>
            <el-tag v-if="!(data.summary?.newLengthsInLast10Minutes || []).length" type="info">无</el-tag>
          </div>
        </section>
      </el-col>
    </el-row>

    <section class="panel">
      <div class="panel-title">最近日报入口</div>
      <el-table :data="data.dailyReports || []" border stripe size="small" height="180">
        <el-table-column prop="date" label="日期" width="140" />
        <el-table-column prop="md" label="Markdown 报告" min-width="360" />
        <el-table-column prop="json" label="JSON 报告" min-width="360" />
      </el-table>
    </section>

    <section class="panel">
      <div class="panel-title">FrameClass 注释</div>
      <el-table :data="data.summary?.frameClass || []" border stripe size="small" height="320">
        <el-table-column prop="value" label="frameClass" min-width="260" />
        <el-table-column prop="annotation.chineseName" label="中文名称" min-width="190" />
        <el-table-column prop="annotation.semanticClass" label="语义分类" min-width="230" />
        <el-table-column prop="annotation.confidence" label="置信度" width="90" />
        <el-table-column label="业务数据帧" width="110">
          <template #default="{ row }">{{ businessText(row.annotation?.businessDataConfirmed) }}</template>
        </el-table-column>
        <el-table-column label="注释" min-width="360">
          <template #default="{ row }">{{ (row.annotation?.notes || []).join("；") }}</template>
        </el-table-column>
        <el-table-column prop="count" label="数量" width="100" />
      </el-table>
    </section>

    <el-row :gutter="12">
      <el-col :span="12"><summary-table title="TypeA" :rows="data.summary?.typeA" /></el-col>
      <el-col :span="12"><summary-table title="Length" :rows="data.summary?.length" /></el-col>
    </el-row>

    <el-row :gutter="12">
      <el-col :span="8"><summary-table title="UDP_DSC remotePort" :rows="data.summary?.protocolRemotePort?.UDP_DSC" /></el-col>
      <el-col :span="8"><summary-table title="UDP_RDS remotePort" :rows="data.summary?.protocolRemotePort?.UDP_RDS" /></el-col>
      <el-col :span="8"><summary-table title="URI 统计" :rows="data.summary?.uri" /></el-col>
    </el-row>

    <section class="panel">
      <div class="panel-title">TypeA / Length 组合</div>
      <el-table :data="data.summary?.typeALength || []" border stripe size="small" height="260">
        <el-table-column prop="value" label="protocol | typeA | length" min-width="320" />
        <el-table-column prop="typeAAnnotation.chineseName" label="typeA 注释" min-width="190" />
        <el-table-column prop="typeAAnnotation.semanticClass" label="typeA 语义分类" min-width="250" />
        <el-table-column prop="typeAAnnotation.confidence" label="置信度" width="90" />
        <el-table-column prop="count" label="数量" width="100" />
      </el-table>
    </section>

    <section class="panel">
      <div class="panel-title">最近 24 小时 frameClass 趋势</div>
      <el-table :data="trendRows" border stripe size="small" height="260">
        <el-table-column prop="hour" label="小时" min-width="210" />
        <el-table-column prop="frameClass" label="frameClass" min-width="260" />
        <el-table-column prop="count" label="数量" width="100" />
      </el-table>
    </section>

    <section class="panel">
      <div class="panel-title">UNKNOWN 样本</div>
      <packet-table :rows="data.unknownExamples || []" @copy="copyRaw" />
    </section>

    <section class="panel">
      <div class="panel-title">非 24/30/209/245 长度帧</div>
      <packet-table :rows="data.nonStandardLengthFrames || []" @copy="copyRaw" />
    </section>

    <section class="panel">
      <div class="panel-title">含明显 ASCII 的新帧</div>
      <packet-table :rows="data.asciiNewFrames || []" @copy="copyRaw" />
    </section>

    <section class="panel">
      <div class="panel-title">payloadLengthCandidate 异常</div>
      <packet-table :rows="data.payloadLengthAnomalies || []" @copy="copyRaw" />
    </section>

    <section class="panel">
      <div class="panel-title">候选业务帧列表</div>
      <packet-table :rows="data.businessFrameCandidates || []" @copy="copyRaw" />
    </section>

    <section class="panel">
      <div class="panel-title">最近 100 条原始包</div>
      <packet-table :rows="data.recentPackets || []" @copy="copyRaw" />
    </section>
  </div>
</template>

<script setup>
import { computed, defineComponent, h, onMounted, reactive, ref } from "vue";
import { ElButton, ElMessage, ElTable, ElTableColumn } from "element-plus";
import http from "../api/http";

const loading = ref(false);
const data = reactive({
  logs: [],
  summary: {},
  recentPackets: [],
  unknownExamples: [],
  nonStandardLengthFrames: [],
  asciiNewFrames: [],
  payloadLengthAnomalies: [],
  businessFrameCandidates: [],
  parseErrors: [],
  dailyReports: [],
  currentDeviceStage: {},
  last24hSignals: {},
  onlineStatus: {},
  diagnosticSuggestions: [],
  exportBundles: {},
});

const MetricCard = defineComponent({
  props: {
    label: { type: String, required: true },
    value: { type: [String, Number], required: true },
  },
  setup(props) {
    return () => h("div", { class: "metric" }, [h("span", props.label), h("strong", String(props.value))]);
  },
});

const StatusLine = defineComponent({
  props: {
    title: { type: String, required: true },
    item: { type: Object, default: () => ({}) },
  },
  setup(props) {
    return () =>
      h("div", { class: "status-line" }, [
        h("span", { class: "status-name" }, props.title),
        h(
          "span",
          { class: props.item?.status === "online" ? "status-ok" : "status-bad" },
          props.item?.status === "online" ? "在线" : "离线/异常",
        ),
        h("code", props.item?.lastSeenAt || "无数据"),
        h("span", { class: "muted" }, props.item?.ageSeconds == null ? "" : `${props.item.ageSeconds}s 前`),
      ]);
  },
});

const SummaryTable = defineComponent({
  props: {
    title: { type: String, required: true },
    rows: { type: Array, default: () => [] },
  },
  setup(props) {
    return () =>
      h("section", { class: "panel" }, [
        h("div", { class: "panel-title" }, props.title),
        h(
          "div",
          { class: "summary-list" },
          props.rows.length
            ? props.rows.map((row) =>
                h("div", { class: "summary-row", key: row.value }, [
                  h("code", row.value),
                  h("strong", row.count),
                ]),
              )
            : h("span", { class: "empty" }, "无数据"),
        ),
      ]);
  },
});

const PacketTable = defineComponent({
  props: {
    rows: { type: Array, default: () => [] },
  },
  emits: ["copy"],
  setup(props, { emit }) {
    return () =>
      h(
        ElTable,
        { data: props.rows, border: true, stripe: true, size: "small", height: 320 },
        () => [
          h(ElTableColumn, { prop: "receivedAt", label: "时间", minWidth: 210 }),
          h(ElTableColumn, { prop: "protocol", label: "协议", width: 90 }),
          h(ElTableColumn, {
            label: "远端",
            minWidth: 150,
            formatter: (row) => `${row.remoteAddress || ""}:${row.remotePort || ""}`,
          }),
          h(ElTableColumn, { prop: "frameClass", label: "frameClass", minWidth: 250 }),
          h(ElTableColumn, {
            label: "semanticClass",
            minWidth: 220,
            formatter: (row) => row.annotation?.semanticClass || "",
          }),
          h(ElTableColumn, {
            label: "中文名称",
            minWidth: 180,
            formatter: (row) => row.annotation?.chineseName || "",
          }),
          h(ElTableColumn, {
            label: "业务数据",
            width: 95,
            formatter: (row) => businessText(row.annotation?.businessDataConfirmed),
          }),
          h(ElTableColumn, { prop: "typeA", label: "typeA", width: 100 }),
          h(ElTableColumn, { prop: "length", label: "length", width: 80 }),
          h(ElTableColumn, { prop: "seqLEHex", label: "seqLE", width: 90 }),
          h(ElTableColumn, {
            label: "URI/ASCII",
            minWidth: 220,
            formatter: (row) => {
              if (row.uris?.length) return row.uris.join(" | ");
              return (row.asciiSpans || []).map((span) => span.text).join(" | ");
            },
          }),
          h(ElTableColumn, {
            label: "rawHex",
            minWidth: 260,
            formatter: (row) => row.rawHex,
          }),
          h(ElTableColumn, {
            label: "操作",
            width: 90,
            fixed: "right",
            formatter: (row) =>
              h(ElButton, { size: "small", onClick: () => emit("copy", row.rawHex) }, () => "复制"),
          }),
        ],
      );
  },
});

const trendRows = computed(() => {
  const rows = [];
  for (const bucket of data.summary?.frameClassTrend24h || []) {
    for (const item of bucket.frameClass || []) {
      rows.push({ hour: bucket.hour, frameClass: item.value, count: item.count });
    }
  }
  return rows;
});

const loadData = async () => {
  loading.value = true;
  try {
    const response = await http.get("/fsu-debug/raw-packets", {
      params: { max_records: 10000, recent_limit: 100 },
    });
    Object.assign(data, response.data);
  } finally {
    loading.value = false;
  }
};

const copyRaw = async (rawHex) => {
  await navigator.clipboard.writeText(rawHex || "");
  ElMessage.success("rawHex 已复制");
};

const exportBundle = (key) => {
  const bundle = data.exportBundles?.[key];
  if (!bundle) {
    ElMessage.warning("暂无可导出数据");
    return;
  }
  const blob = new Blob([JSON.stringify(bundle.records || [], null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = bundle.filename || `${key}.json`;
  link.click();
  URL.revokeObjectURL(url);
};

const yesNo = (value) => (value ? "是" : "否");
const businessText = (value) => (value === true ? "是" : value === false ? "否" : "未知");

onMounted(loadData);
</script>

<style scoped>
.fsu-debug {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.page-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
}

h1 {
  margin: 0;
  font-size: 24px;
}

p {
  margin: 6px 0 0;
  color: #667085;
}

.notice,
.panel,
.metric {
  border-radius: 6px;
}

.metric,
.panel {
  background: #fff;
  border: 1px solid #e5e7eb;
  padding: 12px;
}

.metric {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
}

.metric span,
.chips span,
.muted {
  color: #667085;
}

.metric strong {
  font-size: 24px;
}

.panel-title {
  font-weight: 700;
  margin-bottom: 10px;
}

.status-grid,
.suggestion-list,
.summary-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.status-line {
  display: grid;
  grid-template-columns: 90px 92px minmax(180px, 1fr) 80px;
  gap: 8px;
  align-items: center;
}

.status-name {
  font-weight: 700;
}

.status-ok {
  color: #067647;
  font-weight: 700;
}

.status-bad {
  color: #b42318;
  font-weight: 700;
}

.export-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.summary-list {
  max-height: 260px;
  overflow: auto;
}

.summary-row {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  border-bottom: 1px solid #f2f4f7;
  padding-bottom: 4px;
}

.summary-row code {
  overflow-wrap: anywhere;
}

.chips {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin: 8px 0;
}

.empty {
  color: #98a2b3;
}
</style>
