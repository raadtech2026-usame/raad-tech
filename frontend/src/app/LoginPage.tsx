import { useState, type FormEvent } from "react";
import { Navigate, useLocation, type Location } from "react-router-dom";
import {
  Activity,
  CheckCircle2,
  Eye,
  EyeOff,
  Lock,
  Mail,
  Radio,
  ShieldCheck,
  Truck,
} from "lucide-react";
import { useAuthStore } from "../shared/stores/authStore";
import { getDashboardHomePath } from "../shared/auth/dashboard";
import { Logo } from "../shared/components/Logo/Logo";
import { Input } from "../shared/components/Input/Input";
import { FormField } from "../shared/components/FormField/FormField";
import { Button } from "../shared/components/Button/Button";
import styles from "./LoginPage.module.css";

export function LoginPage() {
  const location = useLocation();
  const status = useAuthStore((s) => s.status);
  const error = useAuthStore((s) => s.error);
  const login = useAuthStore((s) => s.login);
  const principal = useAuthStore((s) => s.principal);

  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);

  if (status === "authenticated" && principal) {
    const from = (location.state as { from?: Location } | null)?.from;
    return <Navigate to={from?.pathname ?? getDashboardHomePath(principal.role)} replace />;
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    try {
      await login(identifier, password);
    } catch {
      // Already surfaced via the store's own `error` field - nothing further to do here.
    }
  }

  return (
    <main className={styles.page}>
      <div className={styles.container}>
        {/* Left Side: Enterprise Telematics Brand Showcase */}
        <div className={styles.showcase}>
          <div className={styles.showcaseTop}>
            <div className={styles.brandBadge}>
              <Radio size={14} className={styles.livePulseIcon} />
              <span>Real-Time Fleet OS</span>
            </div>
            <h1 className={styles.showcaseTitle}>
              Mission-critical visibility for student transportation.
            </h1>
            <p className={styles.showcaseDescription}>
              High-throughput JT/T 808 telematics, sub-second GPS tracking, onboard video streaming,
              and complete school transportation management.
            </p>
          </div>

          {/* Telemetry Feature Highlights */}
          <div className={styles.telemetryCard}>
            <div className={styles.telemetryCardHeader}>
              <div className={styles.telemetryVehicle}>
                <div className={styles.vehicleAvatar}>
                  <Truck size={16} />
                </div>
                <div>
                  <div className={styles.vehicleName}>Fleet Bus #104</div>
                  <div className={styles.vehicleRoute}>North Hills Academy · Morning Route</div>
                </div>
              </div>
              <div className={styles.liveStatusPill}>
                <span className={styles.liveStatusDot} />
                <span>Active Trip</span>
              </div>
            </div>

            <div className={styles.telemetryMetrics}>
              <div className={styles.metricItem}>
                <span className={styles.metricLabel}>Speed</span>
                <span className={styles.metricValue}>42 km/h</span>
              </div>
              <div className={styles.metricItem}>
                <span className={styles.metricLabel}>GPS 3D Fix</span>
                <span className={styles.metricValueSuccess}>12 Sats · 1.0 HDOP</span>
              </div>
              <div className={styles.metricItem}>
                <span className={styles.metricLabel}>On-Board</span>
                <span className={styles.metricValue}>28 / 32 Riders</span>
              </div>
            </div>
          </div>

          <div className={styles.featureList}>
            <div className={styles.featureItem}>
              <CheckCircle2 size={16} className={styles.featureCheck} />
              <span>Cellular 4G MDVR gateway with persistent terminal authentication</span>
            </div>
            <div className={styles.featureItem}>
              <CheckCircle2 size={16} className={styles.featureCheck} />
              <span>Multi-tenant isolation & role-based school administration</span>
            </div>
            <div className={styles.featureItem}>
              <CheckCircle2 size={16} className={styles.featureCheck} />
              <span>Automated parent arrival alerts & route geofence monitors</span>
            </div>
          </div>

          <div className={styles.showcaseFooter}>
            <ShieldCheck size={16} />
            <span>Encrypted Telematics Pipeline · SOC-2 Type II Ingest Standards</span>
          </div>
        </div>

        {/* Right Side: Sign-In Form Card */}
        <div className={styles.card}>
          <div className={styles.brand}>
            <Logo size={44} />
            <div>
              <div className={styles.heading}>RAAD Console</div>
              <div className={styles.tagline}>Sign in to your organization or platform account</div>
            </div>
          </div>

          <form className={styles.form} onSubmit={(e) => void handleSubmit(e)}>
            <FormField label="Email or phone">
              <Input
                value={identifier}
                onChange={(e) => setIdentifier(e.target.value)}
                autoComplete="username"
                autoFocus
                required
                icon={<Mail size={15} />}
                placeholder="admin@school.org or +252..."
              />
            </FormField>

            <FormField label="Password">
              <div className={styles.passwordWrapper}>
                <Input
                  type={showPassword ? "text" : "password"}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  autoComplete="current-password"
                  required
                  icon={<Lock size={15} />}
                  placeholder="Enter your password"
                  className={styles.passwordInput}
                />
                <button
                  type="button"
                  className={styles.passwordToggle}
                  onClick={() => setShowPassword((p) => !p)}
                  aria-label={showPassword ? "Hide password" : "Show password"}
                >
                  {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>
            </FormField>

            {error && (
              <p className={styles.alert} role="alert">
                {error}
              </p>
            )}

            <Button
              type="submit"
              fullWidth
              loading={status === "authenticating"}
              className={styles.submitButton}
            >
              {status === "authenticating" ? "Signing in…" : "Sign In to RAAD"}
            </Button>
          </form>

          <div className={styles.securityNotice}>
            <Activity size={14} className={styles.securityIcon} />
            <span>Authorized school staff and operations personnel only</span>
          </div>

          <p className={styles.footer}>
            RAAD Platform · Enterprise Transport OS & School Management
          </p>
        </div>
      </div>
    </main>
  );
}
