import { createRouter, createWebHistory } from "vue-router";

const LoginView = () => import("../views/LoginView.vue");
const DashboardView = () => import("../views/DashboardView.vue");
const RealtimeView = () => import("../views/RealtimeView.vue");
const SitesView = () => import("../views/SitesView.vue");
const AlarmsView = () => import("../views/AlarmsView.vue");
const HistoryView = () => import("../views/HistoryView.vue");
const UsersView = () => import("../views/UsersView.vue");
const NotifyView = () => import("../views/NotifyView.vue");
const AlarmRulesView = () => import("../views/AlarmRulesView.vue");

const routes = [
  { path: "/login", component: LoginView },
  { path: "/", redirect: "/dashboard" },
  { path: "/dashboard", component: DashboardView, meta: { auth: true, permission: "dashboard.view" } },
  { path: "/realtime", component: RealtimeView, meta: { auth: true, permission: "realtime.view" } },
  { path: "/sites-manage", component: SitesView, meta: { auth: true, permission: "site.view" } },
  { path: "/alarms", component: AlarmsView, meta: { auth: true, permission: "alarm.view" } },
  { path: "/history", component: HistoryView, meta: { auth: true, permission: "history.view" } },
  {
    path: "/alarm-rules",
    component: AlarmRulesView,
    meta: { auth: true, anyPermissions: ["alarm_rule.template.view", "alarm_rule.tenant.view"] },
  },
  { path: "/users", component: UsersView, meta: { auth: true, permission: "user.view" } },
  { path: "/notify", component: NotifyView, meta: { auth: true, anyPermissions: ["notify.channel.view", "notify.policy.view"] } },
];

const router = createRouter({
  history: createWebHistory(),
  routes,
});

router.beforeEach((to, _from, next) => {
  const token = localStorage.getItem("fsu_token");
  const rawUser = localStorage.getItem("fsu_user");
  let permissions = [];

  if (rawUser) {
    try {
      const user = JSON.parse(rawUser);
      permissions = Array.isArray(user?.permissions) ? user.permissions : [];
    } catch (_e) {
      permissions = [];
    }
  }

  if (to.meta.auth && !token) {
    next("/login");
    return;
  }
  if (to.meta.permission && !permissions.includes(to.meta.permission)) {
    next("/dashboard");
    return;
  }
  if (Array.isArray(to.meta.anyPermissions) && !to.meta.anyPermissions.some((item) => permissions.includes(item))) {
    next("/dashboard");
    return;
  }
  next();
});

export default router;
