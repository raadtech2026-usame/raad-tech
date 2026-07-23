import type { HTMLAttributes, ReactNode } from "react";
import clsx from "clsx";
import styles from "./Card.module.css";

export interface CardProps extends HTMLAttributes<HTMLDivElement> {
  /** Adds the card's own internal padding. Off by default so callers embedding a table or a
   * full-bleed map/chart aren't fighting inherited padding. */
  padded?: boolean;
}

export function Card({ padded, className, children, ...rest }: CardProps) {
  return (
    <div className={clsx(styles.card, padded && styles.padded, className)} {...rest}>
      {children}
    </div>
  );
}

export interface CardHeaderProps {
  title: ReactNode;
  action?: ReactNode;
}

export function CardHeader({ title, action }: CardHeaderProps) {
  return (
    <div className={styles.header}>
      <span>{title}</span>
      {action}
    </div>
  );
}
