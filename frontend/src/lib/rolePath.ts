export const roleBaseFromPath = (pathname: string) =>
  pathname.startsWith("/superadmin") ? "/superadmin" : "/admin";
