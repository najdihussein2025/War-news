import type { ReactNode } from "react";

export const Table = ({ children }: { children: ReactNode }) => (
  <div className="overflow-hidden rounded border border-slate-200 bg-white">
    <table className="min-w-full divide-y divide-slate-200 text-sm">{children}</table>
  </div>
);
