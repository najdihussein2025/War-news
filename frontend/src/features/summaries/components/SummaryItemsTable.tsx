import { Link } from "react-router-dom";
import { StatusBadge } from "../../../components/StatusBadge";
import { DataTable, EmptyState, type DataTableColumn } from "../../../components/ui";
import { statusLabel, statusVariant } from "../logic";
import type { SummaryItem, SummaryVillage } from "../types";

const villageName = (village: SummaryVillage | null) => village?.name_ar || village?.name_en || null;

type Props = {
  items: SummaryItem[];
  roleBase: string;
  focusedItemId?: number | null;
  onFocusItem?: (itemId: number | null) => void;
};

export const SummaryItemsTable = ({ items, roleBase, focusedItemId, onFocusItem }: Props) => {
  const columns: Array<DataTableColumn<SummaryItem>> = [
    {
      key: "header",
      header: "Header → condition",
      render: (item) => (
        <div className="space-y-1">
          <p className="text-small text-text-primary" dir="auto">{item.header_text ?? "—"}</p>
          <p className="text-caption text-text-muted">{item.condition ? `${item.condition.name_en} · ${item.condition.name_ar}` : "No condition"}</p>
        </div>
      ),
    },
    {
      key: "location",
      header: "Location",
      render: (item) => <span className="text-small" dir="auto">{item.location_text}</span>,
    },
    {
      key: "village",
      header: "Village",
      render: (item) =>
        item.primary_village ? (
          <div className="space-y-1 text-small">
            <p dir="auto">{villageName(item.primary_village)}</p>
            {item.secondary_village ? (
              <p className="text-caption text-text-muted" dir="auto">or {villageName(item.secondary_village)} (between)</p>
            ) : item.modifier === "outskirts" ? (
              <p className="text-caption text-text-muted">outskirts</p>
            ) : null}
          </div>
        ) : (
          <span className="text-small text-text-muted">Not resolved</span>
        ),
    },
    {
      key: "count",
      header: "Count",
      render: (item) => <span className="tabular-nums">{item.reported_count && item.reported_count > 1 ? `×${item.reported_count}` : "1"}</span>,
    },
    {
      key: "origin",
      header: "Source",
      render: (item) => <StatusBadge label={item.origin === "llm_crosscheck" ? "LLM cross-check" : "Parser"} variant={item.origin === "llm_crosscheck" ? "accent" : "neutral"} />,
    },
    {
      key: "status",
      header: "Status",
      render: (item) => {
        const incidentId = item.matched_incident_id ?? item.created_incident_id;
        const badge = <StatusBadge label={statusLabel(item.display_status)} variant={statusVariant(item.display_status)} />;
        return incidentId ? (
          <Link to={`${roleBase}/incidents/${incidentId}`} className="inline-flex items-center gap-1 underline-offset-2 hover:underline" aria-label={`Open incident (${statusLabel(item.display_status)})`}>
            {badge}
          </Link>
        ) : (
          badge
        );
      },
    },
  ];

  return (
    <div onMouseLeave={() => onFocusItem?.(null)}>
      <DataTable
        columns={columns}
        rows={items}
        getRowKey={(item) => String(item.id)}
        clientSort={false}
        density="compact"
        minWidth="820px"
        onRowClick={(item) => onFocusItem?.(focusedItemId === item.id ? null : item.id)}
        emptyState={<EmptyState title="No items" description="This summary produced no parsed items." />}
      />
    </div>
  );
};
