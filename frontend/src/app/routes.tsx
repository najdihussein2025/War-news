import { Navigate, Outlet, type RouteObject } from "react-router-dom";
import { ROLES, type Role } from "../constants/roles";
import { useAuthStore } from "../stores/authStore";
import { LoginPage } from "../features/auth/pages/LoginPage";
import { ReviewQueuePage } from "../features/news/pages/ReviewQueuePage";
import { IncidentDetailPage } from "../features/news/pages/IncidentDetailPage";
import { AllNewsPage } from "../features/news/pages/AllNewsPage";
import { SourcesPage } from "../features/sources/pages/SourcesPage";
import { AccountsPage } from "../features/accounts/pages/AccountsPage";
import { LogsPage } from "../features/logs/pages/LogsPage";
import { ExportPage } from "../features/export/pages/ExportPage";

const AuthGuard = () => {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  return isAuthenticated ? <Outlet /> : <Navigate to="/login" replace />;
};

const RoleGuard = ({ allowedRoles }: { allowedRoles: Role[] }) => {
  const role = useAuthStore((state) => state.role);
  return role && allowedRoles.includes(role) ? (
    <Outlet />
  ) : (
    <Navigate to="/forbidden" replace />
  );
};

const ForbiddenPage = () => (
  <main className="mx-auto flex min-h-screen max-w-4xl flex-col justify-center px-6">
    <p className="text-sm font-medium uppercase tracking-wide text-red-600">
      Forbidden
    </p>
    <h1 className="mt-2 text-3xl font-semibold text-slate-950">
      You do not have access to this area.
    </h1>
  </main>
);

export const routes: RouteObject[] = [
  { path: "/login", element: <LoginPage /> },
  {
    element: <AuthGuard />,
    children: [
      { index: true, element: <Navigate to="/review" replace /> },
      { path: "/review", element: <ReviewQueuePage /> },
      { path: "/incidents/:incidentId", element: <IncidentDetailPage /> },
      { path: "/news", element: <AllNewsPage /> },
      { path: "/sources", element: <SourcesPage /> },
      { path: "/logs", element: <LogsPage /> },
      { path: "/export", element: <ExportPage /> },
      { path: "/forbidden", element: <ForbiddenPage /> },
      {
        element: <RoleGuard allowedRoles={[ROLES.SUPER_ADMIN]} />,
        children: [{ path: "/accounts", element: <AccountsPage /> }],
      },
    ],
  },
  { path: "*", element: <Navigate to="/review" replace /> },
];
