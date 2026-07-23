import type { ReactNode } from "react";
import styles from "./LiveIndicator.module.css";

export interface LiveIndicatorProps {
  children: ReactNode;
}

/** The blinking-dot "N live" chip from the approved topbar design. Reserved for genuinely
 * real-time counters (WebSocket-fed) — never a static/cached number, matching the design's own
 * convention that motion signals "this is updating right now." */
export function LiveIndicator({ children }: LiveIndicatorProps) {
  return (
    <span className={styles.wrap}>
      <span className={styles.dot} aria-hidden="true" />
      {children}
    </span>
  );
}
