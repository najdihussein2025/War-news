import { useEffect, useRef, useState, type ReactNode } from "react";
import { cn } from "../../../lib/cn";
import { Card } from "../../../components/ui/Card";

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
  <Card className={cn("p-4", className)} id={id} aria-labelledby={id ? `${id}-title` : undefined}>
    <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
      <div>
        <h2 id={id ? `${id}-title` : undefined} className="text-h4 font-semibold text-text-primary">{title}</h2>
        {subtitle ? <p className="text-caption text-text-muted">{subtitle}</p> : null}
      </div>
      {actions}
    </div>
    {children}
  </Card>
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
