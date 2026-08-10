import type { ReactNode } from "react";
import { cn } from "../../lib/cn";
import { Label } from "./Label";

type FormFieldProps = {
  id: string;
  label: string;
  children: ReactNode;
  error?: string;
  hint?: string;
  className?: string;
};

export const FormField = ({ id, label, children, error, hint, className }: FormFieldProps) => (
  <div className={cn("space-y-2", className)}>
    <Label htmlFor={id}>{label}</Label>
    {children}
    {error ? (
      <p id={`${id}-error`} className="text-small text-danger">
        {error}
      </p>
    ) : hint ? (
      <p id={`${id}-hint`} className="text-small text-text-muted">
        {hint}
      </p>
    ) : null}
  </div>
);
