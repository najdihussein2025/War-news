import axios from "axios";
import { useAuthStore } from "../stores/authStore";
export const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || "/api",
  timeout: 10_000,
  withCredentials: true,
});

apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    const requestUrl = error.config?.url ?? "";
    if (error.response?.status === 401 && !requestUrl.includes("/auth/login")) {
      useAuthStore.getState().logout();
    }

    return Promise.reject(error);
  },
);
