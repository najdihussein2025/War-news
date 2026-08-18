type RefetchResult = { isError: boolean };
type Refetch = () => Promise<RefetchResult>;

export const refreshDashboardQueries = async (queries: Refetch[]): Promise<boolean> => {
  const results = await Promise.allSettled(queries.map((refetch) => refetch()));
  return results.some((result) => result.status === "rejected" || result.value.isError);
};
