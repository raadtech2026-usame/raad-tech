import { useEffect, useRef, useState } from "react";
import { env } from "../../config/env";
/**
 * Audit finding B20 — `MapboxMapProvider` is imported DYNAMICALLY, deliberately, and this must
 * not be "tidied" back into a static import.
 *
 * Mapbox GL is 1.87 MB raw / 521 kB gzipped — by far the largest dependency in this frontend.
 * A static import here puts it in the initial module graph of every page that renders a map,
 * and `app/dashboard/LiveOperationsSection` renders one on the dashboard *home*. That made
 * Mapbox unavoidable for every user on first paint, including Finance Staff who never open a
 * map, and Vite `modulepreload`-ed it from index.html accordingly.
 *
 * Deferring it here rather than at each call site fixes it once for all three importers
 * (LiveOperationsSection, FleetMapPanel, VehicleMapPanel) and keeps the choice of provider
 * exactly where `.claude/rules/frontend.md` #6 already says it belongs: this component is "the
 * one place a concrete provider is named".
 */
import type { LatLng, MapProvider } from "./MapProvider";
import styles from "./MapView.module.css";

export interface MapViewProps {
  center: LatLng;
  zoom: number;
  className?: string;
  /** Called once the provider has mounted, so a caller can add markers/layers via the same
   * imperative `MapProvider` interface — this component owns only mount/unmount lifecycle. */
  onReady?: (provider: MapProvider) => void;
}

/**
 * Thin React wrapper selecting the configured {@link MapProvider} (ADR-0011: currently only
 * `MapboxMapProvider`) — the one place `frontend.md` #6's "pluggable, never hardcoded into
 * feature code" requirement is actually satisfied; every feature consumes this component, never
 * a concrete provider class directly.
 *
 * `className` (from the caller, e.g. `LiveTrackingPage`'s own `.map`) still sizes/positions the
 * *root* element exactly as before — callers rely on this to fill their own layout (absolute
 * `inset: 0` inside a positioned parent, in `LiveTrackingPage`'s case). Internally, the actual
 * Mapbox container and the error banner below are both absolutely-positioned children filling
 * that root, so this root element must establish its own positioning context — `MapView.module.
 * css`'s default `.map` class now sets `position: relative` for exactly that reason; a caller
 * that overrides `className` with its own `position: absolute` class (as `LiveTrackingPage`
 * does) already gets one for free, since `absolute`/`relative`/`fixed`/`sticky` all establish a
 * containing block for absolutely-positioned descendants.
 *
 * **Fails loudly, never a silent blank map.** Previously, a `mount()` rejection (e.g. a missing
 * `VITE_MAPBOX_ACCESS_TOKEN` — the map provider's own real, external prerequisite, matching this
 * codebase's identical "fail loudly, don't fake it" posture for `PaymentProviderPort`/
 * `VideoProviderPort`) had no `.catch()` anywhere in this component, so the failure became a
 * silently-swallowed unhandled promise rejection: `onReady` was never called, and the container
 * div just sat there empty forever with no visible indication anything had gone wrong. Fixed by
 * checking for a configured token up front (a clear, actionable message — this is a deployment
 * prerequisite this repo has never had a real Mapbox account to test against, not a bug in this
 * code) and by catching `mount()` itself failing for any other reason (a real network/auth
 * failure), rendering a visible error state either way.
 */
export function MapView({ center, zoom, className, onReady }: MapViewProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const providerRef = useRef<MapProvider | null>(null);
  const [mountError, setMountError] = useState<string | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    if (!env.mapboxAccessToken) {
      // Checked before ever constructing a provider — a missing token is a configuration
      // prerequisite, not a Mapbox-runtime failure, so this gives a precise, actionable message
      // instead of waiting on Mapbox's own internal "An API access token is required..." error
      // (which still exists as a second line of defense in the .catch() below, in case this
      // check and the provider's own validation ever drift).
      setMountError(
        "Map unavailable: no Mapbox access token is configured (VITE_MAPBOX_ACCESS_TOKEN).",
      );
      return;
    }

    let cancelled = false;
    const container = containerRef.current;

    // The dynamic import IS the deferral — see this module's own note above.
    import("./providers/MapboxMapProvider")
      .then(({ MapboxMapProvider }) => {
        if (cancelled) {
          return;
        }
        const provider = new MapboxMapProvider();
        providerRef.current = provider;
        return provider
          .mount({
            container,
            center,
            zoom,
            accessToken: env.mapboxAccessToken,
          })
          .then(() => provider);
      })
      .then((provider) => {
        if (!provider) {
          return;
        }
        if (!cancelled) {
          setMountError(null);
          onReady?.(provider);
        }
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        const message = error instanceof Error ? error.message : String(error);
        setMountError(`Map failed to load: ${message}`);
      });

    return () => {
      cancelled = true;
      // Read through the ref, not a closure variable: the provider is now created inside an
      // async import, so at cleanup time it may not exist yet (unmount before the chunk
      // finished loading). `cancelled` already stops the import chain from mounting in that
      // case; this just avoids calling `unmount()` on something that was never constructed.
      providerRef.current?.unmount();
      providerRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- mount/unmount once per instance; use onReady's provider handle for live updates, not prop changes.
  }, []);

  return (
    <div className={className ?? styles.map}>
      <div ref={containerRef} className={styles.mapContainer} data-testid="map-view" />
      {mountError && (
        <div className={styles.error} role="alert" data-testid="map-view-error">
          {mountError}
        </div>
      )}
    </div>
  );
}
