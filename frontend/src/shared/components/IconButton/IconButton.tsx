import { forwardRef, type ButtonHTMLAttributes } from "react";
import clsx from "clsx";
import styles from "./IconButton.module.css";

export interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  icon: React.ReactNode;
  size?: "sm" | "md";
  raised?: boolean;
  /** A small numeric badge (e.g. unread notification count) rendered at the top-right corner. */
  badgeCount?: number;
  "aria-label": string;
}

export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(function IconButton(
  { icon, size = "md", raised, badgeCount, className, ...rest },
  ref,
) {
  const button = (
    <button
      ref={ref}
      type="button"
      className={clsx(styles.iconButton, styles[size], raised && styles.raised, className)}
      {...rest}
    >
      {icon}
    </button>
  );

  if (badgeCount === undefined || badgeCount <= 0) {
    return button;
  }

  return (
    <span className={styles.badgeWrap}>
      {button}
      <span className={styles.badgeCount}>{badgeCount > 9 ? "9+" : badgeCount}</span>
    </span>
  );
});
