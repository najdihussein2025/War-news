import { useState, type ReactNode } from "react";
import { cn } from "../../lib/cn";
import { Card } from "./Card";

export type SortDirection = "asc" | "desc";

export type DataTableColumn<T> = {
  key: string;
  header: string;
  render: (row: T) => ReactNode;
  sortValue?: (row: T) => string | number | boolean | null;
  className?: string;
};

type DataTableProps<T> = {
  columns: Array<DataTableColumn<T>>;
  rows: T[];
  getRowKey: (row: T) => string;
  actions?: (row: T) => ReactNode;
  onRowClick?: (row: T) => void;
  minWidth?: string;
  loading?: boolean;
  error?: boolean;
  emptyState: ReactNode;
  errorState?: ReactNode;
  initialSort?: { key: string; direction: SortDirection };
  clientSort?: boolean;
};

const SortIcon = ({ active, direction }: { active: boolean; direction: SortDirection }) => (
  <svg
    className="ml-2 h-3.5 w-3.5 text-text-muted"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="2"
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
  >
    {active && direction === "asc" ? (
      <>
        <path d="m7 9 5-5 5 5" />
        <path d="M12 4v16" />
      </>
    ) : active ? (
      <>
        <path d="m7 15 5 5 5-5" />
        <path d="M12 4v16" />
      </>
    ) : (
      <>
        <path d="m8 7 4-4 4 4" />
        <path d="m8 17 4 4 4-4" />
        <path d="M12 3v18" />
      </>
    )}
  </svg>
);

const LoadingRows = ({ columns }: { columns: number }) => (
  <>
    {Array.from({ length: 6 }).map((_, rowIndex) => (
      <tr className="border-b border-border" key={rowIndex}>
        {Array.from({ length: columns }).map((__, columnIndex) => (
          <td className="px-4 py-4" key={columnIndex}>
            <div className="h-5 w-full rounded-md bg-surface-muted" />
          </td>
        ))}
      </tr>
    ))}
  </>
);

export const DataTable = <T,>({
  columns,
  rows,
  getRowKey,
  actions,
  onRowClick,
  minWidth = "760px",
  loading = false,
  error = false,
  emptyState,
  errorState,
  initialSort,
  clientSort = true,
}: DataTableProps<T>) => {
  const firstSortable = columns.find((column) => column.sortValue);
  const [sort, setSort] = useState<{ key: string; direction: SortDirection } | null>(
    initialSort ?? (firstSortable ? { key: firstSortable.key, direction: "asc" } : null),
  );

  const sortedRows = clientSort ? [...rows].sort((a, b) => {
    const column = columns.find((item) => item.key === sort?.key);
    if (!column?.sortValue || !sort) {
      return 0;
    }

    const aValue = column.sortValue(a);
    const bValue = column.sortValue(b);
    const result =
      typeof aValue === "number" && typeof bValue === "number"
        ? aValue - bValue
        : String(aValue ?? "").localeCompare(String(bValue ?? ""));

    return sort.direction === "asc" ? result : -result;
  }) : rows;

  const handleSort = (key: string) => {
    setSort((current) => ({
      key,
      direction: current?.key === key && current.direction === "asc" ? "desc" : "asc",
    }));
  };

  if (error) {
    return <Card>{errorState}</Card>;
  }

  if (!loading && sortedRows.length === 0) {
    return <Card>{emptyState}</Card>;
  }

  return (
    <Card className="overflow-hidden">
      <div className="hidden overflow-x-auto md:block">
        <table className="w-full border-collapse" style={{ minWidth }} aria-busy={loading}>
          <thead className="sticky top-0 z-10 bg-surface-raised">
            <tr className="border-b border-border">
              {columns.map((column) => (
                <th className={cn("px-4 py-3 text-left", column.className)} key={column.key} aria-sort={clientSort && column.sortValue && sort?.key === column.key ? (sort.direction === "asc" ? "ascending" : "descending") : undefined}>
                  {clientSort && column.sortValue ? (
                    <button
                      type="button"
                      className="inline-flex items-center text-left text-caption font-semibold uppercase text-text-muted transition-colors duration-150 ease-out hover:text-text-primary focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
                      onClick={() => handleSort(column.key)}
                    >
                      {column.header}
                      <SortIcon active={sort?.key === column.key} direction={sort?.direction ?? "asc"} />
                    </button>
                  ) : (
                    <span className="text-caption font-semibold uppercase text-text-muted">
                      {column.header}
                    </span>
                  )}
                </th>
              ))}
              {actions ? (
                <th className="px-4 py-3 text-right text-caption font-semibold uppercase text-text-muted">
                  Actions
                </th>
              ) : null}
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {loading ? (
              <LoadingRows columns={columns.length + (actions ? 1 : 0)} />
            ) : (
              sortedRows.map((row) => (
                <tr
                  key={getRowKey(row)}
                  className={cn(
                    "transition-colors duration-150 ease-out hover:bg-surface-muted",
                    onRowClick && "cursor-pointer",
                  )}
                  onClick={() => onRowClick?.(row)}
                  onKeyDown={(event) => {
                    if (onRowClick && (event.key === "Enter" || event.key === " ")) {
                      event.preventDefault();
                      onRowClick(row);
                    }
                  }}
                  tabIndex={onRowClick ? 0 : undefined}
                >
                  {columns.map((column) => (
                    <td className={cn("px-4 py-4 align-top text-small", column.className)} key={column.key}>
                      {column.render(row)}
                    </td>
                  ))}
                  {actions ? (
                    <td className="relative px-4 py-4 text-right align-top" onClick={(event) => event.stopPropagation()}>
                      {actions(row)}
                    </td>
                  ) : null}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
      <div className="divide-y divide-border md:hidden" aria-busy={loading}>
        {loading ? (
          <div className="space-y-3 p-4">
            {Array.from({ length: 4 }).map((_, index) => <div className="h-20 animate-pulse rounded-md bg-surface-muted" key={index} />)}
          </div>
        ) : sortedRows.map((row) => (
          <article className="space-y-3 p-4" key={getRowKey(row)}>
            {columns.map((column) => (
              <div className="grid grid-cols-[7rem_minmax(0,1fr)] gap-3" key={column.key}>
                <p className="text-caption font-semibold uppercase text-text-muted">{column.header}</p>
                <div className="min-w-0 text-small text-text-primary">{column.render(row)}</div>
              </div>
            ))}
            {actions ? <div className="flex justify-end border-t border-border pt-3">{actions(row)}</div> : null}
          </article>
        ))}
      </div>
    </Card>
  );
};
