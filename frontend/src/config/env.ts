/** Typed access to Vite's `import.meta.env` (see `.env.example`). One place that reads env
 * vars directly — everything else imports from here, never `import.meta.env` itself. */
export const env = {
  apiBaseUrl: import.meta.env.VITE_API_BASE_URL,
  wsBaseUrl: import.meta.env.VITE_WS_BASE_URL,
  /** ADR-0011 (Mapbox GL JS). Required only by `shared/map/providers/MapboxMapProvider` — an
   * empty/missing value fails loudly at `MapProvider.mount()` time (a real Mapbox account/token
   * is an operational prerequisite, never a fallback-to-fake value). */
  mapboxAccessToken: import.meta.env.VITE_MAPBOX_ACCESS_TOKEN,
  /** ADR-0022. Stripe's own *publishable* key — safe, by design, to ship to the browser (unlike
   * the backend's secret key, which stays `RAAD_PAYMENT__PROVIDER_CREDENTIALS`-only, never
   * returned by any API). `OrgBillingPage`'s "Pay Invoice" flow only mounts Stripe Elements when
   * both this is set *and* `GET /admin/settings`'s `billing_payment_provider` reads `"stripe"` —
   * an empty value here fails loudly at that mount point, never a silent fallback. */
  stripePublishableKey: import.meta.env.VITE_STRIPE_PUBLISHABLE_KEY,
} as const;
