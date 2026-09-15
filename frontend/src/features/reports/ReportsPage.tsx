import { useState } from "react";
import clsx from "clsx";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Eye, FileText, Truck, UserRound } from "lucide-react";
import { Card } from "../../shared/components/Card/Card";
import { PageSection } from "../../shared/components/PageSection/PageSection";
import { Button } from "../../shared/components/Button/Button";
import { Input } from "../../shared/components/Input/Input";
import { Select } from "../../shared/components/Select/Select";
import { EmptyState } from "../../shared/components/EmptyState/EmptyState";
import { Skeleton } from "../../shared/components/Skeleton/Skeleton";
import { FormField } from "../../shared/components/FormField/FormField";
import { ApiError } from "../../shared/api/types";
import { useToast } from "../../shared/components/Toast/toastStore";
import { usePageHeader } from "../../app/layout/PageHeaderContext";
import { useAuthStore } from "../../shared/stores/authStore";
import { getDashboardType } from "../../shared/auth/dashboard";
import {
  downloadReport,
  listParentsForReportPicker,
  listReportCatalog,
  listVehiclesForReportPicker,
  previewReport,
  type DownloadReportParams,
  type ReportCategory,
  type ReportDefinition,
  type ReportFormat,
  type ReportPickerOption,
  type ReportStatus,
  type ReportTablePreview,
} from "./api";
import { ReportSelectorList } from "./components/ReportSelectorList";
import { DateRangePresetFilter } from "./components/DateRangePresetFilter";
import { ReportEntitySelect } from "./components/ReportEntitySelect";
import { ReportPreviewDocument, type ReportFilterSummaryItem } from "./components/ReportPreviewDocument";
import { ExportActions } from "./components/ExportActions";
import { PlatformReportCenter } from "./PlatformReportCenter";
import styles from "./ReportsPage.module.css";

/** Formats a `YYYY-MM-DD` string as "September 5, 2026" using its own literal calendar date —
 * never `new Date(iso)` directly, which parses as UTC midnight and can silently shift the
 * displayed day backward in any timezone behind UTC. Presentation only: the raw ISO string is
 * still what is sent to the server. */
function formatDisplayDate(iso: string): string {
  const [year, month, day] = iso.split("-").map(Number);
  if (!year || !month || !day) return iso;
  return new Date(year, month - 1, day).toLocaleDateString(undefined, {
    year: "numeric",
    month: "long",
    day: "numeric",
  });
}

/** Formats a `YYYY-MM` period string as "September 2026". */
function formatDisplayPeriod(period: string): string {
  const [year, month] = period.split("-").map(Number);
  if (!year || !month) return period;
  return new Date(year, month - 1, 1).toLocaleDateString(undefined, { year: "numeric", month: "long" });
}

/**
 * Reports (ADR-0040 §6, ADR-0041 §3, Report Center re-design 2026-09-11,
 * UI refinement + catalog cleanup 2026-09-13).
 *
 * The catalogue is served by the backend (`GET /reports/catalog`), already filtered to what this
 * caller's role can generate — this page renders what it is given rather than keeping its own
 * hardcoded list, so a report added server-side appears here with no frontend change.
 *
 * **Organization dashboard: one Report Center, top-to-bottom, not a sidebar list next to a
 * mostly-empty panel.** A navigation/filter bar (search + category tabs) narrows the "Available
 * reports" tile grid below it; picking a tile reveals that report's own compact filter toolbar —
 * only the filters its `accepts` list names, never a raw Parent/Vehicle id field, only
 * `ReportEntitySelect`'s searchable name/plate pickers — and, once viewed, an A4-style document
 * preview (`ReportPreviewDocument`) rather than a dashboard-card result panel. The catalog itself
 * is two categories now (Financial/Transportation) — "Management" and three individual reports
 * (Parent Payment Report, Vehicle Revenue, Student Transportation Report) were removed from the
 * backend catalog registration; see `core/di/report_definitions.py`'s own 2026-09-13 comment.
 *
 * **Platform dashboard now shares the same design language** (`PlatformReportCenter.tsx`,
 * Organization Management phase) — category nav + search, a compact per-report filter toolbar,
 * an A4-style `ReportPreviewDocument` preview, PDF/Excel/Print export. The pre-redesign card grid
 * (`start`/`end`-only filters per card, an inline collapsible preview) is retired, not kept
 * alongside it — two visual languages for report browsing was the thing being fixed.
 *
 * **Select report -> apply filters -> View -> preview -> Export.** `Preview` calls
 * `GET /reports/{key}/preview`, the exact same `ReportTable` the PDF/XLSX renderers consume, so
 * what is shown here and what gets exported can never disagree — one source of truth
 * (`ReportExportService.build_table`), never two calculations of the same numbers.
 *
 * **Exports are real files.** `openpyxl` and `reportlab` render actual `.xlsx` and `.pdf`
 * server-side; there is no CSV pretending to be a spreadsheet and no "download" that produces a
 * job reference. Print reuses the PDF, which is the artifact a user would print anyway.
 */
export function ReportsPage() {
  const principal = useAuthStore((s) => s.principal);
  const scope = principal && getDashboardType(principal.role) === "platform" ? "platform" : "organization";

  usePageHeader(
    "Reports",
    scope === "platform"
      ? "Revenue, subscriptions, invoices, payments and platform costs"
      : "Parent invoices, receivables, income, expense and vehicle cost",
  );

  const catalog = useQuery({
    queryKey: ["reports", "catalog", scope],
    queryFn: () => listReportCatalog(scope),
    staleTime: 5 * 60_000,
  });

  return (
    <div className={clsx(styles.page, "raad-view-transition")}>
      {scope === "platform" ? (
        <PlatformReportCenter catalog={catalog} />
      ) : (
        <OrganizationReportCenter catalog={catalog} />
      )}
    </div>
  );
}

/* ---- Organization dashboard: the Report Center ------------------------------------------- */

function OrganizationReportCenter({
  catalog,
}: {
  catalog: ReturnType<typeof useQuery<ReportDefinition[]>>;
}) {
  const [search, setSearch] = useState("");
  const [activeCategory, setActiveCategory] = useState<ReportCategory>("financial");
  const [selectedKey, setSelectedKey] = useState<string | null>(null);

  const definitions = catalog.data ?? [];
  const selected = definitions.find((d) => d.key === selectedKey) ?? null;

  return (
    <PageSection title="Report Center" description="Search, preview, then export to PDF or Excel.">
      {catalog.isError ? (
        <Card padded>
          <EmptyState
            icon={<FileText size={22} />}
            title="Could not load the report catalogue"
            description={
              catalog.error instanceof ApiError ? catalog.error.message : "Something went wrong. Please try again."
            }
          />
        </Card>
      ) : catalog.isLoading ? (
        <Card padded className={styles.center}>
          <Skeleton height={36} width={320} />
          <Skeleton height={100} />
        </Card>
      ) : definitions.length === 0 ? (
        <Card padded>
          <EmptyState
            icon={<FileText size={22} />}
            title="No reports available for your role"
            description="Report availability follows the same permissions as the data behind it."
          />
        </Card>
      ) : (
        <div className={styles.center}>
          <Card padded>
            <ReportSelectorList
              definitions={definitions}
              search={search}
              onSearchChange={setSearch}
              activeCategory={activeCategory}
              onCategoryChange={setActiveCategory}
              selectedKey={selectedKey}
              onSelect={(definition) => setSelectedKey(definition.key)}
            />
          </Card>

          {selected ? (
            <Card padded>
              <ReportDetailPanel key={selected.key} definition={selected} />
            </Card>
          ) : (
            <p className={styles.pickHint}>
              <Eye size={14} /> Select a report above to configure its filters and preview it.
            </p>
          )}
        </div>
      )}
    </PageSection>
  );
}

const STATUS_OPTIONS: { value: ReportStatus | ""; label: string }[] = [
  { value: "", label: "All" },
  { value: "paid", label: "Paid" },
  { value: "partial", label: "Partial" },
  { value: "unpaid", label: "Unpaid" },
];

/** One selected report's own filters + preview + export. Mounted with `key={definition.key}` by
 * its parent so switching reports resets every filter and the preview, rather than carrying stale
 * state (a Vehicle picked for the Bus Report) into a report that doesn't use it. */
function ReportDetailPanel({ definition }: { definition: ReportDefinition }) {
  const toast = useToast();
  const accepts = new Set(definition.accepts);

  const [period, setPeriod] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [vehicle, setVehicle] = useState<ReportPickerOption | null>(null);
  const [parent, setParent] = useState<ReportPickerOption | null>(null);
  const [status, setStatus] = useState<ReportStatus | "">("");
  const [busy, setBusy] = useState<ReportFormat | null>(null);
  const [preview, setPreview] = useState<ReportTablePreview | null>(null);

  function currentParams(): DownloadReportParams {
    return {
      period: period || undefined,
      start: start || undefined,
      end: end || undefined,
      vehicleId: vehicle?.id,
      parentId: parent?.id,
      status: status || undefined,
    };
  }

  const previewMutation = useMutation({
    mutationFn: () => previewReport(definition.key, currentParams()),
    onSuccess: (table) => setPreview(table),
    onError: (error) => {
      toast.error("Preview failed", error instanceof Error ? error.message : "Please try again.");
    },
  });

  async function run(format: ReportFormat, print = false) {
    setBusy(format);
    try {
      await downloadReport(definition.key, format, currentParams());
      toast.success(
        print ? "Report ready to print" : "Report downloaded",
        print ? `${definition.title} was downloaded — open it to print.` : `${definition.title} (${format.toUpperCase()})`,
      );
    } catch (error) {
      toast.error("Export failed", error instanceof Error ? error.message : "Please try again.");
    } finally {
      setBusy(null);
    }
  }

  const hasDateRange = accepts.has("start") && accepts.has("end");
  const hasStartOnly = accepts.has("start") && !accepts.has("end");

  const periodLabel = hasDateRange
    ? start && end
      ? `${formatDisplayDate(start)} → ${formatDisplayDate(end)}`
      : "All time"
    : hasStartOnly
      ? start
        ? `Year ${start.split("-")[0]}`
        : "All time"
      : accepts.has("period")
        ? period
          ? formatDisplayPeriod(period)
          : "All time"
        : null;

  const filterSummaryItems: ReportFilterSummaryItem[] = [];
  if (accepts.has("parent_id")) {
    filterSummaryItems.push({ label: "Parent", value: parent?.label ?? "All parents" });
  }
  if (accepts.has("vehicle_id")) {
    filterSummaryItems.push({ label: "Vehicle", value: vehicle?.label ?? "All vehicles" });
  }
  if (accepts.has("status")) {
    filterSummaryItems.push({
      label: "Payment status",
      value: STATUS_OPTIONS.find((option) => option.value === status)?.label ?? "All",
    });
  }

  return (
    <div className={styles.detailBody}>
      <div>
        <h3 className={styles.detailTitle}>{definition.title}</h3>
        <p className={styles.detailDescription}>{definition.description}</p>
      </div>

      {accepts.size > 0 && (
        <div className={styles.filterBar}>
          {accepts.has("period") && (
            <FormField label="Period" hint="YYYY-MM — leave blank for all time">
              <Input value={period} onChange={(e) => setPeriod(e.target.value)} placeholder="2026-09" />
            </FormField>
          )}
          {hasDateRange && (
            <DateRangePresetFilter start={start} end={end} onChange={(range) => { setStart(range.start); setEnd(range.end); }} />
          )}
          {hasStartOnly && (
            <FormField label="Year" hint="Any date within the year to summarize">
              <Input type="date" value={start} onChange={(e) => setStart(e.target.value)} />
            </FormField>
          )}
          {accepts.has("vehicle_id") && (
            <FormField label="Vehicle" hint="Optional — narrows to one vehicle">
              <ReportEntitySelect
                value={vehicle}
                onChange={setVehicle}
                fetchOptions={listVehiclesForReportPicker}
                queryKey="report-vehicle"
                placeholder="All vehicles"
                emptyLabel="No vehicles found"
                icon={<Truck size={14} />}
              />
            </FormField>
          )}
          {accepts.has("parent_id") && (
            <FormField label="Parent" hint="Optional — narrows to one family">
              <ReportEntitySelect
                value={parent}
                onChange={setParent}
                fetchOptions={listParentsForReportPicker}
                queryKey="report-parent"
                placeholder="All parents"
                emptyLabel="No parents found"
                icon={<UserRound size={14} />}
              />
            </FormField>
          )}
          {accepts.has("status") && (
            <FormField label="Payment status">
              <Select value={status} onChange={(e) => setStatus(e.target.value as ReportStatus | "")}>
                {STATUS_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </Select>
            </FormField>
          )}
        </div>
      )}

      <div className={styles.actions}>
        <Button
          variant="primary"
          size="sm"
          leadingIcon={<Eye size={14} />}
          loading={previewMutation.isPending}
          disabled={busy !== null}
          onClick={() => previewMutation.mutate()}
        >
          View
        </Button>
        <ExportActions busy={busy} enabled={preview !== null} onExport={(format, print) => void run(format, print)} />
      </div>

      {preview && (
        <div className={styles.previewSection}>
          <div className={styles.sectionLabel}>Report preview</div>
          <ReportPreviewDocument preview={preview} period={periodLabel} filters={filterSummaryItems} />
        </div>
      )}
    </div>
  );
}

