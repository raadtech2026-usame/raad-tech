import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../shared/api/client", () => ({
  apiRequest: vi.fn(),
}));

import { apiRequest } from "../../shared/api/client";
import { listDevicesForVideoPicker, requestLiveVideo, stopVideoSession } from "./api";

const DEVICE_WITH_CAMERA_WIRE = {
  id: "01DEVICE0000000000000000A",
  organization_id: "01ORG00000000000000000000",
  terminal_id: "TERM12345678",
  model: "LSZ-C5804DG-Q-F",
  vendor: "LSZ",
  sim_msisdn: "+252611111111",
  imei: null,
  iccid: null,
  serial_number: null,
  lifecycle_state: "assigned",
  last_seen_at: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  cameras: [
    { id: "01CAMERA000000000000000A", channel_no: 1, position: "road_facing", label: "Front" },
  ],
};

const DEVICE_WITHOUT_CAMERA_WIRE = {
  ...DEVICE_WITH_CAMERA_WIRE,
  id: "01DEVICE0000000000000000B",
  terminal_id: "TERM99999999",
  cameras: [],
};

const SESSION_WIRE = {
  id: "01SESSION000000000000000A",
  organization_id: "01ORG00000000000000000000",
  device_id: "01DEVICE0000000000000000A",
  camera_id: "01CAMERA000000000000000A",
  purpose: "live",
  requested_by: "01USER00000000000000000A",
  window_start: null,
  window_end: null,
  status: "requested",
  started_at: null,
  ended_at: null,
  created_at: "2026-01-01T00:00:00Z",
  stream_url: "ws://jt1078-relay:7911/viewer?token=abc123",
};

describe("video api", () => {
  beforeEach(() => {
    vi.mocked(apiRequest).mockReset();
  });

  it("listDevicesForVideoPicker builds the picker query and maps to camelCase", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce({
      data: [DEVICE_WITH_CAMERA_WIRE],
      page: { total: 1, page: 1, page_size: 100 },
    });

    const result = await listDevicesForVideoPicker("");

    expect(apiRequest).toHaveBeenCalledWith("/devices?page=1&page_size=100&sort=terminal_id");
    expect(result).toEqual([
      {
        id: "01DEVICE0000000000000000A",
        terminalId: "TERM12345678",
        model: "LSZ-C5804DG-Q-F",
        vendor: "LSZ",
        lifecycleState: "assigned",
        cameras: [{ id: "01CAMERA000000000000000A", channelNo: 1, position: "road_facing", label: "Front" }],
      },
    ]);
  });

  it("listDevicesForVideoPicker filters out devices with no cameras — nothing this feature can use", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce({
      data: [DEVICE_WITH_CAMERA_WIRE, DEVICE_WITHOUT_CAMERA_WIRE],
      page: { total: 2, page: 1, page_size: 100 },
    });

    const result = await listDevicesForVideoPicker("");

    expect(result).toHaveLength(1);
    expect(result[0].id).toBe("01DEVICE0000000000000000A");
  });

  it("requestLiveVideo posts device_id/camera_id verbatim and maps the response", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce(SESSION_WIRE);

    const result = await requestLiveVideo("01DEVICE0000000000000000A", "01CAMERA000000000000000A");

    expect(apiRequest).toHaveBeenCalledWith("/video/live", {
      method: "POST",
      body: { device_id: "01DEVICE0000000000000000A", camera_id: "01CAMERA000000000000000A" },
    });
    expect(result).toEqual({
      id: "01SESSION000000000000000A",
      organizationId: "01ORG00000000000000000000",
      deviceId: "01DEVICE0000000000000000A",
      cameraId: "01CAMERA000000000000000A",
      purpose: "live",
      requestedBy: "01USER00000000000000000A",
      windowStart: null,
      windowEnd: null,
      status: "requested",
      startedAt: null,
      endedAt: null,
      createdAt: "2026-01-01T00:00:00Z",
      streamUrl: "ws://jt1078-relay:7911/viewer?token=abc123",
    });
  });

  it("stopVideoSession posts to the stop route and maps the response", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce({ ...SESSION_WIRE, status: "ended" });

    const result = await stopVideoSession("01SESSION000000000000000A");

    expect(apiRequest).toHaveBeenCalledWith("/video/sessions/01SESSION000000000000000A/stop", {
      method: "POST",
    });
    expect(result.status).toBe("ended");
  });
});
