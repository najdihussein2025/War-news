export const DuplicateBadge = ({ isDuplicate }: { isDuplicate: boolean }) => (
  <span className="inline-flex rounded bg-slate-100 px-2 py-1 text-xs font-medium text-slate-700">
    {isDuplicate ? "Duplicate" : "Unique"}
  </span>
);
