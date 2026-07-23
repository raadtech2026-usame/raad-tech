import type { HTMLAttributes } from "react";
import clsx from "clsx";
import styles from "./Avatar.module.css";

export interface AvatarProps extends HTMLAttributes<HTMLSpanElement> {
  initials: string;
  color: string;
  size?: "sm" | "md" | "lg";
  /** `true` renders a rounded-square badge (matches the sidebar role chip); `false` (default)
   * renders a circle (matches the topbar account avatar) — both patterns appear in the approved
   * design for the same role data, distinguished only by context. */
  square?: boolean;
}

export function Avatar({
  initials,
  color,
  size = "md",
  square,
  className,
  style,
  ...rest
}: AvatarProps) {
  return (
    <span
      className={clsx(styles.avatar, styles[size], square && styles.square, className)}
      style={{ background: color, ...style }}
      {...rest}
    >
      {initials}
    </span>
  );
}
