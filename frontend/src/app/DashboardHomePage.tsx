import { useAuthStore } from "../shared/stores/authStore";
import { getRoleDisplay } from "../shared/auth/roleDisplay";
import { getDashboardType } from "../shared/auth/dashboard";
import { usePageHeader } from "./layout/PageHeaderContext";
import { Card } from "../shared/components/Card/Card";
import styles from "./DashboardHomePage.module.css";

/**
 * Deliberately does not show fleet/trip/rider KPI numbers yet — the approved design's dashboard
 * mockup shows fixed sample figures ("48 trips today", "18 live"), but no aggregate summary
 * endpoint exists on the backend to back them for real. Fabricating numbers here would violate
 * this project's own "fail loudly, don't fake it" posture; the real KPI grid lands once its
 * feature phase does.
 */
export function DashboardHomePage() {
  const principal = useAuthStore((s) => s.principal);
  const dashboardType = principal ? getDashboardType(principal.role) : "platform";
  const roleDisplay = principal ? getRoleDisplay(principal.role) : null;

  usePageHeader(
    "Dashboard",
    dashboardType === "platform" ? "RAAD platform overview" : "Your organization at a glance",
  );

  return (
    <div className={styles.grid}>
      <Card className={styles.welcomeCard}>
        <div className={styles.welcomeTitle}>Welcome{roleDisplay ? `, ${roleDisplay.label}` : ""}</div>
        <p className={styles.welcomeBody}>
          {dashboardType === "platform"
            ? "This is the RAAD platform console. Fleet, tracking, billing, and reporting summaries will appear here as each module comes online."
            : "This is your organization's console. Fleet, tracking, and rider summaries for your organization will appear here as each module comes online."}
        </p>
      </Card>
    </div>
  );
}
