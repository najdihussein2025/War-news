import { create } from "zustand";
import type { Role } from "../constants/roles";

const AUTH_STORAGE_KEY = "lebanon-news-auth";

export type AuthUser = {
  id: string;
  username: string;
  displayName?: string;
};

type StoredAuthState = {
  user: AuthUser | null;
  role: Role | null;
  token: string | null;
};

type AuthState = StoredAuthState & {
  isAuthenticated: boolean;
  login: (payload: { user: AuthUser; role: Role; token: string }) => void;
  logout: () => void;
  hydrateFromStorage: () => void;
};

const emptyAuthState: StoredAuthState = {
  user: null,
  role: null,
  token: null,
};

const readStoredAuth = (): StoredAuthState => {
  const raw = localStorage.getItem(AUTH_STORAGE_KEY);
  if (!raw) {
    return emptyAuthState;
  }

  try {
    const parsed = JSON.parse(raw) as Partial<StoredAuthState>;
    return {
      user: parsed.user ?? null,
      role: parsed.role ?? null,
      token: parsed.token ?? null,
    };
  } catch {
    localStorage.removeItem(AUTH_STORAGE_KEY);
    return emptyAuthState;
  }
};

const persistAuth = (state: StoredAuthState) => {
  localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(state));
};

export const useAuthStore = create<AuthState>((set) => ({
  ...emptyAuthState,
  isAuthenticated: false,
  login: ({ user, role, token }) => {
    const nextState = { user, role, token };
    persistAuth(nextState);
    set({ ...nextState, isAuthenticated: true });
  },
  logout: () => {
    localStorage.removeItem(AUTH_STORAGE_KEY);
    set({ ...emptyAuthState, isAuthenticated: false });
  },
  hydrateFromStorage: () => {
    const stored = readStoredAuth();
    set({ ...stored, isAuthenticated: Boolean(stored.token) });
  },
}));
