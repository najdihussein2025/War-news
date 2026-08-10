import { cn } from "../lib/cn";

type StatusBadgeVariant = "neutral" | "accent" | "success" | "warning" | "danger";

type StatusBadgeProps = {
  label: string;
  variant?: StatusBadgeVariant;
};

const variantClasses: Record<StatusBadgeVariant, string> = {
  neutral: "border-border bg-surface-muted text-text-muted",
  accent: "border-accent bg-surface-muted text-accent",
  success: "border-border bg-surface-muted text-success",
  warning: "border-border bg-surface-muted text-warning",
  danger: "border-border bg-surface-muted text-danger",
};

export const StatusBadge = ({ label, variant = "neutral" }: StatusBadgeProps) => (
  <span
    className={cn(
      "inline-flex items-center rounded-md border px-2 py-1 text-caption font-semibold",
      variantClasses[variant],
    )}
  >
    {label}
  </span>
);
