import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");

  return {
    plugins: [react()],
    server: {
      watch: {
        // Docker Desktop does not reliably forward Windows bind-mount events.
        usePolling: process.env.VITE_USE_POLLING === "true",
        interval: 500,
      },
      proxy: {
        "/api": {
          target:
            process.env.VITE_API_PROXY_TARGET ||
            env.VITE_API_PROXY_TARGET ||
            "http://localhost:8000",
          changeOrigin: true,
        },
      },
    },
  };
});
