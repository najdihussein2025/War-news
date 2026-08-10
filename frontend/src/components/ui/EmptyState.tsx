import type { ReactNode } from "react";
import { cn } from "../../lib/cn";

type EmptyStateProps = {
  title: string;
  description: string;
  icon?: ReactNode;
  className?: string;
};

export const EmptyState = ({ title, description, icon, className }: EmptyStateProps) => (
  <div className={cn("flex min-h-64 flex-col items-center justify-center px-6 py-10 text-center", className)}>
    {icon ? (
      <div className="mb-4 flex h-10 w-10 items-center justify-center rounded-md border border-border bg-surface-muted text-accent">
        {icon}
      </div>
    ) : null}
    <h2 className="text-h4 font-semibold text-text-primary">{title}</h2>
    <p className="mt-2 max-w-md text-small text-text-muted">{description}</p>
  </div>
);
