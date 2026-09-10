import { useCallback, useEffect, useMemo, useState } from "react";
import { NavLink, useLocation } from "react-router-dom";
import clsx from "clsx";
import { ChevronDown, PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { Logo } from "../../shared/components/Logo/Logo";
import { Avatar } from "../../shared/components/Avatar/Avatar";
import { useAuthStore } from "../../shared/stores/authStore";
import { getRoleDisplay } from "../../shared/auth/roleDisplay";
import type { NavItem, NavLinkItem } from "./navConfig";
import styles from "./Sidebar.module.css";

export interface SidebarProps {
  nav: NavItem[];
  /** Rail (icon-only) mode. Owned by `AppShell` so the topbar's own toggle and the shell's
   * grid width stay in sync with it. Ignored while the mobile drawer is open — a 72px rail on
   * a phone is worse than either full state. */
  collapsed?: boolean;
  onToggleCollapsed?: () => void;
  /** Mobile off-canvas state. On desktop the sidebar is always present and these are unused. */
  mobileOpen?: boolean;
  onNavigate?: () => void;
}

/** A section header plus the links that follow it, which is exactly how `navConfig.ts` already
 * expresses structure — as a flat list with `type: "header"` separators.
 *
 * Grouping is derived here rather than restructuring `navConfig` into a nested tree on purpose:
 * `getNavForRole` filters that flat list and drops headers left empty, and its behaviour is
 * covered by `navConfig.test.ts`. Deriving the tree at render time gives the collapsible
 * grouping this redesign needs without changing the shape any of that logic operates on. */
interface NavGroup {
  label: string | null;
  items: NavLinkItem[];
}

function groupNav(nav: NavItem[]): NavGroup[] {
  const groups: NavGroup[] = [];
  let current: NavGroup | null = null;

  for (const item of nav) {
    if (item.type === "header") {
      current = { label: item.label, items: [] };
      groups.push(current);
      continue;
    }
    if (!current) {
      // Links before any header (none today, but the shape allows it) stay ungrouped at the top
      // rather than being silently swallowed into the first named group below them.
      current = { label: null, items: [] };
      groups.push(current);
    }
    current.items.push(item);
  }

  return groups.filter((group) => group.items.length > 0);
}

const STORAGE_KEY = "raad.sidebar.collapsedGroups";

/** Which groups the user has collapsed, persisted so the sidebar looks the way they left it on
 * the next visit. Stored as the *collapsed* set rather than the expanded one so a newly added
 * nav group defaults to open instead of being hidden by a stale saved list.
 *
 * Not sensitive data (`.claude/rules/frontend.md` #5 governs tokens and account data) — this is
 * a UI preference, and a read failure degrades to "everything expanded", never to an error. */
function readCollapsedGroups(): string[] {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.filter((v): v is string => typeof v === "string") : [];
  } catch {
    return [];
  }
}

export function Sidebar({
  nav,
  collapsed = false,
  onToggleCollapsed,
  mobileOpen = false,
  onNavigate,
}: SidebarProps) {
  const groups = useMemo(() => groupNav(nav), [nav]);
  const location = useLocation();
  const principal = useAuthStore((s) => s.principal);
  const [collapsedGroups, setCollapsedGroups] = useState<string[]>(readCollapsedGroups);

  useEffect(() => {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(collapsedGroups));
    } catch {
      // A private-mode/quota failure must not break navigation — the preference is simply not
      // remembered for next time.
    }
  }, [collapsedGroups]);

  const toggleGroup = useCallback((label: string) => {
    setCollapsedGroups((prev) =>
      prev.includes(label) ? prev.filter((l) => l !== label) : [...prev, label],
    );
  }, []);

  const roleDisplay = principal ? getRoleDisplay(principal.role) : null;

  return (
    <aside
      className={clsx(
        styles.sidebar,
        collapsed && styles.collapsed,
        mobileOpen && styles.mobileOpen,
      )}
      data-collapsed={collapsed ? "true" : "false"}
    >
      <div className={styles.brand}>
        <Logo
          size={32}
          withWordmark={!collapsed}
          wordmarkColor="var(--color-text-primary)"
          taglineColor="var(--color-text-faint)"
        />
        {onToggleCollapsed && (
          <button
            type="button"
            className={styles.railToggle}
            onClick={onToggleCollapsed}
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          >
            {collapsed ? <PanelLeftOpen size={17} /> : <PanelLeftClose size={17} />}
          </button>
        )}
      </div>

      <nav className={styles.nav} aria-label="Primary">
        {groups.map((group, index) => {
          const isCollapsedGroup = group.label !== null && collapsedGroups.includes(group.label);
          // A group holding one link renders as that link, promoted to the top level: a
          // disclosure control that reveals exactly one row is pure friction, and this happens
          // for real (Finance Staff's "Platform" group filters down to Organizations alone).
          const isStandalone = group.items.length === 1;
          // In rail mode there is no room for a group label or a disclosure arrow, so groups
          // become icon runs separated by a hairline rule.
          const showHeader = group.label !== null && !isStandalone && !collapsed;
          const groupId = `nav-group-${index}`;
          const containsActive = group.items.some(
            (item) =>
              location.pathname === item.path ||
              (item.path !== "/platform" &&
                item.path !== "/org" &&
                location.pathname.startsWith(`${item.path}/`)),
          );

          return (
            <div
              key={group.label ?? `group-${index}`}
              className={clsx(styles.group, collapsed && styles.groupRail)}
            >
              {showHeader && (
                <button
                  type="button"
                  className={clsx(styles.groupHeader, containsActive && styles.groupHeaderActive)}
                  onClick={() => toggleGroup(group.label as string)}
                  aria-expanded={!isCollapsedGroup}
                  aria-controls={groupId}
                >
                  <span className={styles.groupLabel}>{group.label}</span>
                  <ChevronDown
                    size={14}
                    className={clsx(styles.groupChevron, isCollapsedGroup && styles.groupChevronClosed)}
                    aria-hidden="true"
                  />
                </button>
              )}

              {/* `grid-template-rows: 1fr -> 0fr` animates an unknown content height with no
                  JS measurement and no max-height guess that clips a long group. The closed
                  state also sets `visibility: hidden`, which is what actually pulls the hidden
                  links out of the tab order — a purely visual collapse leaves them focusable. */}
              <div
                id={groupId}
                className={clsx(
                  styles.groupItems,
                  showHeader && isCollapsedGroup && styles.groupItemsClosed,
                )}
              >
                <div className={styles.groupItemsInner}>
                  {group.items.map((item) => (
                    <NavLink
                      key={item.path}
                      to={item.path}
                      end={item.path === "/platform" || item.path === "/org"}
                      onClick={onNavigate}
                      className={({ isActive }) => clsx(styles.link, isActive && styles.linkActive)}
                      title={collapsed ? item.label : undefined}
                    >
                      <span className={styles.linkIcon}>
                        <item.icon size={18} strokeWidth={1.9} aria-hidden="true" />
                      </span>
                      <span className={styles.linkLabel}>{item.label}</span>
                      {/* Decorative duplicate of the label above — hidden from the accessibility
                          tree so a rail-mode link is not announced as "Vehicles Vehicles". In
                          rail mode `.linkLabel` is visually hidden rather than `display: none`,
                          so the accessible name is the same in both modes. */}
                      {collapsed && (
                        <span className={styles.railTooltip} aria-hidden="true">
                          {item.label}
                        </span>
                      )}
                    </NavLink>
                  ))}
                </div>
              </div>
            </div>
          );
        })}
      </nav>

      {/* Identity anchored to the foot of the rail, mirroring the reference layout. The topbar
          account menu remains the only place that can sign out — this is a "who am I" marker,
          not a second, competing menu for the same actions. */}
      {roleDisplay && (
        <div className={styles.account}>
          <Avatar initials={roleDisplay.abbreviation} color={roleDisplay.color} size="md" square />
          <span className={styles.accountText}>
            <span className={styles.accountName}>{roleDisplay.label}</span>
            <span className={styles.accountMeta}>
              {principal?.organizationId ? "Organization" : "RAAD Platform"}
            </span>
          </span>
        </div>
      )}
    </aside>
  );
}
