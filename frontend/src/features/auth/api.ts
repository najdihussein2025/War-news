import { apiClient } from "../../lib/apiClient";
import type { LoginResponse } from "./types";

export const login = async (
  username: string,
  password: string,
): Promise<LoginResponse> => {
  const response = await apiClient.post<LoginResponse>("/auth/login", {
    username,
    password,
  });

  return response.data;
};

export const logout = async (): Promise<void> => {
  await apiClient.post("/auth/logout");
};
