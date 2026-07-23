import { Smartphone } from "lucide-react";
import { useAuthStore } from "../shared/stores/authStore";
import { Button } from "../shared/components/Button/Button";
import styles from "./MobileOnlyPage.module.css";

/** Driver and Parent have no web dashboard at all (`.claude/rules/flutter.md` #1, Project Brief
 * §4.7/§4.8 — both are mobile-only roles). If one of these accounts signs into the web login,
 * the honest response is this message, not a broken or empty dashboard shell. */
export function MobileOnlyPage() {
  const logout = useAuthStore((s) => s.logout);

  return (
    <div className={styles.wrap}>
      <span className={styles.icon}>
        <Smartphone size={26} />
      </span>
      <h1 className={styles.title}>Use the RAAD mobile app</h1>
      <p className={styles.description}>
        This account is set up for the RAAD mobile app, not the web dashboard. Install RAAD on
        your phone and sign in there to track buses, view trips, and receive alerts.
      </p>
      <Button variant="secondary" onClick={() => void logout()}>
        Sign out
      </Button>
    </div>
  );
}
