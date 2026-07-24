# ADR-0011: Mapbox GL JS as the RAAD Map Provider

## Status
Accepted (user decision, resolving `docs/architecture/frontend-flutter-master-roadmap.md` §3.9's
"stop, this needs your decision" map-provider item — the last open Decision Log item blocking
Phase F7). Frontend integration points prepared; F7 (Live Monitoring & Maps) itself is not yet
implemented — this ADR and its accompanying prep work are explicitly infrastructure-only.

## Context
`.claude/rules/frontend.md` #6 and Project Brief §11.8 both require the map to sit behind a
pluggable provider abstraction, never hardcoded into feature code — but *which* provider to
integrate first is a real vendor/product decision (§3.9 named it a "paid external service must be
selected" trigger), not one this codebase could resolve on its own. The roadmap's own §3.9
compared three options without choosing:

| Option | Cost model | Notes |
|---|---|---|
| **Mapbox GL JS** | Free tier (50k loads/mo), paid beyond | Best-in-class vector tiles, smooth realtime marker animation, widely used for fleet-tracking UIs specifically |
| Google Maps Platform | Pay-per-load beyond a small free credit | Most familiar to end users; heavier billing setup |
| MapLibre GL + a free tile source | Free | Zero vendor lock-in, trades polish/support for zero cost |

## Decision
**Mapbox GL JS.** User-confirmed. Reasoning (per the roadmap's own comparison, now acted on):
best-in-class vector tiles and realtime marker animation, the most direct precedent among
fleet-tracking UIs specifically — the exact workload F7 (fleet-wide + per-vehicle live view) needs.

### Frontend integration points prepared this phase
- **`frontend/src/shared/map/`** — the pluggable abstraction `frontend.md` #6 requires:
  - `MapProvider.ts` — the interface every concrete provider implements (`mount`/`unmount`,
    `setCenter`/`setZoom`, `addMarker`/`updateMarker`/`removeMarker`, `fitBounds`,
    `addSource`/`addLayer` for route/stop/geofence overlays) — deliberately shaped around what
    F7's own documented scope names (`GET /tracking/vehicles/{id}/latest` fleet/per-vehicle view,
    route/stop overlay reusing F5's data, geofence display), not a speculative generic map API.
  - `providers/MapboxMapProvider.ts` — the concrete Mapbox GL JS implementation.
  - `MapView.tsx` — a thin React wrapper selecting the configured provider (currently only
    Mapbox is implemented; the selection mechanism itself is what proves this is a real
    abstraction, not a Mapbox-hardcoded component pretending to be one).
- **`mapbox-gl` + `@types/mapbox-gl`** — new frontend dependencies (approved by this same user
  decision; MIT-licensed client library, no server component, the standard way to embed Mapbox GL
  JS in a React app — no lighter alternative achieves vector-tile rendering).
- **`VITE_MAPBOX_ACCESS_TOKEN`** — new env var (`.env.example`), read through `config/env.ts`'s
  existing single-point-of-truth pattern, never `import.meta.env` directly elsewhere.
- **Not built this phase:** the actual F7 live-monitoring pages/vehicle markers/WebSocket wiring.
  `MapView`/`MapboxMapProvider` render a configurable map with markers/overlays as a reusable
  primitive — no tracking-domain logic, no route/nav entry, matching this ADR's own "prepare
  integration points, don't build the feature" scope.

### Backend integration points
**None required.** `tracking`'s existing REST (`GET /tracking/vehicles/{id}/latest`,
`GET /tracking/trips/{id}/positions`) and WebSocket (`/ws/tracking`) contracts already expose
plain decimal-degree `lat`/`lng` (API Contracts §11.2) — exactly what Mapbox GL JS (or any other
provider) consumes directly; no map-vendor-specific transformation, proxy, or new endpoint is
needed on the Business API side. Server-side static map rendering (e.g., for the Reporting
context's PDF exports) is not a documented requirement anywhere and is not invented here — flagged
as genuinely out of scope, not silently built.

## Consequences
- F7's map-provider gate (`docs/architecture/frontend-flutter-master-roadmap.md` §3.9) is now
  resolved — only its *other* gate (roadmap §4A's B1/B2 reaching a working state) remained, and
  B1/B2 are now complete (ADR-0009/ADR-0010).
- A Mapbox account/access token is required for local development and any deployed environment —
  tracked as an operational prerequisite, not a code dependency; `.env.example` documents the
  variable without a real value.
- Switching providers later (e.g., to MapLibre, if Mapbox's free-tier limits ever become a real
  constraint) means writing one new `MapProvider` implementation — no change to any consumer of
  `MapView`, by construction.

## Verification
- `frontend/src/shared/map/__tests__/`: `MapProvider` interface conformance and `MapboxMapProvider`
  unit tests (mocking the `mapbox-gl` library itself — no network/real Mapbox API call in tests).
- Existing frontend test suite continues to pass unmodified.

## References
- `.claude/rules/frontend.md` #6
- `docs/business/Project_Brief_v1.md` §11.8
- `docs/architecture/frontend-flutter-master-roadmap.md` §3.9, §4 (Phase F7)
- `docs/business/RAAD_Phase3.3_API_Contracts_v1.md` §11.2 (`/ws/tracking` wire frame)
