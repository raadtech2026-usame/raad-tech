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

export function DashboardHomePage() {
  const principal = useAuthStore((s) => s.principal);
  const dashboardType = principal ? getDashboardType(principal.role) : "platform";
  const roleDisplay = principal ? getRoleDisplay(principal.role) : null;
  const isFinanceStaff = principal?.role === "finance_staff";

  usePageHeader(
    "Dashboard",
    dashboardType === "platform" ? "RAAD platform overview" : "Your organization at a glance",
  );

  const todayDisplay = new Date().toLocaleDateString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
  });

  return (
    <div className={clsx(styles.page, "raad-view-transition")}>
      <div className={styles.hero}>
        <div className={styles.heroMain}>
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

        <div className={styles.heroMeta}>
          <div className={styles.operationalStatus} title="Fleet Telematics System Active">
            <span className={styles.operationalDot} />
            <span>Telemetry Live</span>
          </div>
          <div className={styles.dateBadge}>{todayDisplay}</div>
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
