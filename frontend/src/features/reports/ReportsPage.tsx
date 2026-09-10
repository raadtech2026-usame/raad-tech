import { useMemo, useState } from "react";
import clsx from "clsx";
import { useQuery } from "@tanstack/react-query";
import { FileSpreadsheet, FileText, Printer, Search } from "lucide-react";
import { Card } from "../../shared/components/Card/Card";
import { PageSection } from "../../shared/components/PageSection/PageSection";
import { Button } from "../../shared/components/Button/Button";
import { Input } from "../../shared/components/Input/Input";
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
  listReportCatalog,
  type ReportDefinition,
  type ReportFormat,
} from "./api";
import styles from "./ReportsPage.module.css";

/**
 * Reports (ADR-0040 §6).
 *
 * The catalogue is served by the backend (`GET /reports/catalog`), already filtered to what this
 * caller's role can generate — this page renders what it is given rather than keeping its own
 * hardcoded list, so a report added server-side appears here with no frontend change.
 *
 * **Exports are real files.** `openpyxl` and `reportlab` render actual `.xlsx` and `.pdf`
 * server-side; there is no CSV pretending to be a spreadsheet and no "download" that produces a
 * job reference. Print reuses the PDF, which is the artifact a user would print anyway.
 *
 * Filters are driven by each definition's own `accepts` list, so a report that takes no period
 * shows no period field — rather than every report showing every filter and most of them being
 * ignored.
 */
export function ReportsPage() {
  const principal = useAuthStore((s) => s.principal);
  const scope = principal && getDashboardType(principal.role) === "platform" ? "platform" : "organization";

  usePageHeader(
    "Reports",
    scope === "platform"
      ? "Revenue, subscriptions, invoices, payments and platform costs"
      : "Student billing, vehicle revenue and outstanding balances",
  );

  const catalog = useQuery({
    queryKey: ["reports", "catalog", scope],
    queryFn: () => listReportCatalog(scope),
    staleTime: 5 * 60_000,
  });

  const [search, setSearch] = useState("");
  const filtered = useMemo(() => {
    const data = catalog.data ?? [];
    const query = search.trim().toLowerCase();
    if (!query) return data;
    return data.filter(
      (definition) =>
        definition.title.toLowerCase().includes(query) ||
        definition.description.toLowerCase().includes(query),
    );
  }, [catalog.data, search]);

  return (
    <div className={clsx(styles.page, "raad-view-transition")}>
      <PageSection
        title={scope === "platform" ? "Platform reports" : "Organization reports"}
        description="Rendered on demand and downloaded directly — PDF or Excel."
        action={
          (catalog.data?.length ?? 0) > 0 && (
            <Input
              icon={<Search size={14} />}
              placeholder="Search reports…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              aria-label="Search the report catalogue"
            />
          )
        }
      >
        {catalog.isError ? (
          <Card padded>
            <EmptyState
              icon={<FileText size={22} />}
              title="Could not load the report catalogue"
              description={
                catalog.error instanceof ApiError
                  ? catalog.error.message
                  : "Something went wrong. Please try again."
              }
            />
          </Card>
        ) : catalog.isLoading ? (
          <div className={styles.grid}>
            {Array.from({ length: 4 }, (_, i) => (
              <Card key={i} padded>
                <Skeleton height={18} width="55%" />
                <Skeleton height={14} />
                <Skeleton height={34} width={180} />
              </Card>
            ))}
          </div>
        ) : (catalog.data?.length ?? 0) === 0 ? (
          <Card padded>
            <EmptyState
              icon={<FileText size={22} />}
              title="No reports available for your role"
              description="Report availability follows the same permissions as the data behind it."
            />
          </Card>
        ) : filtered.length === 0 ? (
          <Card padded>
            <EmptyState
              icon={<Search size={22} />}
              title="No reports match your search"
              description={`Nothing in the catalogue matches "${search}". Try a different term.`}
            />
          </Card>
        ) : (
          <div className={styles.grid}>
            {filtered.map((definition) => (
              <ReportCard key={definition.key} definition={definition} />
            ))}
          </div>
        )}
      </PageSection>
    </div>
  );
}

function ReportCard({ definition }: { definition: ReportDefinition }) {
  const toast = useToast();
  const [period, setPeriod] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [vehicleId, setVehicleId] = useState("");
  const [busy, setBusy] = useState<ReportFormat | null>(null);

  const accepts = new Set(definition.accepts);

  async function run(format: ReportFormat, print = false) {
    setBusy(format);
    try {
      await downloadReport(definition.key, format, {
        period: period || undefined,
        start: start || undefined,
        end: end || undefined,
        vehicleId: vehicleId || undefined,
      });
      toast.success(
        print ? "Report ready to print" : "Report downloaded",
        print
          ? `${definition.title} was downloaded — open it to print.`
          : `${definition.title} (${format.toUpperCase()})`,
      );
    } catch (error) {
      toast.error(
        "Export failed",
        error instanceof Error ? error.message : "Please try again.",
      );
    } finally {
      setBusy(null);
    }
  }

  return (
    <Card padded className={styles.card}>
      <div className={styles.cardHead}>
        <span className={styles.icon}>
          <FileText size={18} />
        </span>
        <div className={styles.cardText}>
          <h3 className={styles.cardTitle}>{definition.title}</h3>
          <p className={styles.cardDescription}>{definition.description}</p>
        </div>
      </div>

      {accepts.size > 0 && (
        <div className={styles.filters}>
          {accepts.has("period") && (
            <FormField label="Period" hint="YYYY-MM — leave blank for all time">
              <Input
                value={period}
                onChange={(e) => setPeriod(e.target.value)}
                placeholder="2026-09"
              />
            </FormField>
          )}
          {accepts.has("vehicle_id") && (
            <FormField label="Vehicle" hint="Required for this report">
              <Input
                value={vehicleId}
                onChange={(e) => setVehicleId(e.target.value)}
                placeholder="Vehicle id"
              />
            </FormField>
          )}
          {accepts.has("start") && (
            <FormField label="From">
              <Input type="date" value={start} onChange={(e) => setStart(e.target.value)} />
            </FormField>
          )}
          {accepts.has("end") && (
            <FormField label="To">
              <Input type="date" value={end} onChange={(e) => setEnd(e.target.value)} />
            </FormField>
          )}
        </div>
      )}

      <div className={styles.actions}>
        <Button
          variant="primary"
          size="sm"
          loading={busy === "pdf"}
          disabled={busy !== null}
          onClick={() => void run("pdf")}
        >
          <FileText size={14} /> PDF
        </Button>
        <Button
          variant="secondary"
          size="sm"
          loading={busy === "xlsx"}
          disabled={busy !== null}
          onClick={() => void run("xlsx")}
        >
          <FileSpreadsheet size={14} /> Excel
        </Button>
        <Button
          variant="ghost"
          size="sm"
          disabled={busy !== null}
          onClick={() => void run("pdf", true)}
          title="Downloads the PDF — open it to print"
        >
          <Printer size={14} /> Print
        </Button>
      </div>
    </Card>
  );
}
