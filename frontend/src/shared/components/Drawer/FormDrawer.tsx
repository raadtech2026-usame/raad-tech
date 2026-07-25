import { useEffect, useRef, type ReactNode } from "react";
import { X } from "lucide-react";
import styles from "./DetailDrawer.module.css";

export interface FormDrawerProps {
  open: boolean;
  onClose: () => void;
  icon: ReactNode;
  iconTint: string;
  iconColor: string;
  title: ReactNode;
  subtitle?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
}

/** The same slide-over chrome `DetailDrawer` uses — scrim, Escape-to-close, focus management on
 * open/close (reuses `DetailDrawer.module.css`'s chrome classes: `.scrim`/`.panel`/`.header`/
 * `.body`/`.footer` are generic drawer layout, not detail-view-specific — only `.statsGrid`/
 * `.rowsCard` are, and this component doesn't use those) — but with a free-form `children` body
 * instead of `DetailDrawer`'s fixed stats/rows key-value layout, for create/edit forms (first
 * consumer: `features/organizations/CreateOrganizationForm.tsx`). The open/close focus-management
 * effect is intentionally duplicated from `DetailDrawer` rather than factored out: it's ~15 lines
 * shared by exactly two components, the same "duplicate a small amount rather than couple two
 * otherwise-independent components" call this codebase's own domain layer already makes for its
 * per-module event-buffering logic. */
export function FormDrawer({
  open,
  onClose,
  icon,
  iconTint,
  iconColor,
  title,
  subtitle,
  children,
  footer,
}: FormDrawerProps) {
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const previouslyFocused = useRef<HTMLElement | null>(null);
  // Holds the latest `onClose` without making it a dependency of the effect below. Callers
  // routinely pass an inline `onClose={() => ...}` (a new function identity every render) — if
  // that identity were a dependency, any parent re-render while the drawer is open (e.g. a form
  // inside it re-rendering on every keystroke) would re-run the effect and re-focus the close
  // button below, stealing focus from whatever field the user was actively typing in.
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
        aria-labelledby="form-drawer-title"
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
              <div id="form-drawer-title" className={styles.title}>
                {title}
              </div>
              {subtitle && <div className={styles.subtitle}>{subtitle}</div>}
            </div>
          </div>
        </div>
        <div className={styles.body}>{children}</div>
        {footer && <div className={styles.footer}>{footer}</div>}
      </div>
    </>
  );
}
