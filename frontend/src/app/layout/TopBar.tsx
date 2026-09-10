import { useEffect, useRef, useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { Search, Bell, CircleHelp, LogOut, Menu } from "lucide-react";
import { useAuthStore } from "../../shared/stores/authStore";
import { getRoleDisplay } from "../../shared/auth/roleDisplay";
import { Avatar } from "../../shared/components/Avatar/Avatar";
import { IconButton } from "../../shared/components/IconButton/IconButton";
import { Input } from "../../shared/components/Input/Input";
import styles from "./TopBar.module.css";

export interface TopBarProps {
  title: ReactNode;
  subtitle?: ReactNode;
  notificationsPath: string;
  liveIndicator?: ReactNode;
  unreadNotifications?: number;
  /** Opens the off-canvas navigation. Only rendered below the tablet breakpoint, where the
   * sidebar leaves the layout flow. */
  onOpenMobileNav?: () => void;
}

export function TopBar({
  title,
  subtitle,
  notificationsPath,
  liveIndicator,
  unreadNotifications,
  onOpenMobileNav,
}: TopBarProps) {
  const principal = useAuthStore((s) => s.principal);
  const logout = useAuthStore((s) => s.logout);
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();

  // An account menu that only closes via its own trigger is a menu users leave open by accident
  // and then click straight through. Both dismissal paths a menu is expected to have:
  useEffect(() => {
    if (!menuOpen) return;
    const onPointerDown = (event: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        setMenuOpen(false);
      }
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setMenuOpen(false);
    };
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [menuOpen]);

  if (!principal) {
    return null;
  }

  const roleDisplay = getRoleDisplay(principal.role);

  return (
    <header className={styles.topbar}>
      {onOpenMobileNav && (
        <button
          type="button"
          className={styles.menuButton}
          onClick={onOpenMobileNav}
          aria-label="Open navigation menu"
        >
          <Menu size={20} />
        </button>
      )}

      <div className={styles.titleBlock}>
        <h1 className={styles.title}>{title}</h1>
        {subtitle && <div className={styles.subtitle}>{subtitle}</div>}
      </div>

      <div className={styles.search}>
        <Input
          placeholder="Search buses, students, routes…"
          icon={<Search size={16} />}
          disabled
          title="Global search is not available yet"
          aria-label="Global search (not available yet)"
        />
      </div>

      <div className={styles.actions}>
        {liveIndicator}
        <IconButton
          icon={<Bell size={18} />}
          aria-label="Notifications"
          badgeCount={unreadNotifications}
          onClick={() => navigate(notificationsPath)}
        />
        <IconButton icon={<CircleHelp size={18} />} aria-label="Help" className={styles.helpButton} />

        <span className={styles.divider} aria-hidden="true" />

        <div className={styles.accountMenu} ref={menuRef}>
          <button
            type="button"
            className={styles.accountTrigger}
            onClick={() => setMenuOpen((open) => !open)}
            aria-haspopup="menu"
            aria-expanded={menuOpen}
            aria-label="Account menu"
          >
            <Avatar initials={roleDisplay.abbreviation} color={roleDisplay.color} size="md" />
            <span className={styles.accountLabel}>{roleDisplay.label}</span>
          </button>
          {menuOpen && (
            <div className={styles.dropdown} role="menu">
              <div className={styles.dropdownHeader}>
                <div className={styles.dropdownName}>{roleDisplay.label}</div>
                <div className={styles.dropdownRole}>{principal.userId}</div>
              </div>
              <button
                type="button"
                role="menuitem"
                className={styles.dropdownItem}
                onClick={() => void logout()}
              >
                <LogOut size={15} />
                Sign out
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
