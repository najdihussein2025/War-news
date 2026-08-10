import type { LabelHTMLAttributes, ReactNode } from "react";
import { cn } from "../../lib/cn";

type LabelProps = LabelHTMLAttributes<HTMLLabelElement> & {
  children: ReactNode;
};

export const Label = ({ className, children, ...props }: LabelProps) => (
  <label className={cn("block text-small font-semibold text-text-primary", className)} {...props}>
    {children}
  </label>
);
