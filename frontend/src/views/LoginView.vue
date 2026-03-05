<template>
  <div class="login-wrap">
    <div class="panel">
      <h1>动环监控平台</h1>
      <p>默认账号：admin/admin123，hq_noc/noc12345，suba_noc/noc12345</p>
      <el-form :model="form" @submit.prevent>
        <el-form-item>
          <el-input v-model="form.username" placeholder="请输入用户名" />
        </el-form-item>
        <el-form-item>
          <el-input
            v-model="form.password"
            type="password"
            show-password
            placeholder="请输入密码"
            @keyup.enter="submit"
          />
        </el-form-item>
        <el-button type="primary" :loading="loading" style="width: 100%" @click="submit">
          登录
        </el-button>
      </el-form>
    </div>
  </div>
</template>

<script setup>
import { reactive, ref } from "vue";
import { ElMessage } from "element-plus";
import { useRouter } from "vue-router";
import { useAuthStore } from "../stores/auth";

const auth = useAuthStore();
const router = useRouter();
const loading = ref(false);
const form = reactive({ username: "admin", password: "admin123" });

const submit = async () => {
  if (!form.username || !form.password) return;
  loading.value = true;
  try {
    await auth.login(form.username, form.password);
    router.push("/dashboard");
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || "登录失败");
  } finally {
    loading.value = false;
  }
};
</script>

<style scoped>
.login-wrap {
  min-height: 100vh;
  display: grid;
  place-items: center;
  background: radial-gradient(circle at 20% 20%, #bfd5ff 0%, #f4f8ff 45%, #f8fafc 100%);
  font-family: "Segoe UI", "Microsoft YaHei", sans-serif;
}

.panel {
  width: min(420px, 90vw);
  background: #fff;
  border-radius: 12px;
  box-shadow: 0 12px 42px rgba(16, 36, 63, 0.18);
  padding: 26px;
}

h1 {
  margin: 0 0 8px;
  color: #153968;
}

p {
  margin: 0 0 18px;
  color: #64748b;
}
</style>
