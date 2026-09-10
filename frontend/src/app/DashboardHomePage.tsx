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
import dashboardStyles from "./dashboard/dashboard.module.css";
import styles from "./DashboardHomePage.module.css";

/**
 * The RAAD Founder/Platform dashboard — a fleet-management SaaS home page (Fleetio/Samsara/
 * Motive/Linear/Stripe-Admin-comparable layout: a hero KPI row, an operations strip with a live
 * map, an activity/health mid-section, then billing) per the user's explicit brief. **Every
 * number on this page comes from an already-existing backend route** — no new API, no new
 * permission, no fabricated figure: `GET /admin/platform-stats` (ADR-0020) backs the KPI row,
 * Device Health, and Billing; `GET /admin/audit` (existing) backs Recent Activity;
 * `GET /vehicles`/`GET /trips` (existing, count-only reads) back Fleet Health and Live
 * Operations. Wherever a section names a KPI the backend genuinely has no data for (a revenue
 * trend, live fleet-wide vehicle positions beyond one at a time, an activity actor's display
 * name), it shows a real empty/partial state instead — never an invented number.
 *
 * **Finance Staff sees a narrower page, not a broken one.** Confirmed against the seeded RBAC
 * matrix (`migrations/versions/20260721..._5437a5d1651b...py`), not assumed: `finance_staff`
 * holds none of `fleet_device.vehicles.read`, `transport_ops.{drivers,trips}.list`,
 * `transport_ops.{students,parents}.count`, or `admin.audit.read` — every one of Live
 * Operations/Fleet Health/Recent Activity/People would 403 for this role alone (the other three
 * platform roles all hold every one of those grants). Rather than showing four "could not load"
 * errors for what is actually a permanent, correct restriction, those four sections are omitted
 * for Finance Staff, mirroring `navConfig.ts`'s own `FINANCE_ALLOWED_PATHS` precedent — the KPI
 * row, Device Health, and Billing all key off `admin.platform_stats.read` alone, which Finance
 * Staff does hold (ADR-0020 granted it explicitly for this reason), so those stay visible.
 *
 * 2026-09-05 redesign. Two structural changes, no data change:
 *   - The welcome card is a page hero rather than a boxed card. It was a bordered surface
 *     carrying a gradient and a paragraph of prose, directly above the KPI row — two card-shaped
 *     objects in a row, the first of which said nothing measurable. It is now unboxed greeting
 *     text, so the KPI row is the first *card* on the page and the visual hierarchy starts where
 *     the information does.
 *   - Sections use the shared `PageSection` primitive, so this page and the ERP finance pages
 *     cannot drift apart on section spacing and label treatment.
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
    </div>
  );
}
