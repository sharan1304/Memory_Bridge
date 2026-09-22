import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In Docker Compose the backend is reachable at http://backend:8000 (the
// service name); locally it's just http://localhost:8000.
const backendUrl = process.env.BACKEND_URL || "http://localhost:8000";

const proxy = {
  "/dashboard": { target: backendUrl, ws: true },
  "/mcp": backendUrl,
};

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    proxy,
  },
  preview: {
    port: 3000,
    proxy,
  },
});
