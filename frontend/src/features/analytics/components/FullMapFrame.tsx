import { useLayoutEffect, useRef, type ReactNode } from "react";
import { cn } from "../../../lib/cn";

/** Keep the map mounted while promoting its existing box above the application chrome. */
export const FullMapFrame = ({ full, onClose, toolbar, children }: {
  full: boolean; onClose: () => void; toolbar: ReactNode; children: ReactNode;
}) => {
  const frame = useRef<HTMLDivElement>(null);
  const close = useRef<HTMLButtonElement>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;
  useLayoutEffect(() => {
    if (!full || !frame.current) return;
    const previous = document.activeElement as HTMLElement | null;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    // Make everything outside this branch unavailable to pointer, keyboard and AT.
    const siblings = new Map<HTMLElement, boolean>();
    const isolate = () => {
      let branch: HTMLElement = frame.current!;
      while (branch.parentElement && branch !== document.body) {
        for (const element of Array.from(branch.parentElement.children)) {
          if (element !== branch && element instanceof HTMLElement) {
            if (!siblings.has(element)) siblings.set(element, element.inert);
            element.inert = true;
          }
        }
        branch = branch.parentElement;
      }
    };
    isolate();
    // Area selection can replace the background rankings with a new profile column.
    const observer = new MutationObserver(isolate);
    observer.observe(document.body, { childList: true, subtree: true });
    close.current?.focus({ preventScroll: true });
    const keydown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault(); event.stopPropagation(); onCloseRef.current();
      }
      if (event.key !== "Tab") return;
      const items = Array.from(frame.current?.querySelectorAll<HTMLElement>(
        'button:not([disabled]), input:not([disabled]), select:not([disabled]), a[href], [tabindex="0"]',
      ) ?? []).filter((node) => node.getClientRects().length > 0);
      const first = items[0], last = items[items.length - 1];
      if (event.shiftKey && (document.activeElement === first || document.activeElement === frame.current)) {
        event.preventDefault(); last?.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault(); first?.focus();
      }
    };
    frame.current.addEventListener("keydown", keydown);
    const node = frame.current;
    return () => {
      node.removeEventListener("keydown", keydown);
      observer.disconnect();
      document.body.style.overflow = overflow;
      siblings.forEach((inert, element) => { element.inert = inert; });
      requestAnimationFrame(() => {
        if (previous?.isConnected) previous.focus({ preventScroll: true });
        else node.querySelector<HTMLButtonElement>('[aria-label="View full map"]')?.focus({ preventScroll: true });
      });
    };
  }, [full]);
  return (
    <div ref={frame} role={full ? "dialog" : undefined} aria-modal={full ? true : undefined}
      aria-label={full ? "Full map of Lebanon" : undefined} tabIndex={full ? -1 : undefined}
      className={cn(full ? "fixed inset-0 z-40 bg-surface" : "relative h-full min-w-0")}>
      {children}
      {full ? <>
        <div className="absolute left-3 right-16 top-3 z-30 mx-auto w-fit max-w-[calc(100%-6rem)] rounded-lg border border-border bg-surface-raised p-2 shadow-overlay">{toolbar}</div>
        <button ref={close} type="button" onClick={onClose} aria-label="Close full map"
          className="absolute right-3 top-3 z-30 flex h-9 w-9 items-center justify-center rounded-md border border-border bg-surface-raised shadow-raised hover:bg-surface-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus-ring">
          <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true"><path d="m6 6 12 12M6 18 18 6" /></svg>
        </button>
      </> : null}
    </div>
  );
};
