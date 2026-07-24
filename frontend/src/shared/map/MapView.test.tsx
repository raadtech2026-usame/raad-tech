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

describe("MapView", () => {
  beforeEach(() => {
    mountMock.mockClear();
    unmountMock.mockClear();
  });

  it("mounts the configured provider with the given center/zoom/token and renders a container", async () => {
    render(<MapView center={{ lat: 24.7136, lng: 46.6753 }} zoom={11} />);

    expect(screen.getByTestId("map-view")).toBeInTheDocument();
    await waitFor(() => expect(mountMock).toHaveBeenCalledOnce());
    expect(mountMock).toHaveBeenCalledWith(
      expect.objectContaining({
        center: { lat: 24.7136, lng: 46.6753 },
        zoom: 11,
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
});
