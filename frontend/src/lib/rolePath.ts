export const roleBaseFromPath = (pathname: string) =>
  pathname.startsWith("/superadmin") ? "/superadmin" : "/admin";

/** Sidebar Incidents target: keep query when already in-section; bare path for a fresh entry. */
export const incidentsNavTarget = (
  roleBase: string,
  pathname: string,
  search: string,
) => {
  const listPath = `${roleBase}/incidents`;
  const isInsideIncidents =
    pathname === listPath || pathname.startsWith(`${listPath}/`);
  return isInsideIncidents ? `${listPath}${search}` : listPath;
};
