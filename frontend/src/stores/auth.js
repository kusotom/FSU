import { defineStore } from "pinia";
import http from "../api/http";

const parseMe = () => {
  const raw = localStorage.getItem("fsu_user");
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch (_e) {
    return null;
  }
};

export const useAuthStore = defineStore("auth", {
  state: () => ({
    token: localStorage.getItem("fsu_token") || "",
    user: parseMe(),
  }),
  getters: {
    isLoggedIn: (state) => Boolean(state.token),
    permissions: (state) => state.user?.permissions || [],
    scopes: (state) => state.user?.scopes || [],
    roleBindings: (state) => state.user?.role_bindings || [],
    tenantCodes: (state) => state.user?.tenant_codes || [],
    hasPermission: (state) => (code) => (state.user?.permissions || []).includes(code),
    hasAnyPermission: (state) => (codes) => codes.some((code) => (state.user?.permissions || []).includes(code)),
    isAdmin: (state) => (state.user?.permissions || []).includes("user.manage"),
    isTemplateManager: (state) =>
      (state.user?.permissions || []).includes("alarm_rule.template.manage"),
    canManageTenantAssets: (state) =>
      ["site.create", "site.update"].some((code) => (state.user?.permissions || []).includes(code)),
    canEditImportant: (state) =>
      (state.user?.permissions || []).includes("realtime.important.manage"),
  },
  actions: {
    async login(username, password) {
      const res = await http.post("/auth/login", { username, password });
      this.token = res.data.access_token;
      localStorage.setItem("fsu_token", this.token);
      await this.fetchMe();
    },
    async fetchMe() {
      if (!this.token) return;
      const res = await http.get("/auth/me");
      this.user = res.data;
      localStorage.setItem("fsu_user", JSON.stringify(this.user));
    },
    logout() {
      this.token = "";
      this.user = null;
      localStorage.removeItem("fsu_token");
      localStorage.removeItem("fsu_user");
    },
  },
});
