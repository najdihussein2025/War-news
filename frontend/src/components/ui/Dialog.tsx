import { useEffect, useId, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { cn } from "../../lib/cn";

type DialogProps = {
  title: string;
  children: ReactNode;
  onClose: () => void;
  size?: "md" | "lg" | "xl" | "panel";
};

const focusableSelector =
  'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

const sizeClasses = {
  md: "max-w-lg",
  lg: "max-w-2xl",
  xl: "max-w-4xl",
  panel: "ml-auto h-full max-w-3xl rounded-none border-y-0 border-r-0",
};

export const Dialog = ({ title, children, onClose, size = "md" }: DialogProps) => {
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const titleId = useId();

  useEffect(() => {
    const previouslyFocused = document.activeElement as HTMLElement | null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    dialogRef.current?.querySelector<HTMLElement>(focusableSelector)?.focus();

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
        return;
      }

      const focusableElements = Array.from(dialogRef.current?.querySelectorAll<HTMLElement>(focusableSelector) ?? []);
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
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      document.body.style.overflow = previousOverflow;
      previouslyFocused?.focus();
    };
  }, [onClose]);

  return createPortal(
    <div
      className={cn(
        "fixed inset-0 z-50 flex bg-gray-950/65 p-4 backdrop-blur-sm",
        size === "panel" ? "justify-end p-0" : "items-center justify-center",
      )}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <section
        ref={dialogRef}
        className={cn(
          "flex max-h-[calc(100vh-2rem)] w-full flex-col overflow-hidden rounded-xl border-2 border-border bg-surface-raised shadow-overlay",
          sizeClasses[size],
        )}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
      >
        <div className="flex shrink-0 items-center justify-between gap-4 border-b border-border bg-surface-raised px-6 py-4">
          <div>
            <p className="text-caption font-semibold uppercase tracking-wide text-accent">View details</p>
            <h2 id={titleId} className="mt-1 text-h4 font-semibold text-text-primary">
            {title}
            </h2>
          </div>
          <button
            type="button"
            className="inline-flex h-8 items-center gap-1 rounded-md border border-border bg-surface px-2 text-caption font-semibold text-text-primary transition-colors duration-150 ease-out hover:bg-surface-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
            onClick={onClose}
            aria-label="Close details"
          >
            <span aria-hidden="true" className="text-base leading-none">×</span>
            Close
          </button>
        </div>
        <div className="min-h-0 overflow-y-auto px-6 py-5">{children}</div>
      </section>
    </div>,
    document.body,
  );
};
