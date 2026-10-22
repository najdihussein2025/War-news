import { createContext, useContext, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { Link, Outlet } from "react-router-dom";
import { RoleBadge, useSignOut } from "../../../app/AppShell";
import { ROLES } from "../../../constants/roles";
import { useAuthStore } from "../../../stores/authStore";

/** DOM node in the top bar where the page renders its own actions (freshness, export). */
const ActionsSlot = createContext<HTMLElement | null>(null);

export const TopBarActions = ({ children }: { children: ReactNode }) => {
  const target = useContext(ActionsSlot);
  return target ? createPortal(children, target) : null;
};

const focusRing = "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring";

/**
 * Full-width shell for the analytics page: no admin sidebar, a slim sticky top bar
 * with a way back to the dashboard. The role guard wraps this layout in routes.tsx.
 */
export const AnalyticsLayout = () => {
  const role = useAuthStore((state) => state.role);
  const user = useAuthStore((state) => state.user);
  const signOut = useSignOut();
  const [slot, setSlot] = useState<HTMLElement | null>(null);
  const roleBase = role === ROLES.SUPER_ADMIN ? "/superadmin" : "/admin";

  return (
    <div className="min-h-screen overflow-x-clip bg-surface text-text-primary">
      <a href="#analytics-main" className={`sr-only z-50 rounded-md bg-surface-raised px-3 py-2 text-small font-semibold focus:not-sr-only focus:fixed focus:left-3 focus:top-3 ${focusRing}`}>Skip to content</a>
      <header className="sticky top-0 z-30 h-14 border-b border-border bg-surface-raised shadow-[0_1px_0_rgba(8,45,111,0.04)]">
        <div className="mx-auto flex h-full max-w-[1800px] items-center gap-3 px-4 sm:px-6">
          <Link to={`${roleBase}/dashboard`} aria-label="Back to dashboard"
            className={`flex h-8 shrink-0 items-center gap-1.5 rounded-md border border-border px-2.5 text-small font-medium text-brand-navy transition-colors duration-150 hover:border-brand-gold hover:bg-brand-sky/20 ${focusRing}`}>
            <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M19 12H5" /><path d="m12 19-7-7 7-7" /></svg>
            <span className="hidden sm:inline">Dashboard</span>
          </Link>
          <span className="hidden h-8 items-center gap-2 border-l border-border pl-3 md:flex" aria-hidden="true">
            <img src="/cnrs-logo-transparent.png" alt="" className="h-7 w-auto object-contain" />
            <img src="/ncne-logo-transparent.png" alt="" className="h-7 w-auto object-contain" />
          </span>
          <h1 className="shrink-0 text-h4 font-semibold text-brand-navy">Analytics</h1>

          <div ref={setSlot} className="flex min-w-0 flex-1 items-center justify-end gap-2" />

          <div className="flex shrink-0 items-center gap-2 border-l border-border pl-3">
            <div className="hidden min-w-0 text-right xl:block">
              <p className="max-w-[12rem] truncate text-caption font-semibold leading-tight">{user?.displayName || user?.username || "Signed in"}</p>
            </div>
            <span className="hidden lg:inline"><RoleBadge role={role} /></span>
            <button type="button" onClick={signOut} aria-label="Sign out"
              className={`flex h-8 items-center gap-1.5 rounded-md border border-border px-2.5 text-small font-medium text-text-muted transition-colors duration-150 hover:border-danger hover:bg-red-50 hover:text-danger ${focusRing}`}>
              <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M10 17l5-5-5-5" /><path d="M15 12H3" /><path d="M21 3v18" /></svg>
              <span className="hidden 2xl:inline">Sign out</span>
            </button>
          </div>
        </div>
      </header>
      <ActionsSlot.Provider value={slot}>
        <main id="analytics-main" tabIndex={-1} className="mx-auto max-w-[1800px] px-4 pb-8 focus:outline-none sm:px-6">
          <Outlet />
        </main>
      </ActionsSlot.Provider>
    </div>
  );
};
