import { apiClient } from "../../lib/apiClient";
import type { Account, AccountCreate, AccountPasswordChange, AccountUpdate } from "./types";

export const getAccounts = async (): Promise<Account[]> => {
  const response = await apiClient.get<Account[]>("/accounts");
  return response.data;
};

export const createAccount = async (payload: AccountCreate): Promise<Account> => {
  try {
    const response = await apiClient.post<Account>("/accounts", payload);
    return response.data;
  } catch (error) {
    const response = (error as { response?: { status?: number; data?: { detail?: string } } }).response;
    const needsBootstrap =
      response?.status === 409 &&
      response.data?.detail === "Create the first super_admin account before managing users.";

    if (!needsBootstrap) {
      throw error;
    }

    const bootstrapResponse = await apiClient.post<Account>("/accounts/bootstrap", payload);
    return bootstrapResponse.data;
  }
};

export const updateAccount = async (userId: string, payload: AccountUpdate): Promise<Account> => {
  const response = await apiClient.patch<Account>(`/accounts/${userId}`, payload);
  return response.data;
};

export const deleteAccount = async (userId: string, version: number): Promise<void> => {
  await apiClient.delete(`/accounts/${userId}`, { params: { version } });
};

export const setAccountActive = async (userId: string, isActive: boolean, version: number): Promise<Account> => {
  const response = await apiClient.patch<Account>(`/accounts/${userId}/active`, {
    is_active: isActive,
    version,
  });
  return response.data;
};

export const acquireAccountEditLock = async (userId: string): Promise<Account> => {
  const response = await apiClient.post<Account>(`/accounts/${userId}/edit-lock`);
  return response.data;
};

export const releaseAccountEditLock = async (userId: string): Promise<void> => {
  await apiClient.delete(`/accounts/${userId}/edit-lock`);
};

export const changeAccountPassword = async (
  userId: string,
  payload: AccountPasswordChange,
): Promise<void> => {
  await apiClient.patch(`/accounts/${userId}/password`, payload);
};
