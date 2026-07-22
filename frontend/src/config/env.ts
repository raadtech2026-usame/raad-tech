/** Typed access to Vite's `import.meta.env` (see `.env.example`). One place that reads env
 * vars directly — everything else imports from here, never `import.meta.env` itself. */
export const env = {
  apiBaseUrl: import.meta.env.VITE_API_BASE_URL,
  wsBaseUrl: import.meta.env.VITE_WS_BASE_URL,
} as const;
