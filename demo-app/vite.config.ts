import { defineConfig } from "vite";

const api = process.env.API_URL ?? "http://localhost:8000";

// The demo imports the browser SDK straight from source (sdks/typescript/src/browser.ts).
export default defineConfig({
  server: { port: 5174, proxy: { "/sdk": api }, fs: { allow: [".."] } },
});
