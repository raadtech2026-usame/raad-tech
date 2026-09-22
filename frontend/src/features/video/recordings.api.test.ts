import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../shared/api/client", () => ({
  apiRequest: vi.fn(),
}));

import { apiRequest } from "../../shared/api/client";
import {
  controlPlayback,
  getRecordingSearch,
  requestPlaybackVideo,
  searchRecordings,
} from "./api";

const SEGMENT_WIRE = {
  channel_no: 3,
  start_time: "2026-09-21T08:00:00Z",
  end_time: "2026-09-21T08:30:00Z",
  alarm_flag: 0,
  resource_type: 0,
  stream_type: 0,
  storage_type: 1,
  size_bytes: 104_857_600,
};

const PLAYBACK_SESSION_WIRE = {
  id: "01SESSION000000000000000A",
  organization_id: "01ORG00000000000000000000",
  device_id: "01DEVICE0000000000000000A",
  camera_id: "01CAMERA000000000000000A",
  purpose: "playback",
  requested_by: "01USER00000000000000000A",
  window_start: "2026-09-21T08:00:00Z",
  window_end: "2026-09-21T08:30:00Z",
  status: "requested",
  started_at: null,
  ended_at: null,
  created_at: "2026-09-21T09:00:00Z",
  stream_url: "ws://jt1078-relay:7911/viewer?token=abc123",
  uplink_url: null,
};

describe("recording playback api (ADR-0044)", () => {
  beforeEach(() => {
    vi.mocked(apiRequest).mockReset();
  });

  it("searchRecordings posts the device, camera and window", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce({
      search_id: "01SEARCH0000000000000000A",
      device_id: "01DEVICE0000000000000000A",
      status: "pending",
      segments: null,
    });

    const result = await searchRecordings(
      "01DEVICE0000000000000000A",
      "01CAMERA000000000000000A",
      "2026-09-21T08:00:00Z",
      "2026-09-21T09:00:00Z",
    );

    expect(apiRequest).toHaveBeenCalledWith("/video/recordings/search", {
      method: "POST",
      body: {
        device_id: "01DEVICE0000000000000000A",
        camera_id: "01CAMERA000000000000000A",
        window_start: "2026-09-21T08:00:00Z",
        window_end: "2026-09-21T09:00:00Z",
      },
    });
    expect(result.status).toBe("pending");
    expect(result.segments).toBeNull();
  });

  it("maps every segment field the device reported", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce({
      search_id: "01SEARCH0000000000000000A",
      device_id: "01DEVICE0000000000000000A",
      status: "ready",
      segments: [SEGMENT_WIRE],
    });

    const result = await getRecordingSearch("01SEARCH0000000000000000A");

    expect(apiRequest).toHaveBeenCalledWith(
      "/video/recordings/search/01SEARCH0000000000000000A",
    );
    expect(result.segments).toEqual([
      {
        channelNo: 3,
        startTime: "2026-09-21T08:00:00Z",
        endTime: "2026-09-21T08:30:00Z",
        alarmFlag: 0,
        resourceType: 0,
        streamType: 0,
        storageType: 1,
        sizeBytes: 104_857_600,
      },
    ]);
  });

  it("keeps 'still waiting' distinct from 'the device holds nothing'", async () => {
    // `null` and `[]` mean genuinely different things (ADR-0044 §2); collapsing them would
    // either leave an operator polling an answered question or claim an answer that never came.
    vi.mocked(apiRequest).mockResolvedValueOnce({
      search_id: "s-1",
      device_id: "d-1",
      status: "pending",
      segments: null,
    });
    expect((await getRecordingSearch("s-1")).segments).toBeNull();

    vi.mocked(apiRequest).mockResolvedValueOnce({
      search_id: "s-1",
      device_id: "d-1",
      status: "ready",
      segments: [],
    });
    expect((await getRecordingSearch("s-1")).segments).toEqual([]);
  });

  it("requestPlaybackVideo posts the window and maps the session", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce(PLAYBACK_SESSION_WIRE);

    const result = await requestPlaybackVideo(
      "01DEVICE0000000000000000A",
      "01CAMERA000000000000000A",
      "2026-09-21T08:00:00Z",
      "2026-09-21T08:30:00Z",
    );

    expect(apiRequest).toHaveBeenCalledWith("/video/playback", {
      method: "POST",
      body: {
        device_id: "01DEVICE0000000000000000A",
        camera_id: "01CAMERA000000000000000A",
        window_start: "2026-09-21T08:00:00Z",
        window_end: "2026-09-21T08:30:00Z",
      },
    });
    expect(result.purpose).toBe("playback");
    expect(result.streamUrl).toBe("ws://jt1078-relay:7911/viewer?token=abc123");
  });

  it("controlPlayback sends only the named action when no options are given", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce(PLAYBACK_SESSION_WIRE);

    await controlPlayback("01SESSION000000000000000A", "pause");

    expect(apiRequest).toHaveBeenCalledWith(
      "/video/sessions/01SESSION000000000000000A/playback-control",
      { method: "POST", body: { action: "pause" } },
    );
  });

  it("controlPlayback forwards speed and seek position when given", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce(PLAYBACK_SESSION_WIRE);

    await controlPlayback("01SESSION000000000000000A", "fast_forward", { speed: 4 });

    expect(apiRequest).toHaveBeenCalledWith(
      "/video/sessions/01SESSION000000000000000A/playback-control",
      { method: "POST", body: { action: "fast_forward", speed: 4 } },
    );

    vi.mocked(apiRequest).mockResolvedValueOnce(PLAYBACK_SESSION_WIRE);
    await controlPlayback("01SESSION000000000000000A", "seek", {
      position: "2026-09-21T08:10:00Z",
    });

    expect(apiRequest).toHaveBeenLastCalledWith(
      "/video/sessions/01SESSION000000000000000A/playback-control",
      { method: "POST", body: { action: "seek", position: "2026-09-21T08:10:00Z" } },
    );
  });
});
