import type { ButtonHTMLAttributes, ReactNode } from "react";
import { cn } from "../../lib/cn";

type ButtonVariant = "primary" | "secondary" | "ghost" | "destructive";

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  children: ReactNode;
  variant?: ButtonVariant;
  isLoading?: boolean;
  loadingText?: string;
};

const variantClasses: Record<ButtonVariant, string> = {
  primary:
    "border-transparent bg-button-primary-bg text-button-primary-text hover:bg-button-primary-bg-hover active:bg-button-primary-bg-active",
  secondary:
    "border-border bg-surface-raised text-text-primary hover:bg-surface-muted active:bg-gray-200",
  ghost:
    "border-transparent bg-transparent text-text-primary hover:bg-surface-muted active:bg-gray-200",
  destructive:
    "border-transparent bg-danger text-text-inverse hover:bg-danger-hover active:bg-danger-hover",
};

export const Button = ({
  className,
  children,
  variant = "primary",
  isLoading = false,
  loadingText = "Loading",
  disabled,
  ...props
}: ButtonProps) => (
  <button
    className={cn(
      "inline-flex h-11 items-center justify-center gap-2 rounded-md border px-4 text-small font-semibold leading-none",
      "transition-colors duration-150 ease-out",
      "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring",
      "disabled:cursor-not-allowed disabled:border-gray-200 disabled:bg-gray-200 disabled:text-text-muted disabled:opacity-80",
      variantClasses[variant],
      className,
    )}
    disabled={disabled || isLoading}
    aria-busy={isLoading || undefined}
    {...props}
  >
    {isLoading ? (
      <>
        <span
          className="h-4 w-4 animate-spin rounded-full border-2 border-button-primary-text border-t-transparent"
          aria-hidden="true"
        />
        {loadingText}
      </>
    ) : (
      children
    )}
  </button>
);
