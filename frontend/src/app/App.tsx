import { useEffect } from "react";
import { useRoutes } from "react-router-dom";
import { createRoutes } from "./routes";
import { useAuthStore } from "../stores/authStore";

export const App = () => {
  const hydrateFromStorage = useAuthStore((state) => state.hydrateFromStorage);
  const element = useRoutes(createRoutes());

  useEffect(() => {
    hydrateFromStorage();
  }, [hydrateFromStorage]);

  return element;
};
