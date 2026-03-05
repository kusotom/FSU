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
  { path: "/dashboard", component: DashboardView, meta: { auth: true } },
  { path: "/realtime", component: RealtimeView, meta: { auth: true } },
  { path: "/sites-manage", component: SitesView, meta: { auth: true } },
  { path: "/alarms", component: AlarmsView, meta: { auth: true } },
  { path: "/history", component: HistoryView, meta: { auth: true } },
  { path: "/alarm-rules", component: AlarmRulesView, meta: { auth: true } },
  { path: "/users", component: UsersView, meta: { auth: true, adminOnly: true } },
  { path: "/notify", component: NotifyView, meta: { auth: true, templateOnly: true } },
];

const router = createRouter({
  history: createWebHistory(),
  routes,
});

router.beforeEach((to, _from, next) => {
  const token = localStorage.getItem("fsu_token");
  const rawUser = localStorage.getItem("fsu_user");
  let isAdmin = false;
  let isTemplateManager = false;
  if (rawUser) {
    try {
      const user = JSON.parse(rawUser);
      isAdmin = Boolean(user?.roles?.includes("admin"));
      isTemplateManager = Boolean(user?.roles?.includes("admin") || user?.roles?.includes("hq_noc"));
    } catch (_e) {
      isAdmin = false;
      isTemplateManager = false;
    }
  }
  if (to.meta.auth && !token) {
    next("/login");
    return;
  }
  if (to.meta.adminOnly && !isAdmin) {
    next("/dashboard");
    return;
  }
  if (to.meta.templateOnly && !isTemplateManager) {
    next("/dashboard");
    return;
  }
  next();
});

export default router;
