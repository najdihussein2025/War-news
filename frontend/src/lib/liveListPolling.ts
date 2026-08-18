/** Poll interval for list pages backed by pipeline-materialized DB rows. */
export const LIVE_LIST_POLL_INTERVAL_MS = 30_000;

export const liveListQueryOptions = {
  refetchInterval: LIVE_LIST_POLL_INTERVAL_MS,
  refetchOnWindowFocus: true,
  staleTime: 0,
  // refetchIntervalInBackground defaults to false — polling pauses when the tab is hidden.
} as const;
