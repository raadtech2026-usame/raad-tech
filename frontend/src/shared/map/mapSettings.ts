import { apiRequest } from "../api/client";

export type MapProviderName = "mapbox" | "google_maps" | "google";

let cachedProvider: MapProviderName | null = null;
let pendingPromise: Promise<MapProviderName> | null = null;

/**
 * Fetches the active platform map provider ("mapbox" or "google_maps").
 * Caches in-memory to prevent repeated network roundtrips during component mounts.
 */
export async function getActiveMapProvider(): Promise<MapProviderName> {
  if (cachedProvider) {
    return cachedProvider;
  }
  if (pendingPromise) {
    return pendingPromise;
  }

  pendingPromise = (async () => {
    try {
      const response = await apiRequest<{ provider?: string }>("/config/map-provider");
      const provider = (response?.provider?.toLowerCase() as MapProviderName) || "mapbox";
      cachedProvider = provider;
      return provider;
    } catch {
      // If config route is unreachable or default is active, fallback safely to "mapbox"
      return "mapbox";
    } finally {
      pendingPromise = null;
    }
  })();

  return pendingPromise;
}

/**
 * Manually updates the cached map provider (called when the Founder toggles the setting).
 */
export function setCachedMapProvider(provider: MapProviderName): void {
  cachedProvider = provider;
}
