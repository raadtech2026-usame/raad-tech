import { describe, expect, it } from "vitest";
import {
  buildVehiclePopupHtml,
  createVehicleMarkerElement,
  FIX_STATUS_LABEL,
  updateVehicleMarkerFixStatus,
} from "./vehicleMarker";

const CLASS_NAMES = { popup: "popup", title: "popupTitle", status: "popupStatus", muted: "popupMuted" };

describe("createVehicleMarkerElement", () => {
  it("builds an accessible, focusable marker root carrying the given fix status", () => {
    const element = createVehicleMarkerElement({ fixStatus: "live", ariaLabel: "Bus 001" });
    expect(element.getAttribute("role")).toBe("button");
    expect(element.getAttribute("tabindex")).toBe("0");
    expect(element.getAttribute("aria-label")).toBe("Bus 001");
    expect(element.dataset.fixStatus).toBe("live");
    expect(element.querySelector('[data-role="heading-arrow"]')).not.toBeNull();
    expect(element.querySelector("svg")).not.toBeNull();
  });

  it("adds the selected modifier only when asked", () => {
    const selected = createVehicleMarkerElement({ fixStatus: "live", ariaLabel: "x", selected: true });
    const unselected = createVehicleMarkerElement({ fixStatus: "live", ariaLabel: "x" });
    expect(selected.className).not.toBe(unselected.className);
  });
});

describe("updateVehicleMarkerFixStatus", () => {
  it("updates the element's own fix-status dataset in place", () => {
    const element = createVehicleMarkerElement({ fixStatus: "live", ariaLabel: "x" });
    updateVehicleMarkerFixStatus(element, "stale");
    expect(element.dataset.fixStatus).toBe("stale");
  });
});

describe("buildVehiclePopupHtml", () => {
  it("includes title, fix-status label, speed, and last-GPS time when all fields are given", () => {
    const html = buildVehiclePopupHtml(
      {
        title: "BENCH-001 — Bus 001",
        fixStatus: "live",
        speedKph: 18,
        eventTime: "2026-01-01T12:03:15Z",
        actionHint: "Click to view this vehicle",
      },
      CLASS_NAMES,
    );

    expect(html).toContain("BENCH-001 — Bus 001");
    expect(html).toContain(FIX_STATUS_LABEL.live);
    expect(html).toContain('data-fix-status="live"');
    expect(html).toContain("18 km/h");
    expect(html).toContain("Last GPS");
    expect(html).toContain("Click to view this vehicle");
  });

  it("omits the speed line entirely when speedKph is null, never showing a fabricated 0 km/h", () => {
    const html = buildVehiclePopupHtml(
      { title: "T", fixStatus: "live", speedKph: null, eventTime: "2026-01-01T00:00:00Z" },
      CLASS_NAMES,
    );
    expect(html).not.toContain("km/h");
  });

  it("omits the action-hint line entirely when actionHint is not given", () => {
    const withHint = buildVehiclePopupHtml(
      { title: "T", fixStatus: "live", speedKph: null, eventTime: "2026-01-01T00:00:00Z", actionHint: "Click" },
      CLASS_NAMES,
    );
    const withoutHint = buildVehiclePopupHtml(
      { title: "T", fixStatus: "live", speedKph: null, eventTime: "2026-01-01T00:00:00Z" },
      CLASS_NAMES,
    );
    expect(withHint).toContain("Click");
    // Same number of popupMuted lines minus the action-hint's own — the "Last GPS" muted line
    // must still be present either way.
    expect(withoutHint).toContain("Last GPS");
    expect(withoutHint.match(/popupMuted/g)?.length).toBe(1);
    expect(withHint.match(/popupMuted/g)?.length).toBe(2);
  });

  it("reflects a changed fix status, speed, and timestamp on a later call — the dynamic-update contract every caller relies on", () => {
    const before = buildVehiclePopupHtml(
      { title: "T", fixStatus: "live", speedKph: 0, eventTime: "2026-01-01T12:03:08Z" },
      CLASS_NAMES,
    );
    const after = buildVehiclePopupHtml(
      { title: "T", fixStatus: "stale", speedKph: 18, eventTime: "2026-01-01T12:03:15Z" },
      CLASS_NAMES,
    );
    expect(before).not.toBe(after);
    expect(before).toContain('data-fix-status="live"');
    expect(after).toContain('data-fix-status="stale"');
    expect(before).toContain("0 km/h");
    expect(after).toContain("18 km/h");
  });

  it("escapes HTML-unsafe characters in the title and action hint", () => {
    const html = buildVehiclePopupHtml(
      {
        title: '<img src=x onerror=alert(1)>',
        fixStatus: "live",
        speedKph: null,
        eventTime: "2026-01-01T00:00:00Z",
        actionHint: '"><script>alert(2)</script>',
      },
      CLASS_NAMES,
    );
    expect(html).not.toContain("<img");
    expect(html).not.toContain("<script>");
    expect(html).toContain("&lt;img");
    expect(html).toContain("&lt;script&gt;");
  });
});
