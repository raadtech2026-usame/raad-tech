import { Logo } from "../Logo/Logo";
import styles from "./LoadingScreen.module.css";

export interface LoadingScreenProps {
  label?: string;
}

/** Full-viewport branded loading state — used for the initial route-level Suspense boundary and
 * anywhere else a whole page is waiting on its first data. */
export function LoadingScreen({ label = "Loading RAAD…" }: LoadingScreenProps) {
  return (
    <div className={styles.wrap} role="status" aria-live="polite">
      <Logo size={56} className={styles.mark} />
      <span className={styles.label}>{label}</span>
    </div>
  );
}
