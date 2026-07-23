import { Outlet } from "react-router-dom";
import { useAuthStore } from "../../shared/stores/authStore";
import { getNavForRole, type NavItem } from "./navConfig";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";
import { useCurrentPageHeader } from "./PageHeaderContext";
import styles from "./AppShell.module.css";

export interface AppShellProps {
  nav: NavItem[];
  notificationsPath: string;
}

/** The authenticated shell every feature page renders inside (`<Outlet />`), for both
 * dashboards — `router.tsx` supplies which `nav` tree, `AppShell` itself doesn't decide platform
 * vs. organization. */
export function AppShell({ nav, notificationsPath }: AppShellProps) {
  const principal = useAuthStore((s) => s.principal);
  const header = useCurrentPageHeader();

  if (!principal) {
    return null;
  }

  const visibleNav = getNavForRole(nav, principal.role);

  return (
    <div className={styles.shell}>
      <Sidebar nav={visibleNav} />
      <div className={styles.main}>
        <TopBar
          title={header.title}
          subtitle={header.subtitle}
          notificationsPath={notificationsPath}
        />
        <div className={styles.content}>
          <Outlet />
        </div>
      </div>
    </div>
  );
}
