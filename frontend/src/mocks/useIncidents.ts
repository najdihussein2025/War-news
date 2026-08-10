import { mockIncidents } from "./mockIncidents";

export const useIncidents = () => ({
  data: mockIncidents,
  isLoading: false,
  isError: false,
});
