import { useEffect } from "react";
import { useRoutes } from "react-router-dom";
import { routes } from "./routes";
import { useAuthStore } from "../stores/authStore";

export const App = () => {
  const hydrateFromStorage = useAuthStore((state) => state.hydrateFromStorage);
  const element = useRoutes(routes);

  useEffect(() => {
    hydrateFromStorage();
  }, [hydrateFromStorage]);

  return element;
};
