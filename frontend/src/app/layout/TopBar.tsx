import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { Search, Bell, CircleHelp, LogOut, Menu, Sun, Moon } from "lucide-react";
import { useAuthStore } from "../../shared/stores/authStore";
import { useThemeStore } from "../../shared/theme/themeStore";
import { getRoleDisplay } from "../../shared/auth/roleDisplay";
import { Avatar } from "../../shared/components/Avatar/Avatar";
import { IconButton } from "../../shared/components/IconButton/IconButton";
import { Input } from "../../shared/components/Input/Input";
import { platformNav, organizationNav, getNavForRole } from "./navConfig";
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
  const { resolvedTheme, toggleTheme } = useThemeStore();
  const [menuOpen, setMenuOpen] = useState(false);
  const [quickJumpOpen, setQuickJumpOpen] = useState(false);
  const [quickJumpSearch, setQuickJumpSearch] = useState("");
  const quickJumpInputRef = useRef<HTMLInputElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setQuickJumpOpen((prev) => !prev);
      } else if (e.key === "Escape" && quickJumpOpen) {
        setQuickJumpOpen(false);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [quickJumpOpen]);

  useEffect(() => {
    if (quickJumpOpen) {
      const timer = setTimeout(() => quickJumpInputRef.current?.focus(), 50);
      return () => clearTimeout(timer);
    }
  }, [quickJumpOpen]);

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

  const availableNav = useMemo(() => {
    if (!principal) return [];
    const baseNav = principal.role === "org_admin" ? organizationNav : platformNav;
    const items = getNavForRole(baseNav, principal.role);
    return items.filter((item): item is Extract<typeof item, { type: "link" }> => item.type === "link");
  }, [principal]);

  const filteredNav = availableNav.filter((item) => {
    if (!quickJumpSearch.trim()) return true;
    const q = quickJumpSearch.toLowerCase();
    return item.label.toLowerCase().includes(q) || item.path.toLowerCase().includes(q);
  });

  const handleNavigate = (path: string) => {
    setQuickJumpOpen(false);
    setQuickJumpSearch("");
    navigate(path);
  };

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
        <div
          className={styles.searchInner}
          onClick={() => setQuickJumpOpen(true)}
          role="button"
          tabIndex={0}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              setQuickJumpOpen(true);
            }
          }}
          aria-label="Quick jump (⌘K)"
        >
          <Input
            placeholder="Search buses, students, routes…"
            icon={<Search size={15} />}
            readOnly
            title="Press ⌘K or click to open Quick Jump"
            aria-label="Global search (not available yet)"
          />
          <kbd className={styles.searchKbd} aria-hidden="true">⌘K</kbd>
        </div>
      </div>

      <div className={styles.actions}>
        {liveIndicator ?? (
          <div className={styles.telemetryStatus} title="Real-time telematics gateway active">
            <span className={styles.telemetryPulse} />
            <span className={styles.telemetryText}>Fleet Live</span>
          </div>
        )}
        <IconButton
          icon={<Bell size={18} />}
          aria-label="Notifications"
          badgeCount={unreadNotifications}
          onClick={() => navigate(notificationsPath)}
        />
        <IconButton icon={<CircleHelp size={18} />} aria-label="Help" className={styles.helpButton} />
        <IconButton
          icon={resolvedTheme === "dark" ? <Sun size={18} /> : <Moon size={18} />}
          aria-label={resolvedTheme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
          title={resolvedTheme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
          onClick={toggleTheme}
        />

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

      {quickJumpOpen && (
        <div
          className={styles.quickJumpOverlay}
          onClick={(e) => {
            if (e.target === e.currentTarget) setQuickJumpOpen(false);
          }}
        >
          <div className={styles.quickJumpModal} role="dialog" aria-modal="true" aria-label="Quick Jump">
            <div className={styles.quickJumpHeader}>
              <Search size={16} className={styles.quickJumpIcon} aria-hidden="true" />
              <input
                ref={quickJumpInputRef}
                type="text"
                className={styles.quickJumpInput}
                placeholder="Jump to a page (e.g. tracking, vehicles, routes)..."
                value={quickJumpSearch}
                onChange={(e) => setQuickJumpSearch(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && filteredNav.length > 0) {
                    handleNavigate(filteredNav[0].path);
                  }
                }}
              />
            </div>
            <div className={styles.quickJumpList}>
              {filteredNav.map((item) => {
                const Icon = item.icon;
                return (
                  <button
                    key={item.path}
                    type="button"
                    className={styles.quickJumpItem}
                    onClick={() => handleNavigate(item.path)}
                  >
                    <Icon size={16} className={styles.quickJumpItemIcon} aria-hidden="true" />
                    <span>{item.label}</span>
                    <span className={styles.quickJumpPath}>{item.path}</span>
                  </button>
                );
              })}
              {filteredNav.length === 0 && (
                <div className={styles.quickJumpEmpty}>No destination matching "{quickJumpSearch}"</div>
              )}
            </div>
            <div className={styles.quickJumpFooter}>
              <span>Press <kbd>Enter</kbd> to select</span>
              <span><kbd>Esc</kbd> to close</span>
            </div>
          </div>
        </div>
      )}
    </header>
  );
}
