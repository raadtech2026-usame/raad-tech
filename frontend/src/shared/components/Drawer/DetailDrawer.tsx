import { useEffect, useRef, type ReactNode } from "react";
import { X } from "lucide-react";
import styles from "./DetailDrawer.module.css";

export interface DrawerStat {
  key: string;
  value: ReactNode;
  color?: string;
}

export interface DrawerRow {
  key: string;
  value: ReactNode;
}

export interface DetailDrawerProps {
  open: boolean;
  onClose: () => void;
  icon: ReactNode;
  iconTint: string;
  iconColor: string;
  title: ReactNode;
  subtitle?: ReactNode;
  status?: ReactNode;
  mapSlot?: ReactNode;
  stats?: DrawerStat[];
  rows?: DrawerRow[];
  footer?: ReactNode;
}

/** The slide-over detail panel pattern from the approved design, reused across every entity
 * (vehicle, driver, student…) instead of each feature building its own drawer. Adds real dialog
 * semantics the approved mockup didn't have (it was a static, non-interactive `<div>`): a11y
 * role, Escape-to-close, and focus management on open/close. */
export function DetailDrawer({
  open,
  onClose,
  icon,
  iconTint,
  iconColor,
  title,
  subtitle,
  status,
  mapSlot,
  stats,
  rows,
  footer,
}: DetailDrawerProps) {
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const previouslyFocused = useRef<HTMLElement | null>(null);
  // Holds the latest `onClose` without making it a dependency of the effect below. Callers
  // routinely pass an inline `onClose={() => ...}` (a new function identity every render) — if
  // that identity were a dependency, any parent re-render while the drawer is open would re-run
  // the effect and re-focus the close button below, stealing focus from an active field (the
  // same shared defect fixed in FormDrawer.tsx, this component's own sibling).
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    if (!open) {
      return;
    }
    previouslyFocused.current = document.activeElement as HTMLElement | null;
    closeButtonRef.current?.focus();

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        onCloseRef.current();
      }
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      previouslyFocused.current?.focus();
    };
    // Intentionally only `open`: this effect's job is "run once per open transition" (initial
    // focus + Escape listener), not "run whenever any prop changes" — see onCloseRef above.
  }, [open]);

  if (!open) {
    return null;
  }

  return (
    <>
      <div className={styles.scrim} onClick={onClose} />
      <div
        className={styles.panel}
        role="dialog"
        aria-modal="true"
        aria-labelledby="detail-drawer-title"
      >
        <div className={styles.header}>
          <button
            ref={closeButtonRef}
            type="button"
            className={styles.closeButton}
            onClick={onClose}
            aria-label="Close panel"
          >
            <X size={17} />
          </button>
          <div className={styles.identity}>
            <span className={styles.iconWrap} style={{ background: iconTint, color: iconColor }}>
              {icon}
            </span>
            <div>
              <div id="detail-drawer-title" className={styles.title}>
                {title}
              </div>
              {subtitle && <div className={styles.subtitle}>{subtitle}</div>}
            </div>
          </div>
          {status && <div className={styles.statusRow}>{status}</div>}
        </div>
        <div className={styles.body}>
          {mapSlot}
          {stats && stats.length > 0 && (
            <div className={styles.statsGrid}>
              {stats.map((stat) => (
                <div key={stat.key} className={styles.statCard}>
                  <div className={styles.statKey}>{stat.key}</div>
                  <div className={styles.statValue} style={{ color: stat.color }}>
                    {stat.value}
                  </div>
                </div>
              ))}
            </div>
          )}
          {rows && rows.length > 0 && (
            <div className={styles.rowsCard}>
              {rows.map((row) => (
                <div key={row.key} className={styles.kvRow}>
                  <span className={styles.kvKey}>{row.key}</span>
                  <span className={styles.kvValue}>{row.value}</span>
                </div>
              ))}
            </div>
          )}
        </div>
        {footer && <div className={styles.footer}>{footer}</div>}
      </div>
    </>
  );
}
