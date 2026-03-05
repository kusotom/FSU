<template>
  <AppShell>
    <h2>平台总览</h2>
    <div class="grid">
      <div class="card">
        <div class="k">站点数量</div>
        <div class="v">{{ summary.site_count }}</div>
      </div>
      <div class="card">
        <div class="k">告警总数</div>
        <div class="v">{{ summary.alarm_total }}</div>
      </div>
      <div class="card">
        <div class="k">活动告警</div>
        <div class="v danger">{{ summary.alarm_active }}</div>
      </div>
      <div class="card">
        <div class="k">已恢复</div>
        <div class="v ok">{{ summary.alarm_recovered }}</div>
      </div>
    </div>
    <el-card>
      <template #header>系统说明</template>
      <p>平台已支持数据采集上报、实时监控、阈值告警、告警闭环和权限控制。</p>
      <p>可运行 `backend/scripts/mock_ingest.py` 持续上报模拟数据，观察页面变化。</p>
    </el-card>
  </AppShell>
</template>

<script setup>
import { onMounted, reactive } from "vue";
import AppShell from "../components/AppShell.vue";
import http from "../api/http";

const summary = reactive({
  site_count: 0,
  alarm_total: 0,
  alarm_active: 0,
  alarm_recovered: 0,
  alarm_closed: 0,
});

onMounted(async () => {
  const res = await http.get("/reports/alarm-summary");
  Object.assign(summary, res.data);
});
</script>

<style scoped>
h2 {
  margin: 0 0 14px;
}
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}
.card {
  background: #fff;
  border-radius: 10px;
  padding: 16px;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.06);
}
.k {
  color: #64748b;
  font-size: 13px;
}
.v {
  font-size: 30px;
  margin-top: 8px;
  font-weight: 700;
  color: #1f2937;
}
.danger {
  color: #dc2626;
}
.ok {
  color: #059669;
}
</style>
