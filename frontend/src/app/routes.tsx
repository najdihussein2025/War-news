import { useCallback, useEffect, useState, type ReactNode } from "react";
import { Navigate, useLocation, type RouteObject } from "react-router-dom";
import { ROLES } from "../constants/roles";
import { AccountsPage } from "../features/accounts/pages/AccountsPage";
import { LoginPage } from "../features/auth/pages/LoginPage";
import { AdminDashboardPage } from "../features/dashboard/pages/AdminDashboardPage";
import { SuperAdminDashboardPage } from "../features/dashboard/pages/SuperAdminDashboardPage";
import { LogsPage } from "../features/logs/pages/LogsPage";
import { AirViolationsPage } from "../features/airViolations/pages/AirViolationsPage";
import { IncidentDetailPage } from "../features/news/pages/IncidentDetailPage";
import { IncidentsPage } from "../features/news/pages/IncidentsPage";
import { RejectedNewsPage } from "../features/news/pages/RejectedNewsPage";
import { SettingsPage } from "../features/settings/pages/SettingsPage";
import { SourcesPage } from "../features/sources/pages/SourcesPage";
import { AppShell } from "./AppShell";
import { useAuthStore } from "../stores/authStore";
import { getSession } from "../features/auth/api";

const RequireRole = ({ roles, children }: { roles: string[]; children: ReactNode }) => {
  const location = useLocation();
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const role = useAuthStore((state) => state.role);
  const logout = useAuthStore((state) => state.logout);
  const [sessionValid, setSessionValid] = useState(false);
  const [validationError, setValidationError] = useState(false);
  const [validationAttempt, setValidationAttempt] = useState(0);
  const retryValidation = useCallback(() => {
    setValidationError(false);
    setValidationAttempt((value) => value + 1);
  }, []);
  const clearInvalidSession = useCallback(() => {
    logout();
    if (window.location.pathname !== "/login") {
      window.location.replace("/login");
    }
  }, [logout]);

  useEffect(() => {
    let active = true;
    if (!isAuthenticated) {
      setSessionValid(false);
      return;
    }

    setSessionValid(false);
    setValidationError(false);

    getSession()
      .then((session) => {
        if (!active) return;
        if (session.role !== role) {
          clearInvalidSession();
          return;
        }
        setValidationError(false);
        setSessionValid(true);
      })
      .catch((error: { response?: { status?: number } }) => {
        if (!active) return;
        if (error.response?.status === 401) {
          clearInvalidSession();
          return;
        }
        setValidationError(true);
      });

    return () => {
      active = false;
    };
  }, [clearInvalidSession, isAuthenticated, role, validationAttempt]);

  if (!isAuthenticated) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }
  if (!sessionValid) {
    return <main className="flex min-h-screen items-center justify-center bg-surface p-6"><div className="max-w-md rounded-lg border border-border bg-surface-raised p-6 text-center shadow-raised" role={validationError ? "alert" : "status"} aria-live="polite">{validationError ? <><h1 className="text-h4 font-semibold text-text-primary">Could not verify your session</h1><p className="mt-2 text-small text-text-muted">Check the API connection, then try again. Your session has not been deleted.</p><button type="button" className="mt-5 h-11 rounded-md bg-button-primary-bg px-4 text-small font-semibold text-button-primary-text hover:bg-button-primary-bg-hover" onClick={retryValidation}>Try again</button></> : <><span className="mx-auto block h-8 w-8 animate-spin rounded-full border-2 border-border border-t-accent" aria-hidden="true" /><p className="mt-3 text-small font-semibold text-text-primary">Validating your session…</p></>}</div></main>;
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

const RouteRepairRedirect = ({ fallback }: { fallback: string }) => {
  const location = useLocation();
  const malformedUrlMatch = location.pathname.match(/https?:\/+[^/]+(\/(?:superadmin|admin)\/[^?#]*)/i);
  if (malformedUrlMatch?.[1]) {
    return <Navigate to={malformedUrlMatch[1]} replace />;
  }
  return <Navigate to={fallback} replace />;
};

export const createRoutes = (): RouteObject[] => [
    // Role-scoped operational routes.
    { path: "/login", element: <LoginPage /> },
    {
      path: "/admin",
      element: <RequireRole roles={[ROLES.ADMIN]}><AppShell previewRole={ROLES.ADMIN} /></RequireRole>,
      children: [
        { index: true, element: <Navigate to="dashboard" replace /> },
        { path: "dashboard", element: <AdminDashboardPage /> },
        { path: "incidents", element: <IncidentsPage /> },
        { path: "incidents/:incidentId", element: <IncidentDetailPage /> },
        { path: "filtered-news", element: <AllNewsPage /> },
        { path: "rejected-news", element: <RejectedNewsPage /> },
        { path: "air-violations", element: <AirViolationsPage /> },
        { path: "map", element: <Navigate to="/admin/dashboard" replace /> },
        { path: "sources", element: <SourcesPage /> },
        { path: "logs", element: <Navigate to="audit" replace /> },
        { path: "logs/:logType", element: <LogsPage /> },
        { path: "settings", element: <SettingsPage /> },
        { path: "*", element: <RouteRepairRedirect fallback="/admin/dashboard" /> },
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
        { path: "filtered-news", element: <AllNewsPage /> },
        { path: "rejected-news", element: <RejectedNewsPage /> },
        { path: "air-violations", element: <AirViolationsPage /> },
        { path: "map", element: <Navigate to="/superadmin/dashboard" replace /> },
        { path: "sources", element: <SourcesPage /> },
        { path: "logs", element: <Navigate to="audit" replace /> },
        { path: "logs/:logType", element: <LogsPage /> },
        { path: "settings", element: <SettingsPage /> },
        { path: "accounts", element: <AccountsPage /> },
        { path: "*", element: <RouteRepairRedirect fallback="/superadmin/dashboard" /> },
      ],
    },
    { path: "/", element: <HomeRedirect /> },
    { path: "*", element: <HomeRedirect /> },
  ];
