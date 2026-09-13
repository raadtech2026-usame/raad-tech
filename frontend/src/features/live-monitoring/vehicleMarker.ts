import type { GpsFixStatus } from "./useVehiclePosition";
import styles from "./vehicleMarker.module.css";

export interface VehicleMarkerOptions {
  /** `true` when this marker represents the vehicle currently open in single-vehicle mode
   * (`VehicleMapPanel`) — unused by `FleetMapPanel`, whose markers are never "selected". */
  selected?: boolean;
  fixStatus: GpsFixStatus;
  ariaLabel: string;
}

/**
 * The professional RAAD bus marker (Mapbox UI upgrade) — a single shared builder for both
 * `VehicleMapPanel` (single-vehicle mode) and `FleetMapPanel` (All Vehicles mode), so the two
 * can never visually drift. A plain `HTMLDivElement` (not a React tree) because `MapProvider`'s
 * `addMarker`/`updateMarker` are imperative Mapbox GL APIs — this stays consistent with
 * `FleetMapPanel`'s own pre-existing plain-DOM marker convention.
 *
 * Color communicates GPS fix state (`GpsFixBadge`'s own palette, kept in sync deliberately):
 * brand blue + pulsing ring = live, amber = stale/no fix. `selected` adds a stronger ring so the
 * open vehicle is unambiguous on the fleet map. The small triangular indicator points in the
 * vehicle's heading — rotated independently of the marker's own DOM node (see
 * `MapboxMapProvider`'s own heading-handling docstring), so the bus glyph itself always stays
 * upright and legible.
 */
export function createVehicleMarkerElement(options: VehicleMarkerOptions): HTMLDivElement {
  const root = document.createElement("div");
  root.className = styles.root;
  root.setAttribute("role", "button");
  root.setAttribute("tabindex", "0");
  root.setAttribute("aria-label", options.ariaLabel);
  root.dataset.fixStatus = options.fixStatus;
  if (options.selected) {
    root.classList.add(styles.selected);
  }

  root.innerHTML = `
    <span class="${styles.heading}" data-role="heading-arrow"></span>
    <span class="${styles.badge}">
      <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor"
           stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <path d="M8 6v6"></path>
        <path d="M15 6v6"></path>
        <path d="M2 12h19.6"></path>
        <path d="M18 18h3s.5-1.7.8-2.8c.1-.4.2-.8.2-1.2 0-.4-.1-.8-.2-1.2l-1.4-5C20.1 6.8 19.1 6 18 6H4a2 2 0 0 0-2 2v10h3"></path>
        <circle cx="7" cy="18" r="2"></circle>
        <path d="M9 18h5"></path>
        <circle cx="16" cy="18" r="2"></circle>
      </svg>
    </span>
  `;
  return root;
}

export function updateVehicleMarkerFixStatus(element: HTMLElement, fixStatus: GpsFixStatus): void {
  element.dataset.fixStatus = fixStatus;
}

/** `GpsFixBadge`'s own three labels, as plain text — that component renders a React `Badge`
 * tree, which cannot be used inside a Mapbox `Popup.setHTML` string (plain markup only), so this
 * is the text-only equivalent shared by every vehicle hover popup. */
export const FIX_STATUS_LABEL: Record<GpsFixStatus, string> = {
  live: "Live",
  stale: "Stale",
  no_fix: "No Fix",
};

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

export interface VehiclePopupInfo {
  /** Plate number, optionally combined with a label — the caller's own formatting. */
  title: string;
  fixStatus: GpsFixStatus;
  speedKph: number | null;
  eventTime: string;
  /** The caller's own click affordance text (what clicking this marker actually does differs by
   * map — select this vehicle in place vs. navigate to the full Live Tracking page). Omitted
   * entirely (no line rendered) when the marker has no click affordance to describe — e.g.
   * `VehicleMapPanel`'s marker, which is already the single selected vehicle. */
  actionHint?: string;
}

/**
 * The shared "vehicle info" hover-popup markup (`FleetMapPanel`'s original implementation,
 * extracted here so it and every other vehicle map can never drift into showing different fields
 * for the same vehicle) — plain HTML, matching `createVehicleMarkerElement`'s own "imperative
 * Mapbox API, not a React tree" convention. `classNames` are the caller's own CSS module classes
 * (kept presentation-agnostic here rather than importing one feature's module CSS into this
 * shared file).
 *
 * A pure function of its current inputs — every caller (`FleetMapPanel`, `VehicleMapPanel`,
 * `LiveOperationsSection`) calls this again on every position/fix-status/metadata change and
 * pushes the result through `MapProvider.updateMarkerPopup`, never only once at marker-creation
 * time (root-cause fix, vehicle-popup staleness investigation — see each caller's own effect for
 * why `addMarker`'s one-time `popupHtml` alone was never enough).
 */
export function buildVehiclePopupHtml(
  info: VehiclePopupInfo,
  classNames: { popup: string; title: string; status: string; muted: string },
): string {
  const speedLine = info.speedKph !== null ? `<div>${info.speedKph} km/h</div>` : "";
  const lastGps = new Date(info.eventTime).toLocaleTimeString();
  const actionLine = info.actionHint ? `<div class="${classNames.muted}">${escapeHtml(info.actionHint)}</div>` : "";
  return `
    <div class="${classNames.popup}">
      <div class="${classNames.title}">${escapeHtml(info.title)}</div>
      <div class="${classNames.status}" data-fix-status="${info.fixStatus}">${FIX_STATUS_LABEL[info.fixStatus]}</div>
      ${speedLine}
      <div class="${classNames.muted}">Last GPS ${escapeHtml(lastGps)}</div>
      ${actionLine}
    </div>
  `;
}
