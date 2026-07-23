import { forwardRef, type InputHTMLAttributes, type ReactNode } from "react";
import clsx from "clsx";
import styles from "./Toggle.module.css";

export interface ToggleProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "type"> {
  label?: ReactNode;
  description?: ReactNode;
}

export const Toggle = forwardRef<HTMLInputElement, ToggleProps>(function Toggle(
  { label, description, className, ...rest },
  ref,
) {
  return (
    <label className={clsx(styles.wrap, className)}>
      <input ref={ref} type="checkbox" role="switch" className={styles.input} {...rest} />
      <span className={styles.track}>
        <span className={styles.thumb} />
      </span>
      {(label || description) && (
        <span className={styles.text}>
          {label && <span className={styles.label}>{label}</span>}
          {description && <span className={styles.description}>{description}</span>}
        </span>
      )}
    </label>
  );
});
