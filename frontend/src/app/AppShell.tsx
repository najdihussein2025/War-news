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
import { ROLES, type Role } from "../constants/roles";
import { cn } from "../lib/cn";
import { useAuthStore } from "../stores/authStore";
import { logout as revokeSession } from "../features/auth/api";

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

const AirViolationsIcon = ({ className }: { className?: string }) => (
  <IconBase className={className}>
    <path d="M3 13h5l4-7 4 12 3-5h2" />
    <path d="M5 19h14" />
    <path d="M7 5h10" />
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

const AccountsIcon = ({ className }: { className?: string }) => (
  <IconBase className={className}>
    <path d="M16 21v-2a4 4 0 0 0-4-4H7a4 4 0 0 0-4 4v2" />
    <circle cx="9.5" cy="7" r="4" />
    <path d="M22 21v-2a4 4 0 0 0-3-3.9" />
    <path d="M16 3.1a4 4 0 0 1 0 7.8" />
  </IconBase>
);

const SettingsIcon = ({ className }: { className?: string }) => (
  <IconBase className={className}>
    <circle cx="12" cy="12" r="3" />
    <path d="M19.4 15a1 1 0 0 0 .2 1.1l.1.1a2 2 0 0 1 0 2.8 2 2 0 0 1-2.8 0l-.1-.1a1 1 0 0 0-1.1-.2 1 1 0 0 0-.6.9V20a2 2 0 0 1-4 0v-.2a1 1 0 0 0-.6-.9 1 1 0 0 0-1.1.2l-.1.1a2 2 0 0 1-2.8 0 2 2 0 0 1 0-2.8l.1-.1a1 1 0 0 0 .2-1.1 1 1 0 0 0-.9-.6H4a2 2 0 0 1 0-4h.2a1 1 0 0 0 .9-.6 1 1 0 0 0-.2-1.1l-.1-.1a2 2 0 0 1 0-2.8 2 2 0 0 1 2.8 0l.1.1a1 1 0 0 0 1.1.2 1 1 0 0 0 .6-.9V4a2 2 0 0 1 4 0v.2a1 1 0 0 0 .6.9 1 1 0 0 0 1.1-.2l.1-.1a2 2 0 0 1 2.8 0 2 2 0 0 1 0 2.8l-.1.1a1 1 0 0 0-.2 1.1 1 1 0 0 0 .9.6H20a2 2 0 0 1 0 4h-.2a1 1 0 0 0-.9.6Z" />
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
  hiddenFrom: Role[];
};

const navItems: NavItem[] = [
  // Operational workspaces are kept as direct navigation destinations.
  {
    label: "Dashboard",
    path: "dashboard",
    icon: ShieldIcon,
    hiddenFrom: [],
  },
  {
    label: "Incidents",
    path: "incidents",
    icon: IncidentsIcon,
    hiddenFrom: [],
  },
  {
    label: "Air Violations",
    path: "air-violations",
    icon: AirViolationsIcon,
    hiddenFrom: [],
  },
  {
    label: "Rejected News",
    path: "rejected-news",
    icon: IncidentsIcon,
    hiddenFrom: [],
  },
  {
    label: "Sources",
    path: "sources",
    icon: SourcesIcon,
    hiddenFrom: [],
  },
  {
    label: "Logs",
    path: "logs/audit",
    icon: LogsIcon,
    hiddenFrom: [],
  },
  {
    label: "Settings",
    path: "settings",
    icon: SettingsIcon,
    hiddenFrom: [],
  },
  {
    label: "Accounts",
    path: "accounts",
    icon: AccountsIcon,
    hiddenFrom: [ROLES.ADMIN],
  },
];

const pageMeta = [
  { match: (pathname: string) => pathname.endsWith("/dashboard"), title: "Dashboard" },
  { match: (pathname: string) => pathname.includes("/air-violations"), title: "Air Violations" },
  { match: (pathname: string) => pathname.includes("/incidents"), title: "Incidents" },
  { match: (pathname: string) => pathname.includes("/rejected-news"), title: "Rejected News" },
  { match: (pathname: string) => pathname.includes("/sources"), title: "Sources" },
  { match: (pathname: string) => pathname.includes("/logs"), title: "Logs" },
  { match: (pathname: string) => pathname.includes("/settings"), title: "Settings" },
  { match: (pathname: string) => pathname.startsWith("/superadmin/accounts"), title: "Accounts" },
];

const focusableSelector =
  'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

const BrandMark = ({ to }: { to: string }) => (
  <Link
    to={to}
    className="block bg-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-focus-ring"
    aria-label="War News 2026 dashboard"
  >
    <span className="flex h-[2.5rem] items-center justify-center gap-3 lg:h-20 lg:gap-4" aria-hidden="true">
      <img
        src="/cnrs-logo-transparent.png"
        alt=""
        className="h-full min-w-0 flex-1 object-contain"
      />
      <img
        src="/ncne-logo-transparent.png"
        alt=""
        className="h-full min-w-0 flex-1 object-contain"
      />
    </span>
    <span className="mt-3 hidden text-center text-small font-semibold uppercase tracking-[0.08em] text-brand-navy lg:block">
      War News 2026
    </span>
  </Link>
);

const RoleBadge = ({ role }: { role: string | null }) => (
  <span className="rounded-md border border-brand-gold bg-brand-gold-soft px-2 py-1 text-caption font-semibold text-brand-navy">
    {role === ROLES.SUPER_ADMIN ? "Super Admin" : "Admin"}
  </span>
);

const SidebarContent = ({
  onNavigate,
  previewRole,
}: {
  onNavigate?: () => void;
  previewRole?: Role;
}) => {
  const location = useLocation();
  const navigate = useNavigate();
  const user = useAuthStore((state) => state.user);
  const role = useAuthStore((state) => state.role);
  const logout = useAuthStore((state) => state.logout);
  const displayRole = role ?? previewRole ?? ROLES.ADMIN;
  const roleBase = displayRole === ROLES.SUPER_ADMIN ? "/superadmin" : "/admin";
  const displayUser = user ?? (displayRole === ROLES.SUPER_ADMIN
    ? { username: "super.admin", displayName: "Super Admin" }
    : { username: "admin", displayName: "Operations Admin" });
  const visibleItems = navItems.filter((item) => !item.hiddenFrom.includes(displayRole));

  const handleLogout = () => {
    void revokeSession().catch(() => undefined);
    logout();
    navigate("/login", { replace: true });
  };

  return (
    <div className="flex min-h-full flex-col bg-white">
      <div className="border-b border-brand-gold px-6 py-6">
        <BrandMark to={`${roleBase}/dashboard`} />
      </div>

      <nav className="flex-1 bg-white px-5 py-6" aria-label="Main navigation">
        <div className="space-y-2">
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
                    ? "border-brand-gold bg-brand-sky/50 font-semibold text-brand-navy"
                    : "border-transparent text-text-muted hover:border-brand-gold/40 hover:bg-brand-sky/20 hover:text-brand-navy",
                )}
              >
                <Icon className="h-4 w-4 shrink-0" aria-hidden="true" />
                <span>{item.label}</span>
              </NavLink>
            );
          })}
        </div>
      </nav>

      <div className="border-t border-border bg-white p-5">
        <div className="p-1">
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

export const AppShell = ({ previewRole }: { previewRole?: Role }) => {
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
    <div className="min-h-screen overflow-x-hidden bg-surface text-text-primary">
      {toast ? <Toast>{toast}</Toast> : null}

      <aside className="fixed inset-y-0 left-0 hidden w-[260px] border-r border-border bg-surface-raised shadow-[2px_0_16px_rgba(8,45,111,0.08)] lg:block">
        <SidebarContent previewRole={previewRole} />
      </aside>

      <div className="min-w-0 lg:pl-[260px]">
        <header className="sticky top-0 z-30 flex h-16 items-center justify-between border-b border-border bg-surface-raised px-4 lg:hidden">
          <BrandMark to={`${location.pathname.startsWith("/superadmin") ? "/superadmin" : "/admin"}/dashboard`} />
          <button
            ref={toggleRef}
            type="button"
            className="flex h-[2.5rem] w-[2.5rem] items-center justify-center rounded-md border border-border bg-white text-brand-navy transition-colors duration-150 ease-out hover:border-brand-gold hover:bg-brand-sky/20 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
            onClick={() => setIsDrawerOpen(true)}
            onKeyDown={handleToggleKeyDown}
            aria-label="Open main navigation"
            aria-expanded={isDrawerOpen}
          >
            <MenuIcon className="h-5 w-5" />
          </button>
        </header>

        <main className="min-h-screen min-w-0 overflow-x-hidden px-3 py-5 sm:px-6 sm:py-6 lg:px-8 lg:py-8">
          <div className="mx-auto max-w-6xl">
            <div className="relative mb-6 flex flex-col gap-4 border-b border-border pb-5 after:absolute after:-bottom-px after:left-0 after:h-1 after:w-16 after:bg-brand-gold sm:flex-row sm:items-center sm:justify-between">
              <div className="flex flex-wrap items-center gap-3">
                <h1 className="text-h2 font-semibold text-brand-navy">{meta.title}</h1>
                {titleAddon}
              </div>
              {pageAction}
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
