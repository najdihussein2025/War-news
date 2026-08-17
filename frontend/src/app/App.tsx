import { useEffect } from "react";
import { useRoutes } from "react-router-dom";
import { createRoutes } from "./routes";
import { useAuthStore } from "../stores/authStore";

const routes = createRoutes();

export const App = () => {
  const hydrateFromStorage = useAuthStore((state) => state.hydrateFromStorage);
  const element = useRoutes(routes);

  useEffect(() => {
    hydrateFromStorage();
  }, [hydrateFromStorage]);

  return element;
};
