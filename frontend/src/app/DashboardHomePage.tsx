import clsx from "clsx";
import { useAuthStore } from "../shared/stores/authStore";
import { getRoleDisplay } from "../shared/auth/roleDisplay";
import { getDashboardType } from "../shared/auth/dashboard";
import { usePageHeader } from "./layout/PageHeaderContext";
import { Avatar } from "../shared/components/Avatar/Avatar";
import { Card } from "../shared/components/Card/Card";
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
 * The RAAD Founder/Platform dashboard — redesigned as a fleet-management SaaS home page
 * (Fleetio/Samsara/Motive/Linear/Stripe-Admin-comparable layout: a hero KPI row, an operations
 * strip with a live map, an activity/health mid-section, then billing) per the user's explicit
 * brief. **Every number on this page comes from an already-existing backend route** — no new
 * API, no new permission, no fabricated figure: `GET /admin/platform-stats` (ADR-0020) backs the
 * KPI row, Device Health, and Billing; `GET /admin/audit` (existing, previously unconsumed by
 * any frontend page) backs Recent Activity; `GET /vehicles`/`GET /trips` (existing, count-only
 * reads mirroring this page's own pre-existing drivers-count pattern) back Fleet Health and Live
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
      <Card className={styles.welcomeCard}>
        {roleDisplay && <Avatar initials={roleDisplay.abbreviation} color={roleDisplay.color} size="lg" />}
        <div className={styles.welcomeText}>
          <span className={styles.welcomeTitle}>Welcome{roleDisplay ? `, ${roleDisplay.label}` : ""}</span>
          <p className={styles.welcomeBody}>
            {dashboardType === "platform"
              ? "This is the RAAD platform console. Fleet, tracking, billing, and reporting summaries will appear here as each module comes online."
              : "This is your organization's console. Fleet, tracking, and rider summaries for your organization will appear here as each module comes online."}
          </p>
        </div>
      </Card>

      {dashboardType === "platform" && (
        <>
          <div className={dashboardStyles.section}>
            <span className={dashboardStyles.sectionLabel}>Platform overview</span>
            <KpiSection />
          </div>

          {!isFinanceStaff && (
            <div className={dashboardStyles.section}>
              <span className={dashboardStyles.sectionLabel}>Live operations</span>
              <LiveOperationsSection />
            </div>
          )}

          <div className={dashboardStyles.section}>
            <span className={dashboardStyles.sectionLabel}>
              {isFinanceStaff ? "Device health" : "Activity & health"}
            </span>
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
          </div>

          <div className={dashboardStyles.section}>
            <span className={dashboardStyles.sectionLabel}>Billing</span>
            <div className={dashboardStyles.panelRow}>
              <div className={dashboardStyles.panelHalf}>
                <SubscriptionSummaryCard />
              </div>
              <div className={dashboardStyles.panelHalf}>
                <RevenueSummaryCard />
              </div>
            </div>
          </div>

          {!isFinanceStaff && (
            <div className={dashboardStyles.section}>
              <span className={dashboardStyles.sectionLabel}>People</span>
              <PeopleSection />
            </div>
          )}
        </>
      )}
    </div>
  );
}
