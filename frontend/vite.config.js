import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In development, calls to /api go to the backend on port 8000 (so no CORS setup is needed).
// To call another address instead, set VITE_API_BASE_URL in .env.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { "/api": "http://localhost:8000" } },
  test: { environment: "node" },
});
