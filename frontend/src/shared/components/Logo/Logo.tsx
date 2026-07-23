import clsx from "clsx";
import logoUrl from "../../../assets/logo-raad.png";
import styles from "./Logo.module.css";

export interface LogoProps {
  size?: number;
  /** Renders the "RAAD" wordmark + "TRANSPORT OS" tagline next to the mark — the sidebar/login
   * treatment. Omit for icon-only contexts (favicon-adjacent chrome, compact headers). */
  withWordmark?: boolean;
  wordmarkColor?: string;
  taglineColor?: string;
  className?: string;
}

export function Logo({
  size = 34,
  withWordmark,
  wordmarkColor = "#fff",
  taglineColor = "var(--color-brand-primary)",
  className,
}: LogoProps) {
  const mark = (
    <img
      src={logoUrl}
      alt="RAAD"
      width={size}
      height={size}
      className={clsx(styles.mark, className)}
    />
  );

  if (!withWordmark) {
    return mark;
  }

  return (
    <span className={styles.withWordmark}>
      {mark}
      <span className={styles.wordmark}>
        <span className={styles.name} style={{ color: wordmarkColor }}>
          RAAD
        </span>
        <span className={styles.tagline} style={{ color: taglineColor }}>
          TRANSPORT OS
        </span>
      </span>
    </span>
  );
}
