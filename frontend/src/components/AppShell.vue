<template>
  <div class="shell">
    <aside class="sidebar">
      <div class="logo">动环平台</div>
      <router-link v-if="auth.hasPermission('dashboard.view')" class="nav-link" to="/dashboard">平台总览</router-link>
      <router-link v-if="auth.hasPermission('realtime.view')" class="nav-link" to="/realtime">实时监控</router-link>
      <router-link v-if="auth.hasPermission('site.view')" class="nav-link" to="/sites-manage">站点管理</router-link>
      <router-link v-if="auth.hasPermission('alarm.view')" class="nav-link" to="/alarms">告警中心</router-link>
      <router-link v-if="auth.hasPermission('history.view')" class="nav-link" to="/history">历史查询</router-link>
      <router-link
        v-if="auth.hasAnyPermission(['alarm_rule.template.view', 'alarm_rule.tenant.view'])"
        class="nav-link"
        to="/alarm-rules"
      >
        告警规则/策略
      </router-link>
      <router-link
        v-if="auth.hasAnyPermission(['notify.channel.view', 'notify.policy.view', 'notify.receiver.view', 'notify.group.view', 'notify.rule.view', 'notify.oncall.view', 'notify.push_log.view'])"
        class="nav-link"
        to="/notify"
      >
        通知策略
      </router-link>
      <router-link v-if="auth.canManageUsers" class="nav-link" to="/users">用户管理</router-link>
    </aside>
    <main class="content">
      <header class="topbar">
        <div class="user">
          <span>{{ auth.user?.full_name || auth.user?.username || "未登录" }}</span>
          <span v-if="auth.coreRole === 'platform_admin'">平台管理员</span>
          <span v-else-if="auth.coreRole === 'company_admin'">公司管理员</span>
          <span v-else-if="auth.coreRole === 'employee'">普通员工</span>
          <span v-if="auth.tenantCodes.length">租户 {{ auth.tenantCodes.join(" / ") }}</span>
          <el-button link type="primary" @click="logout">退出登录</el-button>
        </div>
      </header>
      <section class="page">
        <slot />
      </section>
    </main>
  </div>
</template>

<script setup>
import { onMounted } from "vue";
import { useRouter } from "vue-router";
import { useAuthStore } from "../stores/auth";

const auth = useAuthStore();
const router = useRouter();

onMounted(async () => {
  if (!auth.user && auth.token) {
    await auth.fetchMe();
  }
});

const logout = () => {
  auth.logout();
  router.push("/login");
};
</script>

<style scoped>
.shell {
  min-height: 100vh;
  display: grid;
  grid-template-columns: 220px 1fr;
  font-family: "Segoe UI", "Microsoft YaHei", sans-serif;
}

.sidebar {
  background: linear-gradient(180deg, #10243f 0%, #153968 100%);
  color: #fff;
  padding: 20px 16px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.logo {
  font-size: 20px;
  font-weight: 700;
  padding: 8px 10px 16px;
  letter-spacing: 1px;
}

.nav-link {
  color: #d8e6ff;
  text-decoration: none;
  padding: 10px;
  border-radius: 8px;
}

.nav-link.router-link-active {
  background: rgba(255, 255, 255, 0.2);
  color: #fff;
}

.content {
  background: #f3f5f9;
}

.topbar {
  height: 56px;
  display: flex;
  justify-content: flex-end;
  align-items: center;
  padding: 0 20px;
  background: #fff;
  border-bottom: 1px solid #e5e7eb;
}

.page {
  padding: 20px;
}

.user {
  display: flex;
  align-items: center;
  gap: 12px;
}

@media (max-width: 900px) {
  .shell {
    grid-template-columns: 1fr;
  }

  .sidebar {
    flex-direction: row;
    flex-wrap: wrap;
    gap: 6px;
  }
}
</style>
