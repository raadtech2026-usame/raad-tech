import { env } from "../../config/env";
import { apiRequest } from "../../shared/api/client";
import { buildOffsetListQuery } from "../../shared/api/listParams";
import type { OffsetPageWire } from "../../shared/api/types";
import { useAuthStore } from "../../shared/stores/authStore";

/**
 * Reporting catalogue and export (ADR-0040 §6).
 *
 * **Why `downloadReport` does not use `apiRequest`.** That helper parses every response as JSON;
 * a report is `application/pdf` or `.xlsx` bytes. This uses `fetch` directly, reads a `Blob`, and
 * triggers a save — the one place in this frontend where a binary body is the point.
 *
 * **Why not a plain `<a href>` either.** These routes require an `Authorization: Bearer` header,
 * and a browser navigation cannot carry one. `.claude/rules/frontend.md` #5 keeps tokens in
 * memory rather than a cookie precisely so they are never sent ambiently, which means a
 * link-based download is not available to us — the token has to be attached to an explicit
 * request, and the resulting bytes handed to the browser as an object URL.
 */

export type ReportScope = "platform" | "organization";
export type ReportFormat = "pdf" | "xlsx";
/** Report Center re-design (2026-09-11), catalog cleanup (2026-09-13) — the two organization
 * tabs (`raad/modules/reporting/application/catalog.py`'s own `ReportDefinition.category` doc
 * names the grouping rationale; the "management" category and every report registered under it
 * were removed from the backend catalog outright). Platform reports still carry a `category`
 * (backend default) but the platform view ignores it — that catalogue keeps its existing
 * card-grid, untouched. */
export type ReportCategory = "financial" | "transportation" | "platform";
/** `ParentInvoiceStatus` (ADR-0042) — the only four values the Report Center's Status selector
 * offers, matching the directive's own named set exactly (no "cancelled" option in this UI, even
 * though the backend query also accepts it). */
export type ReportStatus = "unpaid" | "partial" | "paid";

export interface ReportDefinition {
  key: string;
  title: string;
  description: string;
  scope: ReportScope;
  /** Which optional inputs this report reads — the UI shows only the filters that apply. */
  accepts: string[];
  category: ReportCategory;
}

export async function listReportCatalog(scope?: ReportScope): Promise<ReportDefinition[]> {
  const qs = scope ? `?scope=${scope}` : "";
  return apiRequest<ReportDefinition[]>(`/reports/catalog${qs}`);
}

export interface DownloadReportParams {
  period?: string;
  start?: string;
  end?: string;
  vehicleId?: string;
  /** ADR-0041 §3 — two additive optional filters, both already-filterable columns at the
   * repository layer; no new query capability, only two report builders that read them. */
  parentId?: string;
  paymentMethod?: string;
  /** Report Center re-design (2026-09-11) — `ParentInvoiceStatus`, already a filterable column
   * (ADR-0042); no new query capability, only report builders now plumbing it through. */
  status?: ReportStatus;
}

function buildReportQuery(params: DownloadReportParams, extra: Record<string, string> = {}): URLSearchParams {
  const qs = new URLSearchParams(extra);
  if (params.period) qs.set("period", params.period);
  if (params.start) qs.set("start", params.start);
  if (params.end) qs.set("end", params.end);
  if (params.vehicleId) qs.set("vehicle_id", params.vehicleId);
  if (params.parentId) qs.set("parent_id", params.parentId);
  if (params.paymentMethod) qs.set("payment_method", params.paymentMethod);
  if (params.status) qs.set("status", params.status);
  return qs;
}

/** One rendered report's data, exactly as `ReportTable` (`reporting.application.report_table`)
 * holds it — headers/rows/metadata/totals already formatted server-side, nothing recomputed
 * here. Field-for-field mirror of `GET /reports/{key}/preview`'s response. */
export interface ReportTablePreview {
  title: string;
  subtitle: string | null;
  headers: string[];
  rows: string[][];
  metadata: Record<string, string>;
  numericColumns: number[];
  totalRow: string[] | null;
}

interface ReportTablePreviewWire {
  title: string;
  subtitle: string | null;
  headers: string[];
  rows: string[][];
  metadata: Record<string, string>;
  numeric_columns: number[];
  total_row: string[] | null;
}

/**
 * `GET /reports/{key}/preview` (ADR-0041 §3) — the "View report before exporting" step: the
 * exact same `ReportTable` `export`'s PDF/XLSX renderers consume, as JSON. Calling this and
 * `downloadReport` with the same filters can never show different numbers — both resolve
 * through `ReportExportService.build_table`, one source of truth.
 */
export async function previewReport(
  definitionKey: string,
  params: DownloadReportParams = {},
): Promise<ReportTablePreview> {
  const qs = buildReportQuery(params);
  const wire = await apiRequest<ReportTablePreviewWire>(
    `/reports/${encodeURIComponent(definitionKey)}/preview?${qs}`,
  );
  return {
    title: wire.title,
    subtitle: wire.subtitle,
    headers: wire.headers,
    rows: wire.rows,
    metadata: wire.metadata,
    numericColumns: wire.numeric_columns,
    totalRow: wire.total_row,
  };
}

/**
 * Renders a report server-side and saves it to the user's machine.
 *
 * Revokes the object URL after the click. Skipping that is the classic leak here: every download
 * would otherwise pin its full blob in memory for the lifetime of the document.
 */
export async function downloadReport(
  definitionKey: string,
  format: ReportFormat,
  params: DownloadReportParams = {},
): Promise<void> {
  const qs = buildReportQuery(params, { format });

  const token = useAuthStore.getState().accessToken;
  const response = await fetch(
    `${env.apiBaseUrl}/reports/${encodeURIComponent(definitionKey)}/export?${qs}`,
    { headers: token ? { Authorization: `Bearer ${token}` } : {} },
  );

  if (!response.ok) {
    // The error envelope is JSON even when the success body is binary, so this still parses.
    let message = `Report export failed (${response.status})`;
    try {
      const body = await response.json();
      message = body?.error?.message ?? message;
    } catch {
      // Non-JSON error body — keep the status-based message.
    }
    throw new Error(message);
  }

  const blob = await response.blob();
  const filename =
    parseFilename(response.headers.get("Content-Disposition")) ??
    `${definitionKey.replace(/\./g, "-")}.${format}`;

  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

/** Reads `attachment; filename="x.pdf"`, so the saved file keeps the server's own name. */
function parseFilename(header: string | null): string | null {
  if (!header) return null;
  const match = /filename="?([^"]+)"?/.exec(header);
  return match ? match[1] : null;
}

/* ---- Report Center re-design (2026-09-11): searchable id->label pickers ------------------- */
/*
 * Two thin, feature-owned lookups against `/parents`/`/vehicles` — never a cross-folder import
 * of `transport-ops/parents/api.ts` or `fleet-devices/devices/api.ts`'s own picker functions
 * (`.claude/rules/frontend.md` #1's "no cross-folder api.ts import" discipline). Duplicating this
 * ~10-line shape is the same precedent `school-erp/api.ts`'s own `listVehiclesForPicker` already
 * documents against `fleet-devices/devices/api.ts`'s: every feature that needs a name for an id
 * it doesn't own defines its own narrow lookup, rather than coupling two feature folders.
 *
 * Deliberately simpler than `transport-ops/parents/ParentSearchSelect.tsx`'s own picker: a report
 * filter only ever needs an id to send back to the server, never the two follow-up calls
 * (`getParent` + `listStudentsForParent`) that component makes to show a "children on file" line
 * a filter has no use for.
 */

export interface ReportPickerOption {
  id: string;
  label: string;
}

interface ParentPickerWire {
  id: string;
  full_name: string;
}

export async function listParentsForReportPicker(search: string): Promise<ReportPickerOption[]> {
  const query = buildOffsetListQuery({
    page: 1,
    pageSize: 20,
    sort: { field: "full_name", direction: "asc" },
    filters: { status: "active" },
    search,
  });
  const wire = await apiRequest<OffsetPageWire<ParentPickerWire>>(`/parents?${query}`);
  return wire.data.map((parent) => ({ id: parent.id, label: parent.full_name }));
}

interface VehiclePickerWire {
  id: string;
  plate_no: string;
  label: string | null;
}

export async function listVehiclesForReportPicker(search: string): Promise<ReportPickerOption[]> {
  const query = buildOffsetListQuery({
    page: 1,
    pageSize: 20,
    sort: { field: "plate_no", direction: "asc" },
    filters: {},
    search,
  });
  const wire = await apiRequest<OffsetPageWire<VehiclePickerWire>>(`/vehicles?${query}`);
  return wire.data.map((vehicle) => ({
    id: vehicle.id,
    label: vehicle.label ? `${vehicle.plate_no} · ${vehicle.label}` : vehicle.plate_no,
  }));
}
