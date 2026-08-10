import type { InputHTMLAttributes, ReactNode } from "react";
import { cn } from "../../lib/cn";

type InputProps = InputHTMLAttributes<HTMLInputElement> & {
  leadingElement?: ReactNode;
  trailingElement?: ReactNode;
};

export const Input = ({ className, leadingElement, trailingElement, ...props }: InputProps) => (
  <div className="relative">
    {leadingElement ? (
      <div className="pointer-events-none absolute inset-y-0 left-3 flex items-center text-text-muted">
        {leadingElement}
      </div>
    ) : null}
    <input
      className={cn(
        "h-11 w-full rounded-md border border-input-border bg-input-bg px-3 text-body text-text-primary",
        "placeholder:text-text-muted",
        "transition-colors duration-150 ease-out",
        "hover:border-input-border-hover",
        "focus:border-input-border-focus focus:bg-surface focus:outline-none focus:ring-2 focus:ring-focus-ring focus:ring-offset-1 focus:ring-offset-surface-raised",
        "disabled:cursor-not-allowed disabled:bg-gray-100 disabled:text-text-muted",
        leadingElement ? "pl-10" : "",
        trailingElement ? "pr-10" : "",
        className,
      )}
      {...props}
    />
    {trailingElement ? (
      <div className="absolute inset-y-0 right-2 flex items-center">{trailingElement}</div>
    ) : null}
  </div>
);
