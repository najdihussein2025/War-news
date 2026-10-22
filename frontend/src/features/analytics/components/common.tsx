import { useEffect, useRef, useState, type ReactNode } from "react";
import { cn } from "../../../lib/cn";
import { Card } from "../../../components/ui/Card";
import { downloadCsv, type CsvCell } from "../csv";

/** Flips to true the first time the element scrolls near the viewport (and stays true). */
export const useInView = (rootMargin = "300px"): [React.RefObject<HTMLDivElement | null>, boolean] => {
  const ref = useRef<HTMLDivElement | null>(null);
  const [seen, setSeen] = useState(typeof IntersectionObserver === "undefined");
  useEffect(() => {
    const node = ref.current;
    if (seen || !node) return undefined;
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting)) {
        setSeen(true);
        observer.disconnect();
      }
    }, { rootMargin });
    observer.observe(node);
    return () => observer.disconnect();
  }, [seen, rootMargin]);
  return [ref, seen];
};

export const Skeleton = ({ className }: { className?: string }) => (
  <div className={cn("animate-pulse rounded-md bg-gray-100", className)} aria-hidden="true" />
);

export const ErrorBlock = ({ message, onRetry }: { message: string; onRetry: () => void }) => (
  <div role="alert" className="flex flex-col items-start gap-2 rounded-md border border-danger/40 bg-red-50 p-4 text-small text-danger">
    <span>{message}</span>
    <button type="button" onClick={onRetry} className="rounded-md border border-danger px-3 py-1 font-semibold hover:bg-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus-ring">Retry</button>
  </div>
);

export const errorMessage = (error: unknown): string => {
  const e = error as { response?: { data?: { detail?: unknown } }; message?: string };
  const detail = e?.response?.data?.detail;
  if (typeof detail === "string") return detail;
  return e?.message || "Something went wrong while loading this section.";
};

export const SectionCard = ({
  title, subtitle, actions, children, className, id,
}: { title: string; subtitle?: string; actions?: ReactNode; children: ReactNode; className?: string; id?: string }) => (
  <Card className={cn("p-3 xl:p-4", className)} id={id} aria-labelledby={id ? `${id}-title` : undefined}>
    <div className="mb-2 flex flex-wrap items-start justify-between gap-2">
      <div className="min-w-0">
        <h2 id={id ? `${id}-title` : undefined} className="text-body font-semibold text-text-primary">{title}</h2>
        {subtitle ? <p className="text-caption text-text-muted">{subtitle}</p> : null}
      </div>
      {actions}
    </div>
    {children}
  </Card>
);

/** "Download CSV" for a chart or table: builds the rows only when clicked. */
export const CsvButton = ({ filename, headers, rows, disabled }: {
  filename: string;
  headers: string[];
  rows: () => CsvCell[][];
  disabled?: boolean;
}) => (
  <button type="button" disabled={disabled} onClick={() => downloadCsv(filename, headers, rows())}
    className="flex h-8 shrink-0 items-center gap-1.5 rounded-md border border-border px-2.5 text-caption font-medium text-text-muted hover:bg-surface-muted hover:text-text-primary disabled:cursor-not-allowed disabled:opacity-40 focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus-ring">
    <svg viewBox="0 0 24 24" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M12 4v11" /><path d="m7 10 5 5 5-5" /><path d="M5 20h14" /></svg>
    Download CSV
  </button>
);

/** Segmented toggle for chart options (aria-pressed buttons). */
export const Toggle = <T extends string>({ label, value, options, onChange }: {
  label: string;
  value: T;
  options: Array<[T, string]>;
  onChange: (value: T) => void;
}) => (
  <div role="group" aria-label={label} className="flex overflow-hidden rounded-md border border-border">
    {options.map(([id, text], i) => (
      <button key={id} type="button" aria-pressed={value === id} onClick={() => onChange(id)}
        className={cn("h-8 px-2.5 text-caption font-medium focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-focus-ring",
          i > 0 && "border-l border-border", value === id ? "bg-brand-navy text-text-inverse" : "hover:bg-surface-muted")}>{text}</button>
    ))}
  </div>
);

/** Short, fixed-height empty state so a section with no data never leaves a large blank card. */
export const EmptyState = ({ children, className }: { children: ReactNode; className?: string }) => (
  <p role="status" className={cn("flex h-20 items-center justify-center rounded-md border border-dashed border-border px-3 text-center text-small text-text-muted", className)}>{children}</p>
);

/**
 * ⓘ button with a popover. It opens on hover and on keyboard focus, and stays open while
 * focus is inside it, so a link in the popover is reachable from the keyboard.
 */
export const InfoTip = ({ label, children, align = "left" }: { label: string; children: ReactNode; align?: "left" | "right" }) => (
  <span className="group/info relative inline-flex">
    <button type="button" aria-label={label}
      className="flex h-6 w-6 items-center justify-center rounded-full text-text-muted hover:bg-surface-muted hover:text-brand-navy focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus-ring">
      <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true"><circle cx="12" cy="12" r="9" /><path d="M12 11v5" /><path d="M12 7.5h.01" /></svg>
    </button>
    <span role="tooltip"
      className={cn("invisible absolute top-full z-30 mt-1 w-64 rounded-md border border-border bg-surface-raised p-3 text-left text-caption font-normal leading-relaxed text-text-primary opacity-0 shadow-overlay transition-opacity duration-150",
        "group-hover/info:visible group-hover/info:opacity-100 group-focus-within/info:visible group-focus-within/info:opacity-100",
        align === "left" ? "left-0" : "right-0")}>
      {children}
    </span>
  </span>
);

export const FamilyDot = ({ color }: { color: string }) => (
  <span className="inline-block h-2.5 w-2.5 shrink-0 rounded-sm" style={{ background: color }} aria-hidden="true" />
);

export const NameCell = ({ en, ar, sub }: { en: string | null; ar: string | null; sub?: string | null }) => (
  <div className="min-w-0">
    <div className="truncate text-small font-medium">{en || ar || "—"}</div>
    <div className="flex items-center gap-2 text-caption text-text-muted">
      {ar && en ? <span dir="rtl" lang="ar">{ar}</span> : null}
      {sub ? <span>{sub}</span> : null}
    </div>
  </div>
);
