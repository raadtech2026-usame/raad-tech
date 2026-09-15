import { useQuery } from "@tanstack/react-query";
import { Info, Users } from "lucide-react";
import { Badge } from "../../../shared/components/Badge/Badge";
import { EmptyState } from "../../../shared/components/EmptyState/EmptyState";
import { Skeleton } from "../../../shared/components/Skeleton/Skeleton";
import { ApiError } from "../../../shared/api/types";
import { formatDateOnly, formatDateTime } from "../../billing/format";
import {
  invoiceStatusLabel,
  invoiceStatusTone,
  paymentStatusLabel,
  paymentStatusTone,
} from "../../billing/labels";
import type { Organization } from "../api";
import { orgTypeLabel, statusLabel, statusTone } from "../labels";
import {
  orgAudit,
  orgDevices,
  orgDrivers,
  orgExpenses,
  orgIncome,
  orgInvoices,
  orgParentCount,
  orgPayments,
  orgRoutes,
  orgStudentCount,
  orgStudentInvoices,
  orgStudentPayments,
  orgUsers,
  orgVehicles,
} from "./api";
import { OrganizationOverviewSummary } from "./OrganizationOverviewSummary";
import { OrganizationSettingsTab } from "./OrganizationSettingsTab";
import { OrganizationSubscriptionPanel } from "./OrganizationSubscriptionPanel";
import { OrganizationUsageTab } from "./OrganizationUsageTab";
import type { OrganizationDetailTabId } from "./tabs";
import styles from "./OrganizationDetailsPage.module.css";

/**
 * Renders one tab. Every tab is a query plus a table; the shared `<DataList>` below keeps the
 * loading / error / empty / rows branches identical across all of them, because fifteen
 * hand-written copies of that ladder is how one of them ends up silently rendering `[]` as
 * success.
 */

interface Props {
  tab: OrganizationDetailTabId;
  organizationId: string;
  organization: Organization;
  regionName: string | null;
  onSelectTab: (tab: OrganizationDetailTabId) => void;
}

interface Column<T> {
  header: string;
  cell: (row: T) => React.ReactNode;
  align?: "right";
}

function DataList<T>({
  queryKey,
  queryFn,
  columns,
  rowKey,
  emptyTitle,
  emptyDescription,
}: {
  queryKey: unknown[];
  queryFn: () => Promise<{ data: T[]; page: { total: number } }>;
  columns: Column<T>[];
  rowKey: (row: T) => string;
  emptyTitle: string;
  emptyDescription: string;
}) {
  const query = useQuery({ queryKey, queryFn, staleTime: 30_000 });

  if (query.isPending) {
    return (
      <>
        <Skeleton height={18} />
        <Skeleton height={18} />
        <Skeleton height={18} />
      </>
    );
  }
  if (query.isError) {
    return (
      <EmptyState
        icon={<Info size={20} />}
        title="Could not load this section"
        description={
          query.error instanceof ApiError
            ? query.error.message
            : "Something went wrong. Please try again."
        }
      />
    );
  }
  if (query.data.data.length === 0) {
    return <EmptyState icon={<Info size={20} />} title={emptyTitle} description={emptyDescription} />;
  }

  return (
    <>
      <p className={styles.count}>{query.data.page.total} total</p>
      <div className={styles.tableScroll}>
        <table className={styles.table}>
          <thead>
            <tr>
              {columns.map((column) => (
                <th
                  key={column.header}
                  className={column.align === "right" ? styles.alignRight : undefined}
                >
                  {column.header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {query.data.data.map((row) => (
              <tr key={rowKey(row)}>
                {columns.map((column) => (
                  <td
                    key={column.header}
                    className={column.align === "right" ? styles.alignRight : undefined}
                  >
                    {column.cell(row)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

/** A count with no roster behind it, and an explicit reason. */
function CountOnly({
  organizationId,
  noun,
  queryFn,
}: {
  organizationId: string;
  noun: string;
  queryFn: (organizationId: string) => Promise<number>;
}) {
  const query = useQuery({
    queryKey: ["organizations", "detail", organizationId, noun, "count"],
    queryFn: () => queryFn(organizationId),
    staleTime: 60_000,
  });

  return (
    <div className={styles.countOnly}>
      <div className={styles.bigNumber}>
        {query.isPending ? "—" : query.isError ? "—" : query.data}
      </div>
      <div className={styles.countOnlyLabel}>{noun} in this organization</div>
      <div className={styles.notice}>
        <Info size={16} className={styles.noticeIcon} aria-hidden="true" />
        <p className={styles.noticeText}>
          RAAD deliberately cannot list individual {noun.toLowerCase()}. The platform manages
          organizations, their fleets and their subscriptions — student and family records belong
          to the school and are visible only to its own administrators. This is enforced by the
          permission matrix, not hidden in the interface.
        </p>
      </div>
    </div>
  );
}

export function OrganizationTabPanel({
  tab,
  organizationId,
  organization,
  regionName,
  onSelectTab,
}: Props) {
  const base = ["organizations", "detail", organizationId] as const;

  switch (tab) {
    case "overview":
      return (
        <div className={styles.stack}>
          <dl className={styles.detail}>
            <div>
              <dt>Name</dt>
              <dd>{organization.name}</dd>
            </div>
            <div>
              <dt>Type</dt>
              <dd>{orgTypeLabel(organization.orgType)}</dd>
            </div>
            <div>
              <dt>Status</dt>
              <dd>
                <Badge variant={statusTone(organization.status)} dot>
                  {statusLabel(organization.status)}
                </Badge>
              </dd>
            </div>
            <div>
              <dt>Region</dt>
              <dd>{regionName ?? organization.regionId}</dd>
            </div>
            <div>
              <dt>Parent organization</dt>
              <dd>{organization.parentOrgId ?? "None — top level"}</dd>
            </div>
            <div>
              <dt>Organization ID</dt>
              <dd className={styles.mono}>{organization.id}</dd>
            </div>
            <div>
              <dt>Created</dt>
              <dd>{formatDateTime(organization.createdAt)}</dd>
            </div>
            <div>
              <dt>Last updated</dt>
              <dd>{formatDateTime(organization.updatedAt)}</dd>
            </div>
          </dl>

          <OrganizationOverviewSummary organizationId={organizationId} onSelectTab={onSelectTab} />
        </div>
      );

    case "subscription":
      return (
        <OrganizationSubscriptionPanel organizationId={organizationId} organization={organization} />
      );

    case "users":
      return (
        <DataList
          queryKey={[...base, "users"]}
          queryFn={() => orgUsers(organizationId)}
          rowKey={(row) => row.id}
          emptyTitle="No users"
          emptyDescription="Nobody can sign in to this organization yet. Onboarding normally provisions an Org Admin."
          columns={[
            { header: "Name", cell: (r) => r.fullName },
            { header: "Role", cell: (r) => r.role.replace(/_/g, " ") },
            { header: "Email", cell: (r) => r.email ?? "—" },
            { header: "Phone", cell: (r) => r.phone ?? "—" },
            { header: "Status", cell: (r) => <Badge variant={r.status === "active" ? "success" : "neutral"} dot>{r.status}</Badge> },
          ]}
        />
      );

    case "vehicles":
      return (
        <DataList
          queryKey={[...base, "vehicles"]}
          queryFn={() => orgVehicles(organizationId)}
          rowKey={(row) => row.id}
          emptyTitle="No vehicles"
          emptyDescription="This organization has not registered any buses."
          columns={[
            { header: "Plate", cell: (r) => r.plateNo },
            { header: "Label", cell: (r) => r.label ?? "—" },
            { header: "Capacity", cell: (r) => r.capacity ?? "—", align: "right" },
            { header: "Status", cell: (r) => <Badge variant={r.status === "active" ? "success" : "neutral"} dot>{r.status}</Badge> },
          ]}
        />
      );

    case "devices":
      return (
        <DataList
          queryKey={[...base, "devices"]}
          queryFn={() => orgDevices(organizationId)}
          rowKey={(row) => row.id}
          emptyTitle="No devices allocated"
          emptyDescription="RAAD has not allocated any GPS/MDVR hardware to this organization yet."
          columns={[
            { header: "Terminal", cell: (r) => <span className={styles.mono}>{r.terminalId}</span> },
            { header: "Model", cell: (r) => r.model ?? "—" },
            { header: "IMEI", cell: (r) => r.imei ?? "—" },
            { header: "State", cell: (r) => r.lifecycleState.replace(/_/g, " ") },
            { header: "Last seen", cell: (r) => (r.lastSeenAt ? formatDateTime(r.lastSeenAt) : "Never") },
          ]}
        />
      );

    case "students":
      return <CountOnly organizationId={organizationId} noun="Students" queryFn={orgStudentCount} />;

    case "parents":
      return <CountOnly organizationId={organizationId} noun="Parents" queryFn={orgParentCount} />;

    case "routes":
      return (
        <DataList
          queryKey={[...base, "routes"]}
          queryFn={() => orgRoutes(organizationId)}
          rowKey={(row) => row.id}
          emptyTitle="No routes"
          emptyDescription="This organization has not defined any bus routes."
          columns={[
            { header: "Name", cell: (r) => r.name },
            { header: "Status", cell: (r) => <Badge variant={r.status === "active" ? "success" : "neutral"} dot>{r.status}</Badge> },
          ]}
        />
      );

    case "drivers":
      return (
        <DataList
          queryKey={[...base, "drivers"]}
          queryFn={() => orgDrivers(organizationId)}
          rowKey={(row) => row.id}
          emptyTitle="No drivers"
          emptyDescription="This organization has not registered any drivers."
          columns={[
            { header: "Licence", cell: (r) => r.licenseNo },
            { header: "Status", cell: (r) => <Badge variant={r.status === "active" ? "success" : "neutral"} dot>{r.status}</Badge> },
          ]}
        />
      );

    case "invoices":
      return (
        <DataList
          queryKey={[...base, "invoices"]}
          queryFn={() => orgInvoices(organizationId)}
          rowKey={(row) => row.id}
          emptyTitle="No invoices"
          emptyDescription="RAAD has not issued an invoice to this organization."
          columns={[
            { header: "Number", cell: (r) => <span className={styles.mono}>{r.number}</span> },
            { header: "Amount", cell: (r) => `${r.amount.toFixed(2)} ${r.currency}`, align: "right" },
            { header: "Status", cell: (r) => <Badge variant={invoiceStatusTone(r.status)} dot>{invoiceStatusLabel(r.status)}</Badge> },
            { header: "Period", cell: (r) => `${formatDateOnly(r.periodStart)} – ${formatDateOnly(r.periodEnd)}` },
            { header: "Issued", cell: (r) => (r.issuedAt ? formatDateOnly(r.issuedAt) : "—") },
          ]}
        />
      );

    case "payments":
      return (
        <DataList
          queryKey={[...base, "payments"]}
          queryFn={() => orgPayments(organizationId)}
          rowKey={(row) => row.id}
          emptyTitle="No payments"
          emptyDescription="No payment has been attempted against this organization's invoices."
          columns={[
            { header: "Date", cell: (r) => formatDateTime(r.createdAt) },
            { header: "Amount", cell: (r) => `${r.amount.toFixed(2)} ${r.currency}`, align: "right" },
            { header: "Provider", cell: (r) => r.provider },
            { header: "Status", cell: (r) => <Badge variant={paymentStatusTone(r.status)} dot>{paymentStatusLabel(r.status)}</Badge> },
            { header: "Confirmed", cell: (r) => (r.confirmedAt ? formatDateTime(r.confirmedAt) : "—") },
          ]}
        />
      );

    case "finance":
      return (
        <div className={styles.stack}>
          <div className={styles.notice}>
            <Info size={16} className={styles.noticeIcon} aria-hidden="true" />
            <p className={styles.noticeText}>
              This is the school's <strong>own</strong> money — what students and families pay it.
              It is a different financial domain from the RAAD subscription on the Invoices and
              Payments tabs, which is what this organization pays RAAD. The two are never combined
              into one balance.
            </p>
          </div>
          <section>
            <h3 className={styles.sectionTitle}>Student invoices</h3>
            <DataList
              queryKey={[...base, "student-invoices"]}
              queryFn={() => orgStudentInvoices(organizationId)}
              rowKey={(row) => row.id}
              emptyTitle="No student invoices"
              emptyDescription="This school has not billed any students yet."
              columns={[
                { header: "Period", cell: (r) => r.period },
                { header: "Student", cell: (r) => <span className={styles.mono}>{r.studentId}</span> },
                { header: "Net", cell: (r) => `${r.netAmount} ${r.currency}`, align: "right" },
                { header: "Paid", cell: (r) => r.amountPaid, align: "right" },
                { header: "Balance", cell: (r) => r.balanceDue, align: "right" },
                { header: "Status", cell: (r) => r.status.replace(/_/g, " ") },
              ]}
            />
          </section>
          <section>
            <h3 className={styles.sectionTitle}>Student payments</h3>
            <DataList
              queryKey={[...base, "student-payments"]}
              queryFn={() => orgStudentPayments(organizationId)}
              rowKey={(row) => row.id}
              emptyTitle="No student payments"
              emptyDescription="No family has paid against a student invoice yet."
              columns={[
                { header: "Received", cell: (r) => r.receivedOn },
                { header: "Amount", cell: (r) => `${r.amount} ${r.currency}`, align: "right" },
                { header: "Method", cell: (r) => r.method.replace(/_/g, " ") },
                { header: "State", cell: (r) => (r.isVoided ? "Voided" : "Recorded") },
              ]}
            />
          </section>
          <section>
            <h3 className={styles.sectionTitle}>Other income</h3>
            <DataList
              queryKey={[...base, "income"]}
              queryFn={() => orgIncome(organizationId)}
              rowKey={(row) => row.id}
              emptyTitle="No other income"
              emptyDescription="Donations, sponsorships and grants would appear here."
              columns={[
                { header: "Date", cell: (r) => r.occurredOn },
                { header: "Amount", cell: (r) => `${r.amount} ${r.currency}`, align: "right" },
                { header: "Description", cell: (r) => r.description ?? "—" },
              ]}
            />
          </section>
          <section>
            <h3 className={styles.sectionTitle}>Expenses</h3>
            <DataList
              queryKey={[...base, "expenses"]}
              queryFn={() => orgExpenses(organizationId)}
              rowKey={(row) => row.id}
              emptyTitle="No expenses"
              emptyDescription="Fuel, maintenance and other costs would appear here."
              columns={[
                { header: "Date", cell: (r) => r.occurredOn },
                { header: "Amount", cell: (r) => `${r.amount} ${r.currency}`, align: "right" },
                { header: "Description", cell: (r) => r.description ?? "—" },
              ]}
            />
          </section>
        </div>
      );

    case "usage":
      return <OrganizationUsageTab organizationId={organizationId} />;

    case "audit":
      return (
        <DataList
          queryKey={[...base, "audit"]}
          queryFn={() => orgAudit(organizationId)}
          rowKey={(row) => row.id}
          emptyTitle="No audit entries"
          emptyDescription="Nothing has been recorded against this organization."
          columns={[
            { header: "When", cell: (r) => formatDateTime(r.createdAt) },
            { header: "Action", cell: (r) => r.action },
            { header: "Entity", cell: (r) => r.entityType ?? "—" },
            { header: "Actor", cell: (r) => <span className={styles.mono}>{r.actorUserId ?? "system"}</span> },
          ]}
        />
      );

    case "settings":
      return <OrganizationSettingsTab organization={organization} onSelectTab={onSelectTab} />;

    default:
      return (
        <EmptyState
          icon={<Users size={20} />}
          title="Unknown tab"
          description="This tab does not exist."
        />
      );
  }
}
