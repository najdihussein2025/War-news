import { create } from "zustand";
import type { Role } from "../constants/roles";

const AUTH_STORAGE_KEY = "lebanon-news-auth";

export type AuthUser = {
  id: string;
  username: string;
  displayName?: string;
  version?: number;
};

type StoredAuthState = {
  user: AuthUser | null;
  role: Role | null;
};

type AuthState = StoredAuthState & {
  isAuthenticated: boolean;
  login: (payload: { user: AuthUser; role: Role }) => void;
  logout: () => void;
  hydrateFromStorage: () => void;
};

const emptyAuthState: StoredAuthState = {
  user: null,
  role: null,
};

const readStoredAuth = (): StoredAuthState => {
  const raw = localStorage.getItem(AUTH_STORAGE_KEY);
  if (!raw) {
    return emptyAuthState;
  }

  try {
    const parsed = JSON.parse(raw) as Partial<StoredAuthState>;
    const safeState = {
      user: parsed.user ?? null,
      role: parsed.role ?? null,
    };
    localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(safeState));
    return safeState;
  } catch {
    localStorage.removeItem(AUTH_STORAGE_KEY);
    return emptyAuthState;
  }
};

const persistAuth = (state: StoredAuthState) => {
  localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(state));
};

const initialAuthState = readStoredAuth();

export const useAuthStore = create<AuthState>((set) => ({
  ...initialAuthState,
  isAuthenticated: Boolean(initialAuthState.user && initialAuthState.role),
  login: ({ user, role }) => {
    const nextState = { user, role };
    persistAuth(nextState);
    set({ ...nextState, isAuthenticated: true });
  },
  logout: () => {
    localStorage.removeItem(AUTH_STORAGE_KEY);
    set({ ...emptyAuthState, isAuthenticated: false });
  },
  hydrateFromStorage: () => {
    const stored = readStoredAuth();
    set({ ...stored, isAuthenticated: Boolean(stored.user && stored.role) });
  },
}));
