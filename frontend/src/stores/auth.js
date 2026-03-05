import { defineStore } from "pinia";
import http from "../api/http";

const parseUser = () => {
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
    user: parseUser(),
  }),
  getters: {
    isLoggedIn: (state) => Boolean(state.token),
    isAdmin: (state) => state.user?.roles?.includes("admin"),
    canManageTenantAssets: (state) =>
      Boolean(state.user?.roles?.includes("admin") || state.user?.roles?.includes("sub_noc")),
    isTemplateManager: (state) =>
      Boolean(state.user?.roles?.includes("admin") || state.user?.roles?.includes("hq_noc")),
    tenantCodes: (state) => state.user?.tenant_codes || [],
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
