import type { HTMLAttributes, ReactNode } from "react";
import { cn } from "../../lib/cn";

type CardProps = HTMLAttributes<HTMLDivElement> & {
  children: ReactNode;
};

export const Card = ({ className, children, ...props }: CardProps) => (
  <div
    className={cn("rounded-lg border border-card-border bg-card-bg shadow-raised", className)}
    {...props}
  >
    {children}
  </div>
);
