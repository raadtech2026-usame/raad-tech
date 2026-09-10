import type { HTMLAttributes, ReactNode } from "react";
import clsx from "clsx";
import styles from "./Card.module.css";

export interface CardProps extends HTMLAttributes<HTMLDivElement> {
  /** Adds the card's own internal padding. Off by default so callers embedding a table or a
   * full-bleed map/chart aren't fighting inherited padding. */
  padded?: boolean;
  /** Lifts the card off the surface. Reserve for cards that genuinely float above the page
   * (an overlay panel), not for ordinary content — a page where everything is elevated reads
   * as a page where nothing is. */
  elevated?: boolean;
  /** Adds the hover treatment for a card that is itself a control (clickable tile, link card).
   * Purely presentational: it does not add a click handler or a role. */
  interactive?: boolean;
  /** Removes the border and drops the card onto the inset ground — the reference design's
   * nested-panel motif, for a summary block sitting inside an already-white card. */
  inset?: boolean;
}

export function Card({
  padded,
  elevated,
  interactive,
  inset,
  className,
  children,
  ...rest
}: CardProps) {
  return (
    <div
      className={clsx(
        styles.card,
        padded && styles.padded,
        elevated && styles.elevated,
        interactive && styles.interactive,
        inset && styles.inset,
        className,
      )}
      {...rest}
    >
      {children}
    </div>
  );
}

export interface CardHeaderProps {
  title: ReactNode;
  /** A line of supporting context under the title. The reference design pairs almost every
   * section title with one — it is what stops a card header from being a bare noun. */
  subtitle?: ReactNode;
  /** Leading visual (an icon chip). Optional: an icon on every single header is decoration,
   * not information. */
  icon?: ReactNode;
  action?: ReactNode;
  className?: string;
}

export function CardHeader({ title, subtitle, icon, action, className }: CardHeaderProps) {
  return (
    <div className={clsx(styles.header, className)}>
      {icon && <span className={styles.headerIcon}>{icon}</span>}
      <div className={styles.headerText}>
        <span className={styles.headerTitle}>{title}</span>
        {subtitle && <span className={styles.headerSubtitle}>{subtitle}</span>}
      </div>
      {action && <div className={styles.headerAction}>{action}</div>}
    </div>
  );
}

export interface CardBodyProps extends HTMLAttributes<HTMLDivElement> {
  children: ReactNode;
}

/** Standard padded region beneath a `CardHeader`. Exists so the several sections that had each
 * hand-written `padding: 0 var(--space-5) var(--space-5)` in their own module stop drifting
 * apart by a few pixels each time one of them is touched. */
export function CardBody({ className, children, ...rest }: CardBodyProps) {
  return (
    <div className={clsx(styles.body, className)} {...rest}>
      {children}
    </div>
  );
}

export interface CardFooterProps extends HTMLAttributes<HTMLDivElement> {
  children: ReactNode;
}

export function CardFooter({ className, children, ...rest }: CardFooterProps) {
  return (
    <div className={clsx(styles.footer, className)} {...rest}>
      {children}
    </div>
  );
}
