import type { HTMLAttributes } from "react";
import clsx from "clsx";
import styles from "./Badge.module.css";

export type BadgeVariant = "success" | "warning" | "danger" | "info" | "neutral" | "purple";

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  variant?: BadgeVariant;
  /** Renders a small leading dot in the badge's own color — the "18 live" / status-pill pattern. */
  dot?: boolean;
  /** Animates the dot with a slow blink — reserved for genuinely live/real-time state, never a
   * static count (matches the approved design's own convention: only truly live counters blink). */
  pulsing?: boolean;
  outlined?: boolean;
}

export function Badge({
  variant = "neutral",
  dot,
  pulsing,
  outlined,
  className,
  children,
  ...rest
}: BadgeProps) {
  return (
    <span
      className={clsx(styles.badge, styles[variant], outlined && styles.outlined, className)}
      {...rest}
    >
      {dot && <span className={clsx(styles.dot, pulsing && styles.pulsing)} aria-hidden="true" />}
      {children}
    </span>
  );
}
