<template>
  <AppShell>
    <div class="bar">
      <h2>历史数据查询</h2>
    </div>
    <el-form inline>
      <el-form-item label="站点编码">
        <el-input v-model="form.site_code" style="width: 160px" />
      </el-form-item>
      <el-form-item label="测点标识">
        <el-input v-model="form.point_key" style="width: 180px" />
      </el-form-item>
      <el-form-item label="开始时间">
        <el-date-picker v-model="form.start" type="datetime" />
      </el-form-item>
      <el-form-item label="结束时间">
        <el-date-picker v-model="form.end" type="datetime" />
      </el-form-item>
      <el-form-item>
        <el-button type="primary" @click="search">查询</el-button>
      </el-form-item>
    </el-form>

    <el-table :data="rows" stripe>
      <el-table-column prop="point_key" label="测点标识" />
      <el-table-column prop="value" label="数值" width="120" />
      <el-table-column prop="collected_at" label="采集时间" />
    </el-table>
  </AppShell>
</template>

<script setup>
import { reactive, ref } from "vue";
import { ElMessage } from "element-plus";
import AppShell from "../components/AppShell.vue";
import http from "../api/http";

const now = new Date();
const oneHourAgo = new Date(now.getTime() - 60 * 60 * 1000);

const form = reactive({
  site_code: "SITE-001",
  point_key: "room_temp",
  start: oneHourAgo,
  end: now,
});
const rows = ref([]);

const search = async () => {
  try {
    const res = await http.get("/telemetry/history", {
      params: {
        site_code: form.site_code,
        point_key: form.point_key,
        start: form.start.toISOString(),
        end: form.end.toISOString(),
      },
    });
    rows.value = res.data;
  } catch (_e) {
    ElMessage.error("查询失败");
  }
};
</script>

<style scoped>
.bar {
  margin-bottom: 12px;
}
h2 {
  margin: 0;
}
</style>
