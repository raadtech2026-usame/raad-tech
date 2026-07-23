import { useState, type FormEvent } from "react";
import { Navigate, useLocation, type Location } from "react-router-dom";
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
      <div className={styles.card}>
        <div className={styles.brand}>
          <Logo size={48} />
          <div>
            <div className={styles.heading}>RAAD</div>
            <div className={styles.tagline}>Sign in to the Transport OS console</div>
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
            />
          </FormField>
          <FormField label="Password">
            <Input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              required
            />
          </FormField>

          {error && (
            <p className={styles.alert} role="alert">
              {error}
            </p>
          )}

          <Button type="submit" fullWidth loading={status === "authenticating"}>
            {status === "authenticating" ? "Signing in…" : "Sign in"}
          </Button>
        </form>

        <p className={styles.footer}>RAAD Platform · Enterprise transport management</p>
      </div>
    </main>
  );
}
