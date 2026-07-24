import { useEffect, useRef } from "react";
import { env } from "../../config/env";
import { MapboxMapProvider } from "./providers/MapboxMapProvider";
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
 */
export function MapView({ center, zoom, className, onReady }: MapViewProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const providerRef = useRef<MapProvider | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    const provider = new MapboxMapProvider();
    providerRef.current = provider;
    let cancelled = false;

    provider
      .mount({
        container: containerRef.current,
        center,
        zoom,
        accessToken: env.mapboxAccessToken,
      })
      .then(() => {
        if (!cancelled) onReady?.(provider);
      });

    return () => {
      cancelled = true;
      provider.unmount();
      providerRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- mount/unmount once per instance; use onReady's provider handle for live updates, not prop changes.
  }, []);

  return <div ref={containerRef} className={className ?? styles.map} data-testid="map-view" />;
}
