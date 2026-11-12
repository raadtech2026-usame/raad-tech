import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./app/App";
import "./styles/global.css";

/**
 * Handle stale chunk dynamic import failures caused by new production deployments.
 * When a new build is deployed to production, previous chunk hashes are removed.
 * If a user with an existing open session navigates to a lazy route (e.g. Live Tracking),
 * Vite throws "Failed to fetch dynamically imported module". Vite dispatches 'vite:preloadError'
 * on window; auto-reloading fetches the latest index.html and its fresh asset graph seamlessly.
 */
window.addEventListener("vite:preloadError", () => {
  const reloadKey = "raad_chunk_reload_ts";
  const lastReload = Number(sessionStorage.getItem(reloadKey) || 0);
  const now = Date.now();
  if (now - lastReload > 10_000) {
    sessionStorage.setItem(reloadKey, String(now));
    window.location.reload();
  }
});

const rootElement = document.getElementById("root");
if (!rootElement) {
  throw new Error("#root element not found in index.html");
}

createRoot(rootElement).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
