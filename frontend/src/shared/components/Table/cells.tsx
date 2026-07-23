import type { ReactNode } from "react";
import styles from "./DataTable.module.css";

export interface LeadCellProps {
  icon: ReactNode;
  title: ReactNode;
  subtitle?: ReactNode;
  iconTint?: string;
  iconColor?: string;
}

/** The "icon + title + subtitle" pattern used for the primary column of nearly every table in
 * the approved design (vehicle, driver, student, organization…). */
export function LeadCell({ icon, title, subtitle, iconTint, iconColor }: LeadCellProps) {
  return (
    <div className={styles.leadCell}>
      <span
        className={styles.leadIcon}
        style={
          iconTint || iconColor
            ? { background: iconTint, color: iconColor }
            : undefined
        }
      >
        {icon}
      </span>
      <div className={styles.leadText}>
        <div className={styles.leadTitle}>{title}</div>
        {subtitle && <div className={styles.leadSubtitle}>{subtitle}</div>}
      </div>
    </div>
  );
}

export function MonoText({ children }: { children: ReactNode }) {
  return <span className={styles.mono}>{children}</span>;
}
