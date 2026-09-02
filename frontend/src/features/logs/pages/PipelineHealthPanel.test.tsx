import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import type { PipelineHealth } from "../types";

const mockQuery = vi.fn();
vi.mock("../hooks", () => ({
  usePipelineHealthQuery: () => mockQuery(),
}));

import { PipelineHealthPanel } from "./LogsPage";

const baseHealth = (overrides: Partial<PipelineHealth["cursor_gap"]> = {}): PipelineHealth => ({
  stages: [
    { stage_name: "matching", queue_depth: 3, oldest_waiting_seconds: 3600 },
    { stage_name: "fast_path", queue_depth: 0, oldest_waiting_seconds: null },
  ],
  cursor_gap: {
    sweep_name: "live_sweep_new_only",
    last_processed_id: 2531,
    max_raw_message_id: 2709,
    gap: 178,
    unhealthy: false,
    ...overrides,
  },
  latency: {
    window_hours: 24,
    materialized: { p50_seconds: 120, p95_seconds: 300, p99_seconds: 480, sample_size: 42 },
    terminal_non_materialized: { p50_seconds: null, p95_seconds: null, p99_seconds: null, sample_size: 0 },
  },
});

const asLoaded = (health: PipelineHealth) => ({
  data: health,
  isLoading: false,
  isError: false,
  isFetching: false,
  refetch: vi.fn(),
});

describe("PipelineHealthPanel", () => {
  it("renders every stage, the cursor gap and latency percentiles", () => {
    mockQuery.mockReturnValue(asLoaded(baseHealth()));
    const html = renderToStaticMarkup(<PipelineHealthPanel />);

    expect(html).toContain("matching");
    expect(html).toContain("fast_path");
    expect(html).toContain("live_sweep_new_only");
    expect(html).toContain("Latency percentiles");
    expect(html).toContain("Healthy");
    // Healthy cursor block does not use the danger surface.
    expect(html).not.toContain("border-danger bg-danger/5");
  });

  it("makes the unhealthy cursor gap visually distinct", () => {
    mockQuery.mockReturnValue(asLoaded(baseHealth({ unhealthy: true, gap: 8990 })));
    const html = renderToStaticMarkup(<PipelineHealthPanel />);

    expect(html).toContain("Unhealthy");
    expect(html).toContain("border-danger bg-danger/5");
    expect(html).toContain("text-danger");
  });
});
