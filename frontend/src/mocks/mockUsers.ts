export type MockUserRole = "super_admin" | "admin";

export type MockUser = {
  id: string;
  username: string;
  full_name: string;
  role: MockUserRole;
  is_active: boolean;
  last_login_at: string | null;
  created_at: string;
};

export const mockUsers: MockUser[] = [];
