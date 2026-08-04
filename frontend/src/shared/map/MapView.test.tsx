import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MapView } from "./MapView";
import type { MapProvider } from "./MapProvider";

const mountMock = vi.fn().mockResolvedValue(undefined);
const unmountMock = vi.fn();

vi.mock("./providers/MapboxMapProvider", () => {
  return {
    // Regular `function`, not an arrow — `new MapboxMapProvider()` needs a real constructor.
    MapboxMapProvider: vi.fn(function MapboxMapProviderCtor() {
      return { mount: mountMock, unmount: unmountMock };
    }),
  };
});

// `config/env.ts` reads `import.meta.env.VITE_MAPBOX_ACCESS_TOKEN` once, at module-import time,
// into a plain object — `vi.stubEnv` (which only affects live `import.meta.env`/`process.env`
// reads) runs too late in a `beforeEach` to change an already-captured value, so the token is
// controlled here instead, the same way `MapboxMapProvider` above is swapped for a fake. The
// getter re-reads `tokenBox.value` on every access, matching plain-object-property semantics the
// real `env.mapboxAccessToken` also has.
const tokenBox: { value: string } = { value: "test-token" };
vi.mock("../../config/env", () => ({
  env: {
    get mapboxAccessToken() {
      return tokenBox.value;
    },
  },
}));

describe("MapView", () => {
  beforeEach(() => {
    mountMock.mockClear();
    mountMock.mockResolvedValue(undefined);
    unmountMock.mockClear();
    tokenBox.value = "test-token";
  });

  it("mounts the configured provider with the given center/zoom/token and renders a container", async () => {
    render(<MapView center={{ lat: 24.7136, lng: 46.6753 }} zoom={11} />);

    expect(screen.getByTestId("map-view")).toBeInTheDocument();
    await waitFor(() => expect(mountMock).toHaveBeenCalledOnce());
    expect(mountMock).toHaveBeenCalledWith(
      expect.objectContaining({
        center: { lat: 24.7136, lng: 46.6753 },
        zoom: 11,
        accessToken: "test-token",
      }),
    );
  });

  it("calls onReady with the mounted provider instance once mount resolves", async () => {
    const onReady = vi.fn();
    render(<MapView center={{ lat: 0, lng: 0 }} zoom={5} onReady={onReady} />);

    await waitFor(() => expect(onReady).toHaveBeenCalledOnce());
    const provider = onReady.mock.calls[0][0] as MapProvider;
    expect(provider).toBeDefined();
  });

  it("unmounts the provider on cleanup", async () => {
    const { unmount } = render(<MapView center={{ lat: 0, lng: 0 }} zoom={5} />);
    await waitFor(() => expect(mountMock).toHaveBeenCalledOnce());
    unmount();
    expect(unmountMock).toHaveBeenCalledOnce();
  });

  it("shows an explicit error and never attempts to mount when no access token is configured", async () => {
    tokenBox.value = "";
    const onReady = vi.fn();

    render(<MapView center={{ lat: 0, lng: 0 }} zoom={5} onReady={onReady} />);

    const alert = await screen.findByTestId("map-view-error");
    expect(alert).toHaveTextContent("Map unavailable: no Mapbox access token is configured");
    expect(mountMock).not.toHaveBeenCalled();
    expect(onReady).not.toHaveBeenCalled();
  });

  it("shows an explicit error when the provider's mount() rejects, instead of failing silently", async () => {
    mountMock.mockRejectedValueOnce(new Error("An API access token is required to use Mapbox GL."));
    const onReady = vi.fn();

    render(<MapView center={{ lat: 0, lng: 0 }} zoom={5} onReady={onReady} />);

    const alert = await screen.findByTestId("map-view-error");
    expect(alert).toHaveTextContent(
      "Map failed to load: An API access token is required to use Mapbox GL.",
    );
    expect(onReady).not.toHaveBeenCalled();
  });
});
