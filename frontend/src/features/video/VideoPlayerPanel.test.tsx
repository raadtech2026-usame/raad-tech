import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { createRef } from "react";
import { VideoPlayerPanel } from "./VideoPlayerPanel";

const IDLE_PLAYER = { state: "idle" as const, errorMessage: null, stalled: false };

function ref() {
  return createRef<HTMLVideoElement>();
}

describe("VideoPlayerPanel", () => {
  it("shows the default idle copy when no overrides are given", () => {
    render(<VideoPlayerPanel phase="idle" requestError={null} player={IDLE_PLAYER} videoRef={ref()} />);
    expect(screen.getByText("Select a device and camera")).toBeInTheDocument();
  });

  it("shows overridden idle copy for a caller with no device-picker step of its own", () => {
    render(
      <VideoPlayerPanel
        phase="idle"
        requestError={null}
        player={IDLE_PLAYER}
        videoRef={ref()}
        idleTitle="Select a camera"
        idleDescription="Choose one of this device's cameras, then press Start Live."
      />,
    );
    expect(screen.getByText("Select a camera")).toBeInTheDocument();
    expect(screen.getByText("Choose one of this device's cameras, then press Start Live.")).toBeInTheDocument();
  });

  it("renders the video element (not an empty state) once connecting or connected", () => {
    render(<VideoPlayerPanel phase="connected" requestError={null} player={IDLE_PLAYER} videoRef={ref()} />);
    expect(screen.getByTestId("live-video")).toBeInTheDocument();
    expect(screen.getByText(/audio isn't available/)).toBeInTheDocument();
  });

  it("keeps the same video element mounted through a freeze so playback can resume", () => {
    const videoRef = ref();
    const { rerender } = render(
      <VideoPlayerPanel phase="connected" requestError={null} player={IDLE_PLAYER} videoRef={videoRef} />,
    );
    const element = screen.getByTestId("live-video");

    rerender(
      <VideoPlayerPanel
        phase="stalled"
        requestError={null}
        player={{ ...IDLE_PLAYER, state: "connected", stalled: true }}
        videoRef={videoRef}
      />,
    );
    expect(screen.getByTestId("live-video")).toBe(element);
    expect(videoRef.current).toBe(element);
    expect(screen.getByTestId("stalled-overlay")).toHaveTextContent("No signal");

    rerender(
      <VideoPlayerPanel phase="connected" requestError={null} player={IDLE_PLAYER} videoRef={videoRef} />,
    );
    expect(screen.getByTestId("live-video")).toBe(element);
    expect(screen.queryByTestId("stalled-overlay")).not.toBeInTheDocument();
  });

  it("says the device is offline, and that video will come back on its own", () => {
    render(<VideoPlayerPanel phase="deviceOffline" requestError={null} player={IDLE_PLAYER} videoRef={ref()} />);
    expect(screen.getByText("Device offline")).toBeInTheDocument();
    expect(screen.getByText(/reconnects automatically/)).toBeInTheDocument();
  });

  it("prefers the request error message over the player's own error message", () => {
    render(
      <VideoPlayerPanel
        phase="error"
        requestError={{ message: "Video access denied.", unavailable: false }}
        player={{ state: "error", errorMessage: "NetworkError: CONNECTING_TIMEOUT", stalled: false }}
        videoRef={ref()}
      />,
    );
    expect(screen.getByText("Video access denied.")).toBeInTheDocument();
  });

  it("falls back to the player's error message when there is no request error", () => {
    render(
      <VideoPlayerPanel
        phase="error"
        requestError={null}
        player={{ state: "error", errorMessage: "NetworkError: CONNECTING_TIMEOUT", stalled: false }}
        videoRef={ref()}
      />,
    );
    expect(screen.getByText("NetworkError: CONNECTING_TIMEOUT")).toBeInTheDocument();
  });

  it("shows the unavailable state for a relay-side close the player can't further distinguish", () => {
    render(<VideoPlayerPanel phase="unavailable" requestError={null} player={IDLE_PLAYER} videoRef={ref()} />);
    expect(screen.getByText("Video is unavailable")).toBeInTheDocument();
  });
});
