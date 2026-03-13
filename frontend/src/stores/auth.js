import { defineStore } from "pinia";
import http from "../api/http";

const parseMe = () => {
  const raw = localStorage.getItem("fsu_user");
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch (_error) {
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
    coreRole: (state) => state.user?.core_role || "employee",
    permissions: (state) => state.user?.permissions || [],
    scopes: (state) => state.user?.scopes || [],
    roleBindings: (state) => state.user?.role_bindings || [],
    tenantCodes: (state) => state.user?.tenant_codes || [],
    hasPermission: (state) => (code) => (state.user?.permissions || []).includes(code),
    hasAnyPermission: (state) => (codes) => codes.some((code) => (state.user?.permissions || []).includes(code)),
    isPlatformAdmin: (state) => state.user?.core_role === "platform_admin",
    isCompanyAdmin: (state) => state.user?.core_role === "company_admin",
    canManageUsers: (state) => ["platform_admin", "company_admin"].includes(state.user?.core_role || ""),
    defaultHome() {
      if (this.isPlatformAdmin) return "/dashboard";
      return this.canManageUsers ? "/users" : "/dashboard";
    },
    isAdmin: (state) => ["platform_admin", "company_admin"].includes(state.user?.core_role || ""),
    isTemplateManager: (state) => (state.user?.permissions || []).includes("alarm_rule.template.manage"),
    canManageTenantAssets: (state) =>
      ["site.create", "site.update"].some((code) => (state.user?.permissions || []).includes(code)),
    canEditImportant: (state) => (state.user?.permissions || []).includes("realtime.important.manage"),
  },
  actions: {
    async login(username, password) {
      const res = await http.post("/auth/login", { username, password });
      this.token = res.data.access_token;
      localStorage.setItem("fsu_token", this.token);
      await this.fetchMe();
    },
    async sendSmsCode(phone, phoneCountryCode = "+86") {
      const res = await http.post("/auth/sms/send", {
        phone_country_code: phoneCountryCode,
        phone,
        scene: "LOGIN",
      });
      return res.data;
    },
    async loginBySms(phone, code, phoneCountryCode = "+86") {
      const res = await http.post("/auth/sms/login", {
        phone_country_code: phoneCountryCode,
        phone,
        code,
      });
      this.token = res.data.access_token;
      localStorage.setItem("fsu_token", this.token);
      await this.fetchMe();
      return res.data;
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
