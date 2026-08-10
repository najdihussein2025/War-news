export type MockUserRole = "super_admin" | "admin";

export type MockUser = {
  id: string;
  username: string;
  full_name: string;
  email: string;
  role: MockUserRole;
  is_active: boolean;
  last_login_at: string | null;
  created_at: string;
};

export const mockUsers: MockUser[] = [
  {
    id: "usr_001",
    username: "maya.haddad",
    full_name: "Maya Haddad",
    email: "maya.haddad@warnews.test",
    role: "super_admin",
    is_active: true,
    last_login_at: "2026-08-10T08:15:00+03:00",
    created_at: "2026-01-12T10:30:00+02:00",
  },
  {
    id: "usr_002",
    username: "karim.nasser",
    full_name: "Karim Nasser",
    email: "karim.nasser@warnews.test",
    role: "admin",
    is_active: true,
    last_login_at: "2026-08-09T21:45:00+03:00",
    created_at: "2026-02-04T14:10:00+02:00",
  },
  {
    id: "usr_003",
    username: "rana.saad",
    full_name: "Rana Saad",
    email: "rana.saad@warnews.test",
    role: "admin",
    is_active: true,
    last_login_at: "2026-08-03T12:20:00+03:00",
    created_at: "2026-03-18T09:00:00+02:00",
  },
  {
    id: "usr_004",
    username: "omar.fares",
    full_name: "Omar Fares",
    email: "omar.fares@warnews.test",
    role: "admin",
    is_active: false,
    last_login_at: "2026-07-18T16:05:00+03:00",
    created_at: "2026-04-07T11:45:00+03:00",
  },
  {
    id: "usr_005",
    username: "leila.mansour",
    full_name: "Leila Mansour",
    email: "leila.mansour@warnews.test",
    role: "super_admin",
    is_active: true,
    last_login_at: "2026-07-29T09:35:00+03:00",
    created_at: "2026-01-28T15:25:00+02:00",
  },
  {
    id: "usr_006",
    username: "sami.khoury",
    full_name: "Sami Khoury",
    email: "sami.khoury@warnews.test",
    role: "admin",
    is_active: false,
    last_login_at: null,
    created_at: "2026-06-11T13:15:00+03:00",
  },
  {
    id: "usr_007",
    username: "dalia.abboud",
    full_name: "Dalia Abboud",
    email: "dalia.abboud@warnews.test",
    role: "admin",
    is_active: true,
    last_login_at: "2026-08-10T10:50:00+03:00",
    created_at: "2026-05-22T08:40:00+03:00",
  },
];
