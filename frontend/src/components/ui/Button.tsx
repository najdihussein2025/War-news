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
    "border-transparent bg-button-primary-bg text-button-primary-text shadow-[0_12px_24px_rgba(8,45,111,0.16)] hover:-translate-y-px hover:bg-button-primary-bg-hover hover:shadow-[0_16px_32px_rgba(8,45,111,0.22)] active:translate-y-0 active:bg-button-primary-bg-active active:shadow-[0_10px_20px_rgba(8,45,111,0.16)]",
  secondary:
    "border-border bg-surface-raised text-text-primary shadow-[0_1px_2px_rgba(11,34,54,0.04)] hover:border-input-border-hover hover:bg-surface hover:shadow-[0_8px_18px_rgba(11,34,54,0.08)] active:bg-surface-muted",
  ghost:
    "border-transparent bg-transparent text-text-primary hover:bg-surface-muted active:bg-gray-200",
  destructive:
    "border-transparent bg-danger text-text-inverse shadow-[0_12px_24px_rgba(155,44,44,0.16)] hover:-translate-y-px hover:bg-danger-hover hover:shadow-[0_16px_30px_rgba(155,44,44,0.22)] active:translate-y-0 active:bg-danger-hover",
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
      "transition-[background-color,border-color,color,box-shadow,transform] duration-150 ease-out",
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
