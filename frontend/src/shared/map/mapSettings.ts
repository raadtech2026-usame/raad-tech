import { apiRequest } from "../api/client";

export type MapProviderName = "mapbox" | "google_maps" | "google";

export interface MapPlatformConfig {
  provider: MapProviderName;
  apiKey?: string;
}

let cachedConfig: MapPlatformConfig | null = null;
let pendingPromise: Promise<MapPlatformConfig> | null = null;

/**
 * Fetches the active platform map provider ("mapbox" or "google_maps") and optional API key.
 * Caches in-memory to prevent repeated network roundtrips during component mounts.
 */
export async function getActiveMapConfig(): Promise<MapPlatformConfig> {
  if (cachedConfig) {
    return cachedConfig;
  }
  if (pendingPromise) {
    return pendingPromise;
  }

  pendingPromise = (async () => {
    try {
      const response = await apiRequest<{ provider?: string; apiKey?: string }>("/config/map-provider");
      const provider = (response?.provider?.toLowerCase() as MapProviderName) || "mapbox";
      const config: MapPlatformConfig = {
        provider,
        apiKey: response?.apiKey || undefined,
      };
      cachedConfig = config;
      return config;
    } catch {
      // If config route is unreachable or default is active, fallback safely to "mapbox"
      return { provider: "mapbox" };
    } finally {
      pendingPromise = null;
    }
  })();

  return pendingPromise;
}

export async function getActiveMapProvider(): Promise<MapProviderName> {
  const config = await getActiveMapConfig();
  return config.provider;
}

/**
 * Manually updates the cached map provider and key (called when the Founder toggles the setting).
 */
export function setCachedMapProvider(provider: MapProviderName, apiKey?: string): void {
  cachedConfig = { provider, apiKey };
}
