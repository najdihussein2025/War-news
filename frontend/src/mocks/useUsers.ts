import { mockUsers } from "./mockUsers";

export const useUsers = () => ({
  data: mockUsers,
  isLoading: false,
  isError: false,
});
