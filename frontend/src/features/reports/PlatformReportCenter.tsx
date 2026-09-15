import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Building2, Eye, FileText } from "lucide-react";
import { Card } from "../../shared/components/Card/Card";
import { PageSection } from "../../shared/components/PageSection/PageSection";
import { Button } from "../../shared/components/Button/Button";
import { Select } from "../../shared/components/Select/Select";
import { EmptyState } from "../../shared/components/EmptyState/EmptyState";
import { Skeleton } from "../../shared/components/Skeleton/Skeleton";
import { FormField } from "../../shared/components/FormField/FormField";
import { ApiError } from "../../shared/api/types";
import { useToast } from "../../shared/components/Toast/toastStore";
import {
  downloadReport,
  listOrganizationsForReportPicker,
  previewReport,
  type DownloadReportParams,
  type ReportBillingCycle,
  type ReportCategory,
  type ReportDefinition,
  type ReportFormat,
  type ReportPickerOption,
  type ReportSubscriptionStatus,
  type ReportTablePreview,
} from "./api";
import { ReportSelectorList } from "./components/ReportSelectorList";
import { DateRangePresetFilter } from "./components/DateRangePresetFilter";
import { ReportEntitySelect } from "./components/ReportEntitySelect";
import { ReportPreviewDocument, type ReportFilterSummaryItem } from "./components/ReportPreviewDocument";
import { ExportActions } from "./components/ExportActions";
import styles from "./ReportsPage.module.css";

/** Part 9's own two named categories, plus "Platform" — the directory/operational catch-all for
 * the seven reports that are neither financial facts nor subscription-lifecycle facts
 * (Organizations, Regions, Plans, Vehicles, Drivers, Devices, Audit Logs). Keeping them reachable
 * under a third, clearly-labelled tab is a deliberate, disclosed choice: the alternative — the
 * literal two named categories only — would silently remove UI-reachability the pre-redesign
 * card grid gave them, which is exactly the kind of regression this phase is not meant to cause. */
const PLATFORM_CATEGORY_TABS: { id: ReportCategory; label: string }[] = [
  { id: "financial", label: "Financial" },
  { id: "subscriptions", label: "Subscriptions" },
  { id: "platform", label: "Platform" },
];

const SUBSCRIPTION_STATUS_OPTIONS: { value: ReportSubscriptionStatus | ""; label: string }[] = [
  { value: "", label: "All" },
  { value: "trial", label: "Trial" },
  { value: "active", label: "Active" },
  { value: "past_due", label: "Past due" },
  { value: "grace_period", label: "Grace period" },
  { value: "suspended", label: "Suspended" },
  { value: "expired", label: "Expired" },
  { value: "cancelled", label: "Cancelled" },
];

const BILLING_CYCLE_OPTIONS: { value: ReportBillingCycle | ""; label: string }[] = [
  { value: "", label: "All" },
  { value: "monthly", label: "Monthly" },
  { value: "quarterly", label: "Quarterly" },
  { value: "annual", label: "Annual" },
];

/** Formats a `YYYY-MM-DD` string as "September 5, 2026" — mirrors `ReportsPage.tsx`'s own
 * identical helper (a small, deliberate duplication rather than threading a shared util through
 * two otherwise-independent report centers, the same posture this feature's own `api.ts`
 * documents for its picker functions). */
function formatDisplayDate(iso: string): string {
  const [year, month, day] = iso.split("-").map(Number);
  if (!year || !month || !day) return iso;
  return new Date(year, month - 1, day).toLocaleDateString(undefined, {
    year: "numeric",
    month: "long",
    day: "numeric",
  });
}

/**
 * Platform Report Center (Organization Management phase) — the Founder-facing counterpart to
 * `ReportsPage.tsx`'s own `OrganizationReportCenter`, built to the *same design language*:
 * category nav + search, a compact filter toolbar per selected report, an A4-style
 * `ReportPreviewDocument` preview, and PDF/Excel/Print export. Deliberately a **separate**
 * component, not a generalized merge of the two — the two report centers serve different
 * catalogues, different filters, and different audiences, and `.claude/rules/architecture.md` #6
 * treats Organization Reports and Platform Reports as two separate bounded contexts worth
 * keeping visibly apart, not one component branching on scope internally beyond what
 * `ReportSelectorList`'s own `categories` prop already generalizes.
 *
 * **Filters are real, not decorative.** `organization_id`/`subscription_status`/`billing_cycle`
 * are genuine, additive backend query parameters (`reporting.application.catalog.ReportRequest`)
 * that specific report builders now read — never a client-side-only narrowing of rows the server
 * already returned unfiltered.
 */
export function PlatformReportCenter({
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
    <PageSection title="Platform Report Center" description="Search, preview, then export to PDF or Excel.">
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
              categories={PLATFORM_CATEGORY_TABS}
            />
          </Card>

          {selected ? (
            <Card padded>
              <PlatformReportDetailPanel key={selected.key} definition={selected} />
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

/** One selected platform report's own filters + preview + export. Mounted with
 * `key={definition.key}` by its parent so switching reports resets every filter and the
 * preview — mirrors `ReportsPage.tsx`'s own `ReportDetailPanel` for the identical reason, with a
 * platform-appropriate filter set instead of Vehicle/Parent/payment-status. */
function PlatformReportDetailPanel({ definition }: { definition: ReportDefinition }) {
  const toast = useToast();
  const accepts = new Set(definition.accepts);

  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [organization, setOrganization] = useState<ReportPickerOption | null>(null);
  const [subscriptionStatus, setSubscriptionStatus] = useState<ReportSubscriptionStatus | "">("");
  const [billingCycle, setBillingCycle] = useState<ReportBillingCycle | "">("");
  const [busy, setBusy] = useState<ReportFormat | null>(null);
  const [preview, setPreview] = useState<ReportTablePreview | null>(null);

  function currentParams(): DownloadReportParams {
    return {
      start: start || undefined,
      end: end || undefined,
      organizationId: organization?.id,
      subscriptionStatus: subscriptionStatus || undefined,
      billingCycle: billingCycle || undefined,
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
  const periodLabel = hasDateRange
    ? start && end
      ? `${formatDisplayDate(start)} → ${formatDisplayDate(end)}`
      : "All time"
    : null;

  const filterSummaryItems: ReportFilterSummaryItem[] = [];
  if (accepts.has("organization_id")) {
    filterSummaryItems.push({ label: "Organization", value: organization?.label ?? "All organizations" });
  }
  if (accepts.has("subscription_status")) {
    filterSummaryItems.push({
      label: "Subscription status",
      value: SUBSCRIPTION_STATUS_OPTIONS.find((o) => o.value === subscriptionStatus)?.label ?? "All",
    });
  }
  if (accepts.has("billing_cycle")) {
    filterSummaryItems.push({
      label: "Billing cycle",
      value: BILLING_CYCLE_OPTIONS.find((o) => o.value === billingCycle)?.label ?? "All",
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
          {hasDateRange && (
            <DateRangePresetFilter
              start={start}
              end={end}
              onChange={(range) => {
                setStart(range.start);
                setEnd(range.end);
              }}
            />
          )}
          {accepts.has("organization_id") && (
            <FormField label="Organization" hint="Optional — narrows to one organization">
              <ReportEntitySelect
                value={organization}
                onChange={setOrganization}
                fetchOptions={listOrganizationsForReportPicker}
                queryKey="report-organization"
                placeholder="All organizations"
                emptyLabel="No organizations found"
                icon={<Building2 size={14} />}
              />
            </FormField>
          )}
          {accepts.has("subscription_status") && (
            <FormField label="Subscription status">
              <Select
                value={subscriptionStatus}
                onChange={(e) => setSubscriptionStatus(e.target.value as ReportSubscriptionStatus | "")}
              >
                {SUBSCRIPTION_STATUS_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </Select>
            </FormField>
          )}
          {accepts.has("billing_cycle") && (
            <FormField label="Billing cycle">
              <Select
                value={billingCycle}
                onChange={(e) => setBillingCycle(e.target.value as ReportBillingCycle | "")}
              >
                {BILLING_CYCLE_OPTIONS.map((option) => (
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
