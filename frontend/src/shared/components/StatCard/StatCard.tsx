import type { ReactNode } from "react";
import clsx from "clsx";
import { Skeleton } from "../Skeleton/Skeleton";
import styles from "./StatCard.module.css";

export type StatCardTone = "brand" | "success" | "warning" | "danger" | "neutral" | "purple";

export interface StatCardProps {
  /** Small leading glyph. Rendered inside a tinted chip, sized by this component — pass the
   * icon element only, not a wrapper. */
  icon?: ReactNode;
  label: ReactNode;
  /** The headline figure. Already formatted by the caller: this component never formats,
   * rounds, or abbreviates a number, so a value shown here is exactly the value it was given. */
  value: ReactNode;
  /** Short qualifier next to the value — a count breakdown, a status, a period. Rendered as a
   * pill, so keep it to a few words.
   *
   * Deliberately NOT a "trend" or "delta" API despite the reference design leading with one:
   * no endpoint in this product returns a prior-period comparison for any of these figures, and
   * a component that makes a delta easy to pass is a component that invites one to be invented. */
  meta?: ReactNode;
  metaTone?: StatCardTone;
  /** A line of context under the inset panel — the breakdown that does not fit in `meta`. */
  footnote?: ReactNode;
  tone?: StatCardTone;
  /** Trailing control in the header row (a link, a menu). */
  action?: ReactNode;
  isLoading?: boolean;
  className?: string;
}

/**
 * The product's single KPI primitive.
 *
 * Shape follows the supplied reference design: a quiet header (tinted icon chip + label) over an
 * inset panel that carries the figure. The inset is doing real work rather than decoration — it
 * gives the number its own ground, so a row of four cards scans as four values rather than as
 * four paragraphs, and it is what keeps the card readable when the label wraps to two lines.
 *
 * Every consumer passes a value it already fetched. There is no placeholder or sample mode: a
 * card with nothing to show renders its loading skeleton or an explicit em dash, never a
 * plausible-looking number.
 */
export function StatCard({
  icon,
  label,
  value,
  meta,
  metaTone = "neutral",
  footnote,
  tone = "brand",
  action,
  isLoading,
  className,
}: StatCardProps) {
  return (
    <div className={clsx(styles.card, className)}>
      <div className={styles.header}>
        {icon && <span className={clsx(styles.icon, styles[`tone_${tone}`])}>{icon}</span>}
        <span className={styles.label}>{label}</span>
        {action && <span className={styles.action}>{action}</span>}
      </div>

      <div className={styles.panel}>
        {isLoading ? (
          <Skeleton width={96} height={30} />
        ) : (
          <span className={styles.value}>{value}</span>
        )}
        {!isLoading && meta && (
          <span className={clsx(styles.meta, styles[`metaTone_${metaTone}`])}>{meta}</span>
        )}
      </div>

      {(footnote || isLoading) && (
        <div className={styles.footnote}>
          {isLoading ? <Skeleton width={140} height={12} /> : footnote}
        </div>
      )}
    </div>
  );
}
