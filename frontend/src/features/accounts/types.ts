import type { Role } from "../../constants/roles";

export type Account = {
  id: string;
  username: string;
  role: Role;
};
