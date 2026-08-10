export const ROLES = {
  SUPER_ADMIN: "super_admin",
  ADMIN: "admin",
} as const;

export type Role = (typeof ROLES)[keyof typeof ROLES];
