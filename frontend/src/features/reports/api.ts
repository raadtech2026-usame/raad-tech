import { env } from "../../config/env";
import { apiRequest } from "../../shared/api/client";
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

export interface ReportDefinition {
  key: string;
  title: string;
  description: string;
  scope: ReportScope;
  /** Which optional inputs this report reads — the UI shows only the filters that apply. */
  accepts: string[];
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
  const qs = new URLSearchParams({ format });
  if (params.period) qs.set("period", params.period);
  if (params.start) qs.set("start", params.start);
  if (params.end) qs.set("end", params.end);
  if (params.vehicleId) qs.set("vehicle_id", params.vehicleId);

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
