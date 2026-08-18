import { useMutation } from "@tanstack/react-query";
import { login, logout } from "./api";
import { useAuthStore } from "../../stores/authStore";

export const useLogin = () => {
  const storeLogin = useAuthStore((state) => state.login);

  return useMutation({
    mutationFn: ({ username, password }: { username: string; password: string }) =>
      login(username, password),
    onSuccess: (data) => {
      storeLogin({
        user: data.user,
        role: data.role,
      });
    },
  });
};

export const useLogout = () => {
  const storeLogout = useAuthStore((state) => state.logout);
  return useMutation({
    mutationFn: logout,
    onSettled: () => {
      storeLogout();
    },
  });
};
