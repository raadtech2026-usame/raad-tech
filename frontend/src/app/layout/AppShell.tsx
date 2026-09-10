import { useCallback, useEffect, useState } from "react";
import { Outlet, useLocation } from "react-router-dom";
import { useAuthStore } from "../../shared/stores/authStore";
import { useUnreadCount } from "../../features/notifications/useUnreadCount";
import { getNavForRole, type NavItem } from "./navConfig";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";
import { useCurrentPageHeader } from "./PageHeaderContext";
import styles from "./AppShell.module.css";
import { SubscriptionInactiveNotice } from "../../shared/subscription/SubscriptionInactiveNotice";

export interface AppShellProps {
  nav: NavItem[];
  notificationsPath: string;
}

const RAIL_STORAGE_KEY = "raad.sidebar.rail";

function readRailPreference(): boolean {
  try {
    return window.localStorage.getItem(RAIL_STORAGE_KEY) === "true";
  } catch {
    return false;
  }
}

/** The authenticated shell every feature page renders inside (`<Outlet />`), for both
 * dashboards — `router.tsx` supplies which `nav` tree, `AppShell` itself doesn't decide platform
 * vs. organization.
 *
 * It owns the two pieces of chrome state the sidebar and topbar both need to agree on: the
 * desktop rail (icon-only) toggle, and the mobile off-canvas drawer. Keeping both here rather
 * than inside `Sidebar` is what lets the topbar host the mobile menu button and the shell
 * itself resize its content column in the same frame the rail animates. */
export function AppShell({ nav, notificationsPath }: AppShellProps) {
  const principal = useAuthStore((s) => s.principal);
  const header = useCurrentPageHeader();
  const location = useLocation();
  const [railCollapsed, setRailCollapsed] = useState(readRailPreference);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  // Unconditional (not gated behind `principal` below) so its Hook order never depends on
  // auth state — matches the Rules of Hooks; `useUnreadCount` itself only opens its
  // `/ws/notifications` connection once a real access token exists (`useWebSocketChannel`'s own
  // "no token yet" -> `closed` status).
  const unreadNotifications = useUnreadCount();

  // A navigation on mobile must close the drawer, otherwise the destination page renders behind
  // a panel the user has to dismiss by hand before they can see what they just opened.
  useEffect(() => {
    setMobileNavOpen(false);
  }, [location.pathname]);

  useEffect(() => {
    if (!mobileNavOpen) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setMobileNavOpen(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [mobileNavOpen]);

  const toggleRail = useCallback(() => {
    setRailCollapsed((prev) => {
      const next = !prev;
      try {
        window.localStorage.setItem(RAIL_STORAGE_KEY, String(next));
      } catch {
        // Preference simply isn't remembered; the toggle still works this session.
      }
      return next;
    });
  }, []);

  if (!principal) {
    return null;
  }

  const visibleNav = getNavForRole(nav, principal.role);

  return (
    <div className={styles.shell}>
      <div className={styles.frame}>
        <Sidebar
          nav={visibleNav}
          collapsed={railCollapsed}
          onToggleCollapsed={toggleRail}
          mobileOpen={mobileNavOpen}
          onNavigate={() => setMobileNavOpen(false)}
        />

        {/* Scrim exists only while the mobile drawer is open — it is the tap target that closes
            it, which a swipe-only dismissal would leave users hunting for. */}
        {mobileNavOpen && (
          <button
            type="button"
            className={styles.scrim}
            aria-label="Close navigation menu"
            onClick={() => setMobileNavOpen(false)}
          />
        )}

        <div className={styles.main}>
          <TopBar
            title={header.title}
            subtitle={header.subtitle}
            notificationsPath={notificationsPath}
            unreadNotifications={unreadNotifications}
            onOpenMobileNav={() => setMobileNavOpen(true)}
          />
          <div className={styles.content}>
            <div className={styles.contentInner}>
              {/* ADR-0039 §6 — a tenant-wide subscription block is one account state, so it is
                  surfaced once here rather than as a per-screen error. Above the outlet, not as
                  a modal: Billing stays reachable (ADR-0039 §3's exempt paths) so an Org Admin
                  can actually pay and recover, which a trapping dialog would prevent. */}
              <SubscriptionInactiveNotice />
              <Outlet />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
