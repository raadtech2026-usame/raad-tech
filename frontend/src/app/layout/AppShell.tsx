import { Outlet } from "react-router-dom";
import { useAuthStore } from "../../shared/stores/authStore";
import { useUnreadCount } from "../../features/notifications/useUnreadCount";
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
  // Unconditional (not gated behind `principal` below) so its Hook order never depends on
  // auth state — matches the Rules of Hooks; `useUnreadCount` itself only opens its
  // `/ws/notifications` connection once a real access token exists (`useWebSocketChannel`'s own
  // "no token yet" -> `closed` status).
  const unreadNotifications = useUnreadCount();

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
          unreadNotifications={unreadNotifications}
        />
        <div className={styles.content}>
          <Outlet />
        </div>
      </div>
    </div>
  );
}
