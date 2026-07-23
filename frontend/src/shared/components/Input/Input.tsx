import { forwardRef, type InputHTMLAttributes, type ReactNode } from "react";
import clsx from "clsx";
import styles from "./Input.module.css";

export interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  invalid?: boolean;
  icon?: ReactNode;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(function Input(
  { invalid, icon, className, ...rest },
  ref,
) {
  const input = (
    <input
      ref={ref}
      className={clsx(styles.input, invalid && styles.invalid, className)}
      aria-invalid={invalid || undefined}
      {...rest}
    />
  );

  if (!icon) {
    return input;
  }

  return (
    <div className={styles.withIcon}>
      <span className={styles.iconSlot}>{icon}</span>
      {input}
    </div>
  );
});
