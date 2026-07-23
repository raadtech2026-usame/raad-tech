import type { CSSProperties } from "react";
import clsx from "clsx";
import styles from "./Skeleton.module.css";

export interface SkeletonProps {
  width?: string | number;
  height?: string | number;
  className?: string;
  style?: CSSProperties;
}

export function Skeleton({ width = "100%", height = 14, className, style }: SkeletonProps) {
  return (
    <span
      className={clsx(styles.skeleton, className)}
      style={{ display: "block", width, height, ...style }}
      aria-hidden="true"
    />
  );
}
