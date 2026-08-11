import { Navigate, type RouteObject } from "react-router-dom";
import type { Role } from "../constants/roles";
import { AppShell } from "./AppShell";
import { LoginPage } from "../features/auth/pages/LoginPage";
import { IncidentDetailPage } from "../features/news/pages/IncidentDetailPage";
import { IncidentsPage } from "../features/news/pages/IncidentsPage";
import { SourcesPage } from "../features/sources/pages/SourcesPage";
import { AccountsPage } from "../features/accounts/pages/AccountsPage";
import { LogsPage } from "../features/logs/pages/LogsPage";
import { ExportPage } from "../features/export/pages/ExportPage";

export const createRoutes = (_role: Role | null): RouteObject[] => [
  { path: "/login", element: <LoginPage /> },
  {
    // Frontend-only mock shell. Add real auth and super_admin guards here when the backend is wired up.
    element: <AppShell staticSuperAdmin />,
    children: [
      { index: true, element: <Navigate to="/incidents" replace /> },
      { path: "/incidents", element: <IncidentsPage /> },
      { path: "/incidents/:incidentId", element: <IncidentDetailPage /> },
      { path: "/news", element: <Navigate to="/incidents" replace /> },
      { path: "/sources", element: <SourcesPage /> },
      { path: "/logs", element: <Navigate to="/logs/audit" replace /> },
      { path: "/logs/:logType", element: <LogsPage /> },
      { path: "/export", element: <ExportPage /> },
      { path: "/superadmin", element: <AccountsPage /> },
      { path: "/admin", element: <Navigate to="/superadmin" replace /> },
    ],
  },
  { path: "*", element: <Navigate to="/incidents" replace /> },
];
