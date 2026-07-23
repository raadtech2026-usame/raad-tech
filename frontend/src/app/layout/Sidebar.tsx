import { NavLink } from "react-router-dom";
import clsx from "clsx";
import { Logo } from "../../shared/components/Logo/Logo";
import type { NavItem } from "./navConfig";
import styles from "./Sidebar.module.css";

export interface SidebarProps {
  nav: NavItem[];
}

export function Sidebar({ nav }: SidebarProps) {
  return (
    <aside className={styles.sidebar}>
      <div className={styles.brand}>
        <Logo size={34} withWordmark />
      </div>

      <nav className={styles.nav} aria-label="Primary">
        {nav.map((item, index) =>
          item.type === "header" ? (
            <div key={`header-${index}`} className={styles.sectionHeader}>
              {item.label}
            </div>
          ) : (
            <NavLink
              key={item.path}
              to={item.path}
              end={item.path === "/platform" || item.path === "/org"}
              className={({ isActive }) => clsx(styles.link, isActive && styles.linkActive)}
            >
              <item.icon size={17} strokeWidth={2} aria-hidden="true" />
              <span className={styles.linkLabel}>{item.label}</span>
            </NavLink>
          ),
        )}
      </nav>

      <div className={styles.footer}>RAAD Platform v1.0</div>
    </aside>
  );
}
