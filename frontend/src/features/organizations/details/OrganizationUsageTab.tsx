import { useQuery } from "@tanstack/react-query";
import { Info } from "lucide-react";
import { Badge } from "../../../shared/components/Badge/Badge";
import { Skeleton } from "../../../shared/components/Skeleton/Skeleton";
import { listPlans } from "../../billing/api";
import {
  orgDevices,
  orgParentCount,
  orgStudentCount,
  orgSubscriptions,
  orgUsers,
  orgVehicles,
} from "./api";
import styles from "./OrganizationDetailsPage.module.css";

/**
 * What this organization consumes, against what its plan includes.
 *
 * **Every number here is a real count, and the ones that are not measurable are named rather
 * than estimated.** `plans` carries `vehicleLimit`, `deviceLimit` and `userLimit` (ADR-0040 §4),
 * so those three allowances have a genuine numerator and denominator. Storage, video minutes,
 * SMS, API calls and bandwidth are *not metered anywhere in this platform* — there is no
 * collection point, no table and no aggregate for any of them — so they are listed as
 * unmeasured with an explanation instead of being shown as zero. A zero would read as "nothing
 * used", which is a different and false claim.
 */

interface UsageRow {
  label: string;
  used: number | null;
  limit: number | null;
  note?: string;
}

function UsageBar({ used, limit }: { used: number; limit: number | null }) {
  if (limit === null || limit <= 0) {
    return <span className={styles.unlimited}>Unlimited</span>;
  }
  const pct = Math.min(100, Math.round((used / limit) * 100));
  const tone = pct >= 100 ? "danger" : pct >= 80 ? "warning" : "ok";
  return (
    <div className={styles.usageBarWrap}>
      <div className={styles.usageBar}>
        <div
          className={clsxTone(tone)}
          style={{ width: `${pct}%` }}
          role="progressbar"
          aria-valuenow={used}
          aria-valuemin={0}
          aria-valuemax={limit}
        />
      </div>
      <span className={styles.usagePct}>{pct}%</span>
    </div>
  );
}

function clsxTone(tone: "ok" | "warning" | "danger"): string {
  return `${styles.usageFill} ${
    tone === "danger" ? styles.usageDanger : tone === "warning" ? styles.usageWarning : ""
  }`;
}

const LIST_ONE = { page: 1, pageSize: 1, sort: null, filters: {}, search: "" };

export function OrganizationUsageTab({ organizationId }: { organizationId: string }) {
  const base = ["organizations", "detail", organizationId, "usage"] as const;

  // `pageSize: 1` throughout — every one of these reads is for its `.total`, so fetching a full
  // page of rows the tab never renders would be pure waste.
  const vehicles = useQuery({
    queryKey: [...base, "vehicles"],
    queryFn: () => orgVehicles(organizationId, LIST_ONE),
    staleTime: 60_000,
  });
  const devices = useQuery({
    queryKey: [...base, "devices"],
    queryFn: () => orgDevices(organizationId, LIST_ONE),
    staleTime: 60_000,
  });
  const users = useQuery({
    queryKey: [...base, "users"],
    queryFn: () => orgUsers(organizationId, LIST_ONE),
    staleTime: 60_000,
  });
  const students = useQuery({
    queryKey: [...base, "students"],
    queryFn: () => orgStudentCount(organizationId),
    staleTime: 60_000,
  });
  const parents = useQuery({
    queryKey: [...base, "parents"],
    queryFn: () => orgParentCount(organizationId),
    staleTime: 60_000,
  });
  const subscription = useQuery({
    queryKey: ["organizations", "detail", organizationId, "subscriptions"],
    queryFn: () => orgSubscriptions(organizationId),
    staleTime: 60_000,
  });
  const plans = useQuery({
    queryKey: ["billing", "plans", "lookup"],
    queryFn: () =>
      listPlans({ page: 1, pageSize: 100, sort: null, filters: {}, search: "" }),
    staleTime: 5 * 60_000,
  });

  const planId = subscription.data?.data[0]?.planId ?? null;
  const plan = plans.data?.data.find((p) => p.id === planId) ?? null;

  const loading =
    vehicles.isPending || devices.isPending || users.isPending || subscription.isPending;

  if (loading) {
    return (
      <>
        <Skeleton height={18} />
        <Skeleton height={18} />
        <Skeleton height={18} />
      </>
    );
  }

  const metered: UsageRow[] = [
    { label: "Vehicles", used: vehicles.data?.page.total ?? 0, limit: plan?.vehicleLimit ?? null },
    { label: "Devices", used: devices.data?.page.total ?? 0, limit: plan?.deviceLimit ?? null },
    { label: "Users", used: users.data?.page.total ?? 0, limit: plan?.userLimit ?? null },
    { label: "Students", used: students.data ?? 0, limit: null, note: "No plan allowance defined" },
    { label: "Parents", used: parents.data ?? 0, limit: null, note: "No plan allowance defined" },
  ];

  const unmeasured = [
    "Storage",
    "Video minutes",
    "SMS",
    "API calls",
    "Bandwidth",
  ];

  return (
    <div className={styles.stack}>
      <p className={styles.count}>
        {plan ? (
          <>
            Measured against plan <strong>{plan.name}</strong>
          </>
        ) : (
          "No active plan — allowances cannot be shown"
        )}
      </p>

      <div className={styles.tableScroll}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th>Resource</th>
              <th className={styles.alignRight}>Used</th>
              <th className={styles.alignRight}>Included</th>
              <th>Consumption</th>
            </tr>
          </thead>
          <tbody>
            {metered.map((row) => (
              <tr key={row.label}>
                <td>{row.label}</td>
                <td className={styles.alignRight}>{row.used ?? "—"}</td>
                <td className={styles.alignRight}>
                  {row.limit === null ? (row.note ? "—" : "Unlimited") : row.limit}
                </td>
                <td>
                  {row.note ? (
                    <span className={styles.muted}>{row.note}</span>
                  ) : (
                    <UsageBar used={row.used ?? 0} limit={row.limit} />
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className={styles.notice}>
        <Info size={16} className={styles.noticeIcon} aria-hidden="true" />
        <div>
          <p className={styles.noticeText}>
            <strong>Not measured on this platform:</strong>{" "}
            {unmeasured.map((item, index) => (
              <Badge key={item} variant="neutral">
                {item}
                {index < unmeasured.length - 1 ? "" : ""}
              </Badge>
            ))}
          </p>
          <p className={styles.noticeText}>
            RAAD has no metering for these — no collection point, no table, no aggregate exists
            for any of them. They are listed here so the gap is visible rather than shown as zero,
            which would wrongly read as “nothing used”. Metering them is a separate piece of work:
            it needs write points in the ingest and video paths, a retention policy and an
            aggregation table.
          </p>
        </div>
      </div>
    </div>
  );
}
