import {
  createContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ComponentType,
  type KeyboardEvent as ReactKeyboardEvent,
  type Dispatch,
  type ReactNode,
  type SetStateAction,
} from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { ROLES } from "../constants/roles";
import { cn } from "../lib/cn";
import { useAuthStore } from "../stores/authStore";
import { Button } from "../components/ui";

type IconComponent = ComponentType<{ className?: string }>;
type ShellAction = ReactNode | null;

type ShellContextValue = {
  setPageAction: Dispatch<SetStateAction<ShellAction>>;
  setTitleAddon: Dispatch<SetStateAction<ShellAction>>;
  showToast: (message: string) => void;
};

export const ShellContext = createContext<ShellContextValue | null>(null);

const IconBase = ({
  className,
  children,
}: {
  className?: string;
  children: ReactNode;
}) => (
  <svg
    className={className}
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="2"
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
  >
    {children}
  </svg>
);

const ShieldIcon = ({ className }: { className?: string }) => (
  <IconBase className={className}>
    <path d="M12 3 5 6v5c0 5 3 8 7 10 4-2 7-5 7-10V6l-7-3Z" />
  </IconBase>
);

const IncidentsIcon = ({ className }: { className?: string }) => (
  <IconBase className={className}>
    <path d="M4 6h16" />
    <path d="M4 12h16" />
    <path d="M4 18h10" />
    <path d="M17 16l3 3" />
    <circle cx="16" cy="15" r="2" />
  </IconBase>
);

const SourcesIcon = ({ className }: { className?: string }) => (
  <IconBase className={className}>
    <ellipse cx="12" cy="5" rx="7" ry="3" />
    <path d="M5 5v7c0 1.7 3.1 3 7 3s7-1.3 7-3V5" />
    <path d="M5 12v7c0 1.7 3.1 3 7 3s7-1.3 7-3v-7" />
  </IconBase>
);

const LogsIcon = ({ className }: { className?: string }) => (
  <IconBase className={className}>
    <path d="M6 3h9l3 3v15H6z" />
    <path d="M14 3v4h4" />
    <path d="M9 12h6" />
    <path d="M9 16h6" />
  </IconBase>
);

const ExportIcon = ({ className }: { className?: string }) => (
  <IconBase className={className}>
    <path d="M12 3v12" />
    <path d="m8 11 4 4 4-4" />
    <path d="M5 19h14" />
  </IconBase>
);

const AccountsIcon = ({ className }: { className?: string }) => (
  <IconBase className={className}>
    <path d="M16 21v-2a4 4 0 0 0-4-4H7a4 4 0 0 0-4 4v2" />
    <circle cx="9.5" cy="7" r="4" />
    <path d="M22 21v-2a4 4 0 0 0-3-3.9" />
    <path d="M16 3.1a4 4 0 0 1 0 7.8" />
  </IconBase>
);

const SignOutIcon = ({ className }: { className?: string }) => (
  <IconBase className={className}>
    <path d="M10 17l5-5-5-5" />
    <path d="M15 12H3" />
    <path d="M21 3v18" />
  </IconBase>
);

const MenuIcon = ({ className }: { className?: string }) => (
  <IconBase className={className}>
    <path d="M4 6h16" />
    <path d="M4 12h16" />
    <path d="M4 18h16" />
  </IconBase>
);

const CloseIcon = ({ className }: { className?: string }) => (
  <IconBase className={className}>
    <path d="M18 6 6 18" />
    <path d="m6 6 12 12" />
  </IconBase>
);

type NavItem = {
  label: string;
  path: string;
  icon: IconComponent;
};

const adminNavItems: NavItem[] = [
  {
    label: "Dashboard",
    path: "dashboard",
    icon: ShieldIcon,
  },
  {
    label: "Incidents",
    path: "incidents",
    icon: IncidentsIcon,
  },
  {
    label: "Export",
    path: "export",
    icon: ExportIcon,
  },
];

const superAdminNavItems: NavItem[] = [
  {
    label: "Dashboard",
    path: "dashboard",
    icon: ShieldIcon,
  },
  {
    label: "Incidents",
    path: "incidents",
    icon: IncidentsIcon,
  },
  {
    label: "Sources",
    path: "sources",
    icon: SourcesIcon,
  },
  {
    label: "Logs",
    path: "logs/audit",
    icon: LogsIcon,
  },
  {
    label: "Export",
    path: "export",
    icon: ExportIcon,
  },
  {
    label: "Accounts",
    path: "accounts",
    icon: AccountsIcon,
  },
];

const pageMeta = [
  { match: (pathname: string) => pathname.endsWith("/dashboard"), title: "Dashboard" },
  { match: (pathname: string) => pathname.includes("/incidents"), title: "Incidents" },
  { match: (pathname: string) => pathname.includes("/sources"), title: "Sources" },
  { match: (pathname: string) => pathname.includes("/logs"), title: "Logs" },
  { match: (pathname: string) => pathname.includes("/export"), title: "Export", action: "Export" },
  { match: (pathname: string) => pathname.startsWith("/superadmin/accounts"), title: "Accounts" },
];

const focusableSelector =
  'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

const BrandMark = ({ to }: { to: string }) => (
  <Link
    to={to}
    className="flex items-center gap-3 rounded-md focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-focus-ring"
  >
    <span className="flex h-8 w-8 items-center justify-center rounded-md border border-accent text-accent">
      <ShieldIcon className="h-4 w-4" />
    </span>
    <span className="min-w-0">
      <span className="block text-caption font-semibold uppercase text-text-muted">
        Secure Records
      </span>
      <span className="block truncate text-h4 font-semibold text-text-primary">
        War News 2026
      </span>
    </span>
  </Link>
);

const RoleBadge = ({ role }: { role: string | null }) => (
  <span className="rounded-md border border-border bg-surface-muted px-2 py-1 text-caption font-semibold text-text-muted">
    {role === ROLES.SUPER_ADMIN ? "Super Admin" : "Admin"}
  </span>
);

const SidebarContent = ({
  onNavigate,
  previewRole,
}: {
  onNavigate?: () => void;
  previewRole?: string;
}) => {
  const location = useLocation();
  const navigate = useNavigate();
  const user = useAuthStore((state) => state.user);
  const role = useAuthStore((state) => state.role);
  const logout = useAuthStore((state) => state.logout);
  const isAdminPanel = location.pathname.startsWith("/admin");
  const isSuperAdminPanel = location.pathname.startsWith("/superadmin");
  const displayRole = isAdminPanel ? ROLES.ADMIN : isSuperAdminPanel ? ROLES.SUPER_ADMIN : (role ?? previewRole ?? ROLES.ADMIN);
  const roleBase = displayRole === ROLES.SUPER_ADMIN ? "/superadmin" : "/admin";
  const displayUser = isAdminPanel
    ? { username: "admin", displayName: "Operations Admin" }
    : user ?? (displayRole === ROLES.SUPER_ADMIN
    ? { username: "super.admin", displayName: "Super Admin" }
    : { username: "admin", displayName: "Operations Admin" });
  const visibleItems = displayRole === ROLES.SUPER_ADMIN ? superAdminNavItems : adminNavItems;

  const handleLogout = () => {
    if (!role) {
      navigate("/admin/dashboard", { replace: true });
      return;
    }

    logout();
    navigate("/login", { replace: true });
  };

  return (
    <div className="flex min-h-full flex-col bg-surface-raised">
      <div className="px-6 py-6">
        <BrandMark to={`${roleBase}/dashboard`} />
      </div>

      <nav className="flex-1 px-4" aria-label="Main navigation">
        <div className="space-y-1">
          {visibleItems.map((item) => {
            const Icon = item.icon;
            const to = `${roleBase}/${item.path}`;
            const isActive = location.pathname === to || location.pathname.startsWith(`${to}/`);

            return (
              <NavLink
                key={to}
                to={to}
                onClick={onNavigate}
                aria-current={isActive ? "page" : undefined}
                className={cn(
                  "flex min-h-11 items-center gap-3 rounded-md border-l-4 px-3 py-2 text-small font-medium",
                  "transition-colors duration-150 ease-out",
                  "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring",
                  isActive
                    ? "border-accent bg-surface-muted text-accent"
                    : "border-transparent text-text-muted hover:bg-surface-muted hover:text-text-primary",
                )}
              >
                <Icon className="h-4 w-4 shrink-0" aria-hidden="true" />
                <span>{item.label}</span>
              </NavLink>
            );
          })}
        </div>
      </nav>

      <div className="border-t border-border p-4">
        <div className="rounded-lg border border-border bg-surface p-3">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="truncate text-small font-semibold text-text-primary">
                {displayUser?.displayName || displayUser?.username || "Signed in user"}
              </p>
              <div className="mt-2">
                <RoleBadge role={displayRole} />
              </div>
            </div>
            <button
              type="button"
              onClick={handleLogout}
              className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md text-text-muted transition-colors duration-150 ease-out hover:bg-surface-muted hover:text-danger focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
              aria-label="Sign out"
            >
              <SignOutIcon className="h-4 w-4" />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

const Toast = ({ children }: { children: ReactNode }) => (
  <div
    className="fixed right-4 top-4 z-50 max-w-sm rounded-lg border border-border bg-surface-raised px-4 py-3 text-small font-medium text-text-primary shadow-overlay"
    role="status"
    aria-live="polite"
  >
    {children}
  </div>
);

export const AppShell = ({ previewRole }: { previewRole?: string }) => {
  const location = useLocation();
  const navigate = useNavigate();
  const [isDrawerOpen, setIsDrawerOpen] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const [pageAction, setPageAction] = useState<ShellAction>(null);
  const [titleAddon, setTitleAddon] = useState<ShellAction>(null);
  const toggleRef = useRef<HTMLButtonElement | null>(null);
  const drawerRef = useRef<HTMLDivElement | null>(null);
  const wasDrawerOpenRef = useRef(false);
  const meta = pageMeta.find((item) => item.match(location.pathname)) ?? pageMeta[0];

  const closeDrawer = () => {
    setIsDrawerOpen(false);
  };

  const showToast = (message: string) => {
    setToast(message);
    window.setTimeout(() => setToast(null), 3600);
  };

  const shellContext = useMemo(
    () => ({
      setPageAction,
      setTitleAddon,
      showToast,
    }),
    [],
  );

  const locationToast = useMemo(() => {
    const state = location.state as { toast?: string } | null;
    return state?.toast ?? null;
  }, [location.state]);

  useEffect(() => {
    if (!locationToast) {
      return;
    }

    setToast(locationToast);
    navigate(location.pathname, { replace: true, state: null });
    const timeoutId = window.setTimeout(() => setToast(null), 3600);
    return () => window.clearTimeout(timeoutId);
  }, [location.pathname, locationToast, navigate]);

  useEffect(() => {
    if (!isDrawerOpen) {
      return;
    }

    const drawer = drawerRef.current;
    const focusableElements = Array.from(
      drawer?.querySelectorAll<HTMLElement>(focusableSelector) ?? [],
    );
    focusableElements[0]?.focus();

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        closeDrawer();
        return;
      }

      if (event.key !== "Tab" || focusableElements.length === 0) {
        return;
      }

      const firstElement = focusableElements[0];
      const lastElement = focusableElements[focusableElements.length - 1];

      if (event.shiftKey && document.activeElement === firstElement) {
        event.preventDefault();
        lastElement.focus();
      } else if (!event.shiftKey && document.activeElement === lastElement) {
        event.preventDefault();
        firstElement.focus();
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [isDrawerOpen]);

  useEffect(() => {
    if (wasDrawerOpenRef.current && !isDrawerOpen) {
      toggleRef.current?.focus();
    }
    wasDrawerOpenRef.current = isDrawerOpen;
  }, [isDrawerOpen]);

  const handleToggleKeyDown = (event: ReactKeyboardEvent<HTMLButtonElement>) => {
    if (event.key === "Escape") {
      closeDrawer();
    }
  };

  return (
    <div className="min-h-screen bg-surface text-text-primary">
      {toast ? <Toast>{toast}</Toast> : null}

      <aside className="fixed inset-y-0 left-0 hidden w-[260px] border-r border-border bg-surface-raised shadow-[1px_0_0_rgba(24,33,43,0.04)] lg:block">
        <SidebarContent previewRole={previewRole} />
      </aside>

      <div className="lg:pl-[260px]">
        <header className="sticky top-0 z-30 flex h-16 items-center justify-between border-b border-border bg-surface-raised px-4 lg:hidden">
          <BrandMark to={`${location.pathname.startsWith("/superadmin") ? "/superadmin" : "/admin"}/dashboard`} />
          <button
            ref={toggleRef}
            type="button"
            className="flex h-10 w-10 items-center justify-center rounded-md border border-border bg-surface text-text-primary transition-colors duration-150 ease-out hover:bg-surface-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
            onClick={() => setIsDrawerOpen(true)}
            onKeyDown={handleToggleKeyDown}
            aria-label="Open main navigation"
            aria-expanded={isDrawerOpen}
          >
            <MenuIcon className="h-5 w-5" />
          </button>
        </header>

        <main className="min-h-screen px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
          <div className="mx-auto max-w-6xl">
            <div className="mb-6 flex flex-col gap-4 border-b border-border pb-5 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex flex-wrap items-center gap-3">
                <h1 className="text-h2 font-semibold text-text-primary">{meta.title}</h1>
                {titleAddon}
              </div>
              {pageAction ?? (meta.action ? (
                <Button type="button" className="w-full sm:w-auto">
                  {meta.action}
                </Button>
              ) : null)}
            </div>
            <ShellContext.Provider value={shellContext}>
              <Outlet />
            </ShellContext.Provider>
          </div>
        </main>
      </div>

      <div
        className={cn(
          "fixed inset-0 z-40 bg-gray-900/40 transition-opacity duration-150 ease-out lg:hidden",
          isDrawerOpen ? "opacity-100" : "pointer-events-none opacity-0",
        )}
        onClick={closeDrawer}
        aria-hidden="true"
      />
      <div
        ref={drawerRef}
        className={cn(
          "fixed inset-y-0 left-0 z-50 w-[260px] border-r border-border bg-surface-raised shadow-overlay transition-transform duration-150 ease-out lg:hidden",
          isDrawerOpen ? "translate-x-0" : "-translate-x-full",
        )}
        role="dialog"
        aria-modal="true"
        aria-label="Main navigation"
      >
        <button
          type="button"
          className="absolute right-3 top-3 flex h-9 w-9 items-center justify-center rounded-md text-text-muted transition-colors duration-150 ease-out hover:bg-surface-muted hover:text-text-primary focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
          onClick={closeDrawer}
          aria-label="Close main navigation"
        >
          <CloseIcon className="h-4 w-4" />
        </button>
        <SidebarContent onNavigate={closeDrawer} previewRole={previewRole} />
      </div>
    </div>
  );
};
