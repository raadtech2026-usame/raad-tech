import { forwardRef, type SelectHTMLAttributes } from "react";
import clsx from "clsx";
import styles from "./Select.module.css";

export type SelectProps = SelectHTMLAttributes<HTMLSelectElement>;

export const Select = forwardRef<HTMLSelectElement, SelectProps>(function Select(
  { className, children, ...rest },
  ref,
) {
  return (
    <select ref={ref} className={clsx(styles.select, className)} {...rest}>
      {children}
    </select>
  );
});
