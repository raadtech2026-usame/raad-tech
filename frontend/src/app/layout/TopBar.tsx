import { useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { Search, Bell, CircleHelp, LogOut } from "lucide-react";
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
}

export function TopBar({
  title,
  subtitle,
  notificationsPath,
  liveIndicator,
  unreadNotifications,
}: TopBarProps) {
  const principal = useAuthStore((s) => s.principal);
  const logout = useAuthStore((s) => s.logout);
  const [menuOpen, setMenuOpen] = useState(false);
  const navigate = useNavigate();

  if (!principal) {
    return null;
  }

  const roleDisplay = getRoleDisplay(principal.role);

  return (
    <header className={styles.topbar}>
      <div className={styles.titleBlock}>
        <div className={styles.title}>{title}</div>
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
          icon={<Bell size={19} />}
          aria-label="Notifications"
          badgeCount={unreadNotifications}
          onClick={() => navigate(notificationsPath)}
        />
        <IconButton icon={<CircleHelp size={19} />} aria-label="Help" />

        <div className={styles.accountMenu}>
          <button
            type="button"
            className={styles.accountTrigger}
            onClick={() => setMenuOpen((open) => !open)}
            aria-haspopup="menu"
            aria-expanded={menuOpen}
            aria-label="Account menu"
          >
            <Avatar initials={roleDisplay.abbreviation} color={roleDisplay.color} />
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
