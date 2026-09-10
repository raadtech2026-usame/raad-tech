import clsx from "clsx";
import { useAuthStore } from "../shared/stores/authStore";
import { getRoleDisplay } from "../shared/auth/roleDisplay";
import { getDashboardType } from "../shared/auth/dashboard";
import { usePageHeader } from "./layout/PageHeaderContext";
import { Avatar } from "../shared/components/Avatar/Avatar";
import { PageSection } from "../shared/components/PageSection/PageSection";
import { KpiSection } from "./dashboard/KpiSection";
import { LiveOperationsSection } from "./dashboard/LiveOperationsSection";
import { RecentActivitySection } from "./dashboard/RecentActivitySection";
import { FleetHealthSection } from "./dashboard/FleetHealthSection";
import { DeviceHealthSection } from "./dashboard/DeviceHealthSection";
import { SubscriptionSummaryCard, RevenueSummaryCard } from "./dashboard/BillingSection";
import { PeopleSection } from "./dashboard/PeopleSection";
import { OrganizationOverviewSection } from "./dashboard/OrganizationOverviewSection";
import { SubscriptionStatusCard, SchoolFinanceSummaryCard } from "./dashboard/OrganizationFinanceSection";
import { QuickActionsSection } from "./dashboard/QuickActionsSection";
import dashboardStyles from "./dashboard/dashboard.module.css";
import styles from "./DashboardHomePage.module.css";

/**
 * The RAAD dashboard home page — rendered at both `/platform` (Founder/Regional Manager/Support
 * Staff/Finance Staff) and `/org` (Org Admin), branching on `getDashboardType(principal.role)`.
 *
 * **Platform branch:** a fleet-management SaaS home page (Fleetio/Samsara/Motive/Linear/
 * Stripe-Admin-comparable layout: a hero KPI row, an operations strip with a live map, an
 * activity/health mid-section, then billing) per the user's explicit brief. Every number comes
 * from an already-existing backend route — `GET /admin/platform-stats` (ADR-0020) backs the KPI
 * row, Device Health, and Billing; `GET /admin/audit` backs Recent Activity; `GET /vehicles`/
 * `GET /trips` back Fleet Health and Live Operations.
 *
 * **Finance Staff sees a narrower platform page, not a broken one.** Confirmed against the
 * seeded RBAC matrix, not assumed: `finance_staff` holds none of `fleet_device.vehicles.read`,
 * `transport_ops.{drivers,trips}.list`, `transport_ops.{students,parents}.count`, or
 * `admin.audit.read` — Live Operations/Fleet Health/Recent Activity/People are omitted for this
 * role rather than shown four times as "could not load", mirroring `navConfig.ts`'s own
 * `FINANCE_ALLOWED_PATHS` precedent.
 *
 * **Organization branch (fixed 2026-09-10 — a real, previously undetected gap, not a redesign).**
 * This branch used to not exist at all: `dashboardType === "platform"` gated the entire page
 * body, so an Org Admin's own `/org` home rendered nothing but the welcome hero — no KPIs, no
 * fleet, no finance, nothing — and a test (`DashboardHomePage.test.tsx`, "hides every platform
 * section entirely for an Org Admin") had been written to assert that emptiness as the *intended*
 * behavior, which is exactly how a missing feature survives a green test suite. `Organization
 * OverviewSection`/`OrganizationFinanceSection`/`QuickActionsSection` close it, composing
 * endpoints already confirmed live and reachable for `org_admin` (2026-09-10, real HTTP calls
 * against a real token — `/vehicles`, `/devices`, `/drivers`, `/routes`, `/trips`, `/students`,
 * `/parents`, `/billing/subscriptions/current`, `/school-finance/summary`), never the
 * platform-wide `GET /admin/platform-stats`/`GET /admin/audit` this role cannot reach. No Classes/
 * Grades — out of scope by explicit direction, and nothing here needed them anyway. "Assigned/
 * unassigned students" is deliberately not shown: the only backing read, `GET
 * /student-assignments`, is documented as not yet tenant-scoped server-side (a pre-existing,
 * separately-tracked gap) — showing a count from it risks either a wrong number or a real
 * cross-tenant leak, and this page will not paper over that with a number that might be wrong.
 *
 * 2026-09-05 redesign (platform branch only). Two structural changes, no data change: the
 * welcome card became a page hero rather than a boxed card (it carried a gradient and a
 * paragraph directly above the KPI row — two card-shaped objects in sequence, the first saying
 * nothing measurable); and sections moved onto the shared `PageSection` primitive, so this page
 * and the ERP finance pages cannot drift apart on section spacing and label treatment.
 */
export function DashboardHomePage() {
  const principal = useAuthStore((s) => s.principal);
  const dashboardType = principal ? getDashboardType(principal.role) : "platform";
  const roleDisplay = principal ? getRoleDisplay(principal.role) : null;
  const isFinanceStaff = principal?.role === "finance_staff";

  usePageHeader(
    "Dashboard",
    dashboardType === "platform" ? "RAAD platform overview" : "Your organization at a glance",
  );

  return (
    <div className={clsx(styles.page, "raad-view-transition")}>
      <div className={styles.hero}>
        {roleDisplay && (
          <Avatar initials={roleDisplay.abbreviation} color={roleDisplay.color} size="lg" square />
        )}
        <div className={styles.heroText}>
          <h2 className={styles.heroTitle}>Welcome{roleDisplay ? `, ${roleDisplay.label}` : ""}</h2>
          <p className={styles.heroBody}>
            {dashboardType === "platform"
              ? "Fleet, tracking, billing and reporting across every organization on the RAAD platform."
              : "Fleet, tracking and rider activity across your organization."}
          </p>
        </div>
      </div>

      {dashboardType === "platform" && (
        <>
          <PageSection title="Platform overview">
            <KpiSection />
          </PageSection>

          {!isFinanceStaff && (
            <PageSection title="Live operations">
              <LiveOperationsSection />
            </PageSection>
          )}

          <PageSection title={isFinanceStaff ? "Device health" : "Activity & health"}>
            {isFinanceStaff ? (
              <DeviceHealthSection />
            ) : (
              <div className={dashboardStyles.panelRow}>
                <div className={dashboardStyles.panelWide}>
                  <RecentActivitySection />
                </div>
                <div className={dashboardStyles.panelNarrow}>
                  <FleetHealthSection />
                  <DeviceHealthSection />
                </div>
              </div>
            )}
          </PageSection>

          <PageSection title="Billing">
            <div className={dashboardStyles.panelRow}>
              <div className={dashboardStyles.panelHalf}>
                <SubscriptionSummaryCard />
              </div>
              <div className={dashboardStyles.panelHalf}>
                <RevenueSummaryCard />
              </div>
            </div>
          </PageSection>

          {!isFinanceStaff && (
            <PageSection title="People">
              <PeopleSection />
            </PageSection>
          )}
        </>
      )}

      {dashboardType === "organization" && (
        <>
          <PageSection title="Organization overview">
            <OrganizationOverviewSection />
          </PageSection>

          <PageSection title="Finance">
            <div className={dashboardStyles.panelRow}>
              <div className={dashboardStyles.panelHalf}>
                <SubscriptionStatusCard />
              </div>
              <div className={dashboardStyles.panelHalf}>
                <SchoolFinanceSummaryCard />
              </div>
            </div>
          </PageSection>

          <PageSection title="Quick actions">
            <QuickActionsSection />
          </PageSection>
        </>
      )}
    </div>
  );
}
