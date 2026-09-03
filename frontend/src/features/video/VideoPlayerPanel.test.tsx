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
