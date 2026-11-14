import { useEffect, useRef, useState } from "react";
import { env } from "../../config/env";
import type { LatLng, MapProvider } from "./MapProvider";
import { getActiveMapProvider, type MapProviderName } from "./mapSettings";
import styles from "./MapView.module.css";

export interface MapViewProps {
  center: LatLng;
  zoom: number;
  className?: string;
  /** Optional override to force a specific provider instance. Defaults to active platform setting. */
  provider?: MapProviderName;
  /** Called once the provider has mounted, so a caller can add markers/layers via the same
   * imperative `MapProvider` interface — this component owns only mount/unmount lifecycle. */
  onReady?: (provider: MapProvider) => void;
}

/**
 * Pluggable React wrapper selecting the configured {@link MapProvider} (Mapbox or Google Maps).
 * Features consume this component and interact exclusively with the `MapProvider` abstraction.
 */
export function MapView({ center, zoom, className, provider: overrideProvider, onReady }: MapViewProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const providerRef = useRef<MapProvider | null>(null);
  const [mountError, setMountError] = useState<string | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    let cancelled = false;
    const container = containerRef.current;

    async function initMap() {
      try {
        const activeProvider = overrideProvider ?? (await getActiveMapProvider());
        if (cancelled) return;

        const isGoogle = activeProvider === "google" || activeProvider === "google_maps";

        if (isGoogle) {
          if (!env.googleMapsApiKey) {
            setMountError(
              "Map unavailable: no Google Maps API key is configured (VITE_GOOGLE_MAPS_API_KEY).",
            );
            return;
          }

          const { GoogleMapsMapProvider } = await import("./providers/GoogleMapsMapProvider");
          if (cancelled) return;

          const provider = new GoogleMapsMapProvider();
          providerRef.current = provider;
          await provider.mount({
            container,
            center,
            zoom,
            accessToken: env.googleMapsApiKey,
          });

          if (!cancelled) {
            setMountError(null);
            onReady?.(provider);
          }
        } else {
          // Default: Mapbox GL JS provider
          if (!env.mapboxAccessToken) {
            setMountError(
              "Map unavailable: no Mapbox access token is configured (VITE_MAPBOX_ACCESS_TOKEN).",
            );
            return;
          }

          const { MapboxMapProvider } = await import("./providers/MapboxMapProvider");
          if (cancelled) return;

          const provider = new MapboxMapProvider();
          providerRef.current = provider;
          await provider.mount({
            container,
            center,
            zoom,
            accessToken: env.mapboxAccessToken,
          });

          if (!cancelled) {
            setMountError(null);
            onReady?.(provider);
          }
        }
      } catch (error: unknown) {
        if (cancelled) return;
        const message = error instanceof Error ? error.message : String(error);
        setMountError(`Map failed to load: ${message}`);
      }
    }

    initMap();

    return () => {
      cancelled = true;
      providerRef.current?.unmount();
      providerRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- mount/unmount once per instance; use onReady's provider handle for live updates, not prop changes.
  }, [overrideProvider]);

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
