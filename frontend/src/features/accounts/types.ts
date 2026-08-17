import type { Role } from "../../constants/roles";

export type Account = {
  id: string;
  username: string;
  full_name: string;
  role: { id: number; name: Role };
  is_active: boolean;
  last_login_at: string | null;
  created_at: string;
};

export type AccountCreate = {
  username: string;
  full_name: string;
  password: string;
  role_id: number;
};

export type AccountUpdate = {
  username: string;
  full_name: string;
  role_id: number;
  password?: string;
};

export type AccountRole = "super_admin" | "admin";

export type AccountRow = {
  id: string;
  username: string;
  full_name: string;
  role: AccountRole;
  is_active: boolean;
  last_login_at: string | null;
  created_at: string;
};
