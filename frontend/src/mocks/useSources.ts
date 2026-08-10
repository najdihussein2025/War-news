import { mockSources } from "./mockSources";

export const useSources = () => ({
  data: mockSources,
  isLoading: false,
  isError: false,
});
