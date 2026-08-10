import { useEffect, useRef, type ReactNode } from "react";
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

  useEffect(() => {
    const focusableElements = Array.from(
      dialogRef.current?.querySelectorAll<HTMLElement>(focusableSelector) ?? [],
    );
    focusableElements[0]?.focus();

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
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
  }, [onClose]);

  return (
    <div
      className={cn(
        "fixed inset-0 z-50 flex bg-gray-900/40 p-4",
        size === "panel" ? "justify-end p-0" : "items-center justify-center",
      )}
    >
      <section
        ref={dialogRef}
        className={cn(
          "w-full overflow-y-auto rounded-lg border border-border bg-surface-raised p-6 shadow-overlay",
          sizeClasses[size],
        )}
        role="dialog"
        aria-modal="true"
        aria-labelledby="dialog-title"
      >
        <div className="flex items-center justify-between gap-4">
          <h2 id="dialog-title" className="text-h4 font-semibold text-text-primary">
            {title}
          </h2>
          <button
            type="button"
            className="rounded-md px-2 py-1 text-small font-semibold text-text-muted transition-colors duration-150 ease-out hover:bg-surface-muted hover:text-text-primary focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
            onClick={onClose}
          >
            Close
          </button>
        </div>
        <div className="mt-5">{children}</div>
      </section>
    </div>
  );
};
