import axios from "axios";

const http = axios.create({
  baseURL: "/api/v1",
  timeout: 10000,
});

http.interceptors.request.use((config) => {
  const token = localStorage.getItem("fsu_token");
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

http.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem("fsu_token");
      localStorage.removeItem("fsu_user");
      if (!window.location.pathname.includes("/login")) {
        window.location.href = "/login";
      }
    }
    return Promise.reject(error);
  }
);

export default http;
