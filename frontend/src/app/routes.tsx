import { useEffect, useState, type ReactNode } from "react";
import { Navigate, useLocation, type RouteObject } from "react-router-dom";
import { ROLES } from "../constants/roles";
import { AccountsPage } from "../features/accounts/pages/AccountsPage";
import { LoginPage } from "../features/auth/pages/LoginPage";
import { AdminDashboardPage } from "../features/dashboard/pages/AdminDashboardPage";
import { SuperAdminDashboardPage } from "../features/dashboard/pages/SuperAdminDashboardPage";
import { ExportPage } from "../features/export/pages/ExportPage";
import { LogsPage } from "../features/logs/pages/LogsPage";
import { AirViolationsPage } from "../features/airViolations/pages/AirViolationsPage";
import { IncidentDetailPage } from "../features/news/pages/IncidentDetailPage";
import { IncidentsPage } from "../features/news/pages/IncidentsPage";
import { SourcesPage } from "../features/sources/pages/SourcesPage";
import { AppShell } from "./AppShell";
import { useAuthStore } from "../stores/authStore";
import { getSession } from "../features/auth/api";

const RequireRole = ({ roles, children }: { roles: string[]; children: ReactNode }) => {
  const location = useLocation();
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const role = useAuthStore((state) => state.role);
  const token = useAuthStore((state) => state.token);
  const logout = useAuthStore((state) => state.logout);
  const [sessionValid, setSessionValid] = useState(false);

  useEffect(() => {
    let active = true;
    if (!isAuthenticated || !token) {
      setSessionValid(false);
      return;
    }
    getSession()
      .then((session) => {
        if (!active) return;
        if (session.role !== role) {
          logout();
          return;
        }
        setSessionValid(true);
      })
      .catch(() => {
        if (active) logout();
      });
    return () => {
      active = false;
    };
  }, [isAuthenticated, logout, role, token]);

  if (!isAuthenticated) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }
  if (!sessionValid) {
    return <div className="min-h-screen bg-surface" aria-label="Validating session" />;
  }
  if (!role || !roles.includes(role)) {
    return <Navigate to={role === ROLES.SUPER_ADMIN ? "/superadmin/dashboard" : "/admin/dashboard"} replace />;
  }
  return children;
};

const HomeRedirect = () => {
  const role = useAuthStore((state) => state.role);
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  if (!isAuthenticated) return <Navigate to="/login" replace />;
  return <Navigate to={role === ROLES.SUPER_ADMIN ? "/superadmin/dashboard" : "/admin/dashboard"} replace />;
};

export const createRoutes = (): RouteObject[] => [
    { path: "/login", element: <LoginPage /> },
    {
      path: "/admin",
      element: <RequireRole roles={[ROLES.ADMIN]}><AppShell previewRole={ROLES.ADMIN} /></RequireRole>,
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
      element: <RequireRole roles={[ROLES.SUPER_ADMIN]}><AppShell previewRole={ROLES.SUPER_ADMIN} /></RequireRole>,
      children: [
        { index: true, element: <Navigate to="dashboard" replace /> },
        { path: "dashboard", element: <SuperAdminDashboardPage /> },
        { path: "incidents", element: <IncidentsPage /> },
        { path: "incidents/:incidentId", element: <IncidentDetailPage /> },
        { path: "air-violations", element: <AirViolationsPage /> },
        { path: "sources", element: <SourcesPage /> },
        { path: "logs", element: <Navigate to="audit" replace /> },
        { path: "logs/:logType", element: <LogsPage /> },
        { path: "export", element: <ExportPage /> },
        { path: "accounts", element: <AccountsPage /> },
        { path: "*", element: <Navigate to="dashboard" replace /> },
      ],
    },
    { path: "/", element: <HomeRedirect /> },
    { path: "*", element: <HomeRedirect /> },
  ];
