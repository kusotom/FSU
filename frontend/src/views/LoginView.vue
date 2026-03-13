<template>
  <div class="login-wrap">
    <div class="panel">
      <h1>动环监控平台</h1>
      <p>仅限已创建账号登录。默认演示手机号：13800000001、13800000002、13800000003</p>
      <el-form :model="form" @submit.prevent>
        <el-form-item>
          <el-input v-model="form.phone" placeholder="请输入手机号" maxlength="20" />
        </el-form-item>
        <el-form-item>
          <div class="code-row">
            <el-input
              v-model="form.code"
              placeholder="请输入短信验证码"
              maxlength="6"
              @keyup.enter="submit"
            />
            <el-button :disabled="sending || countdown > 0 || !form.phone" @click="sendCode">
              {{ countdown > 0 ? `${countdown}s 后重发` : "发送验证码" }}
            </el-button>
          </div>
        </el-form-item>
        <el-button type="primary" :loading="loading" style="width: 100%" @click="submit">
          登录
        </el-button>
      </el-form>
    </div>
  </div>
</template>

<script setup>
import { onBeforeUnmount, reactive, ref } from "vue";
import { ElMessage } from "element-plus";
import { useRouter } from "vue-router";
import { useAuthStore } from "../stores/auth";

const auth = useAuthStore();
const router = useRouter();
const loading = ref(false);
const sending = ref(false);
const countdown = ref(0);
const form = reactive({ phone: "13800000001", code: "" });

let timerId = null;

const startCountdown = (seconds = 60) => {
  countdown.value = seconds;
  if (timerId) window.clearInterval(timerId);
  timerId = window.setInterval(() => {
    countdown.value -= 1;
    if (countdown.value <= 0) {
      window.clearInterval(timerId);
      timerId = null;
    }
  }, 1000);
};

const sendCode = async () => {
  if (!form.phone.trim()) {
    ElMessage.error("请输入手机号");
    return;
  }
  sending.value = true;
  try {
    const data = await auth.sendSmsCode(form.phone.trim());
    startCountdown(data?.resend_after_seconds || 60);
    if (data?.debug_code) {
      ElMessage.success(`开发验证码：${data.debug_code}`);
    } else {
      ElMessage.success(data?.message || "验证码已发送");
    }
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || "发送验证码失败");
  } finally {
    sending.value = false;
  }
};

const submit = async () => {
  if (!form.phone.trim() || !form.code.trim()) {
    ElMessage.error("请输入手机号和验证码");
    return;
  }
  loading.value = true;
  try {
    const data = await auth.loginBySms(form.phone.trim(), form.code.trim());
    if (data?.user?.first_login_activated) {
      ElMessage.success("账号已激活");
    }
    router.push(auth.defaultHome);
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || "登录失败");
  } finally {
    loading.value = false;
  }
};

onBeforeUnmount(() => {
  if (timerId) window.clearInterval(timerId);
});
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
  line-height: 1.6;
}

.code-row {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 12px;
  width: 100%;
}

@media (max-width: 520px) {
  .code-row {
    grid-template-columns: 1fr;
  }
}
</style>
