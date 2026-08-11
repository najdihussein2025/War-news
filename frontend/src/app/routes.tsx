import { Navigate, type RouteObject } from "react-router-dom";
import { ROLES } from "../constants/roles";
import { AccountsPage } from "../features/accounts/pages/AccountsPage";
import { LoginPage } from "../features/auth/pages/LoginPage";
import { AdminDashboardPage } from "../features/dashboard/pages/AdminDashboardPage";
import { SuperAdminDashboardPage } from "../features/dashboard/pages/SuperAdminDashboardPage";
import { ExportPage } from "../features/export/pages/ExportPage";
import { LogsPage } from "../features/logs/pages/LogsPage";
import { IncidentDetailPage } from "../features/news/pages/IncidentDetailPage";
import { IncidentsPage } from "../features/news/pages/IncidentsPage";
import { SourcesPage } from "../features/sources/pages/SourcesPage";
import { AppShell } from "./AppShell";

export const createRoutes = (): RouteObject[] => [
    { path: "/login", element: <LoginPage /> },
    {
      path: "/admin",
      element: <AppShell previewRole={ROLES.ADMIN} />,
      children: [
        { index: true, element: <Navigate to="dashboard" replace /> },
        { path: "dashboard", element: <AdminDashboardPage /> },
        { path: "incidents", element: <IncidentsPage /> },
        { path: "incidents/:incidentId", element: <IncidentDetailPage /> },
        { path: "export", element: <ExportPage /> },
        { path: "*", element: <Navigate to="dashboard" replace /> },
      ],
    },
    {
      path: "/superadmin",
      element: <AppShell previewRole={ROLES.SUPER_ADMIN} />,
      children: [
        { index: true, element: <Navigate to="dashboard" replace /> },
        { path: "dashboard", element: <SuperAdminDashboardPage /> },
        { path: "incidents", element: <IncidentsPage /> },
        { path: "incidents/:incidentId", element: <IncidentDetailPage /> },
        { path: "sources", element: <SourcesPage /> },
        { path: "logs", element: <Navigate to="audit" replace /> },
        { path: "logs/:logType", element: <LogsPage /> },
        { path: "export", element: <ExportPage /> },
        { path: "accounts", element: <AccountsPage /> },
        { path: "*", element: <Navigate to="dashboard" replace /> },
      ],
    },
    { path: "/", element: <Navigate to="/admin/dashboard" replace /> },
    { path: "*", element: <Navigate to="/admin/dashboard" replace /> },
  ];
