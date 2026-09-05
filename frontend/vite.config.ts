import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    /**
     * Hot reload across a Docker bind mount on Windows/macOS needs polling.
     *
     * `docker-compose.dev.yml` bind-mounts the host's `frontend/` into the container so an edit
     * is visible instantly without an image rebuild. The file *contents* do cross that boundary
     * correctly - but the inotify events chokidar relies on do not, so Vite never learns the file
     * changed and keeps serving its cached transform. The failure is silent and genuinely
     * misleading: the container has the new bytes on disk, `docker exec grep` finds them, and the
     * dev server still serves the old module to the browser.
     *
     * Opt-in via env var rather than always-on: polling wakes the CPU on an interval, and a
     * developer running Vite natively on the host needs none of it. `docker-compose.dev.yml` sets
     * CHOKIDAR_USEPOLLING for the containerised case only.
     */
    watch: process.env.CHOKIDAR_USEPOLLING
      ? { usePolling: true, interval: 300 }
      : undefined,
  },
  build: {
    rollupOptions: {
      output: {
        /**
         * Audit finding B20 — the whole dashboard previously shipped as ONE 2.86 MB JavaScript
         * chunk (789 kB gzipped), so every user downloaded and parsed the Mapbox GL renderer,
         * the mpegts.js video demuxer and the Stripe SDK before the login form could paint —
         * including a Finance Staff user who will never open a map or a video feed.
         *
         * Split by *why a dependency is loaded*, not by arbitrary size. Each group below is a
         * genuinely optional capability that a given session may never touch, so splitting them
         * out is what actually removes bytes from the critical path rather than just moving
         * them between files:
         *
         *   - `mapbox`  — only Live Tracking / Fleet Overview render a map.
         *   - `video`   — only the Vehicle Operations and Live Video surfaces play a stream.
         *   - `stripe`  — only the Org Billing pay-invoice dialog, and only for one role.
         *   - `vendor`  — React and the router, which every route genuinely needs, kept in one
         *                 long-cache-lived chunk so a routine application change does not
         *                 invalidate the framework bundle in every user's browser.
         *
         * Deliberately NOT a `node_modules`-wide catch-all chunk: that produces one enormous
         * "vendor" file again and re-creates the exact problem this fixes.
         */
        manualChunks(id) {
          if (!id.includes("node_modules")) {
            return undefined;
          }
          if (id.includes("mapbox-gl")) {
            return "mapbox";
          }
          if (id.includes("mpegts.js") || id.includes("media-chrome")) {
            return "video";
          }
          if (id.includes("@stripe")) {
            return "stripe";
          }
          if (
            id.includes("/react/") ||
            id.includes("/react-dom/") ||
            id.includes("react-router")
          ) {
            return "vendor";
          }
          return undefined;
        },
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
  },
});
