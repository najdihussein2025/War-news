import type { Role } from "../../constants/roles";
import type { AuthUser } from "../../stores/authStore";

export type LoginResponse = {
  user: AuthUser;
  role: Role;
};

export type SessionResponse = Pick<LoginResponse, "user" | "role">;
