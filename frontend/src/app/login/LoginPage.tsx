import { useId, useMemo, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { Navigate, useLocation, type Location } from "react-router-dom";
import { CheckCircle2, Eye, EyeOff, Lock, Mail } from "lucide-react";
import { useAuthStore } from "../../shared/stores/authStore";
import { getDashboardHomePath } from "../../shared/auth/dashboard";
import { Logo } from "../../shared/components/Logo/Logo";
import { Input } from "../../shared/components/Input/Input";
import { FormField } from "../../shared/components/FormField/FormField";
import { Button } from "../../shared/components/Button/Button";
import { LoginScene } from "./LoginScene";
import { describeLoginFailure, type LoginFailure } from "./loginErrors";
import { SUCCESS_HOLD_MS, useLoginPhase, usePrefersReducedMotion } from "./useLoginPhase";
import styles from "./LoginPage.module.css";

/** Focusing the first field on load opens the on-screen keyboard on a phone before the user has
 * even seen the page, so only do it where there is a real pointer and keyboard. */
function shouldAutoFocus(): boolean {
  return typeof window !== "undefined" && typeof window.matchMedia === "function"
    ? window.matchMedia("(pointer: fine)").matches
    : true;
}

export function LoginPage() {
  const location = useLocation();
  const status = useAuthStore((s) => s.status);
  const login = useAuthStore((s) => s.login);
  const principal = useAuthStore((s) => s.principal);

  const reducedMotion = usePrefersReducedMotion();
  const { phase, engage, edit, submit, fail, succeed } = useLoginPhase();
  const autoFocus = useMemo(shouldAutoFocus, []);
  const errorId = useId();

  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [capsLockOn, setCapsLockOn] = useState(false);
  const [failure, setFailure] = useState<LoginFailure | null>(null);
  const passwordRef = useRef<HTMLInputElement>(null);

  // While the request is in flight, or the success beat is playing, the store already says
  // "authenticated" — hold the redirect until the phase reaches `done`. Anyone who arrives
  // already signed in skips all of this and goes straight through.
  const holdingRedirect = phase === "submitting" || phase === "success";
  if (status === "authenticated" && principal && !holdingRedirect) {
    const from = (location.state as { from?: Location } | null)?.from;
    return <Navigate to={from?.pathname ?? getDashboardHomePath(principal.role)} replace />;
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setFailure(null);
    submit();
    try {
      await login(identifier, password);
    } catch (error) {
      const described = describeLoginFailure(error);
      setFailure(described);
      fail(described.kind);
      // The submit button was disabled mid-request, which drops focus; put the user back where
      // a retry starts.
      if (described.kind === "invalid_credentials") {
        passwordRef.current?.focus();
        passwordRef.current?.select();
      }
      return;
    }
    succeed(reducedMotion ? 0 : SUCCESS_HOLD_MS);
  }

  function handleEdit(): void {
    // A message about the previous attempt is stale the moment either field changes.
    setFailure(null);
    edit();
  }

  function trackCapsLock(event: KeyboardEvent<HTMLInputElement>): void {
    setCapsLockOn(event.getModifierState("CapsLock"));
  }

  const busy = phase === "submitting" || phase === "success" || phase === "done";
  const signedIn = phase === "success" || phase === "done";
  const credentialsRejected =
    failure?.kind === "invalid_credentials" || failure?.kind === "locked";
  const describedBy = failure ? errorId : undefined;

  return (
    <main className={styles.page} data-phase={phase}>
      <LoginScene phase={phase} reducedMotion={reducedMotion} />

      <div className={styles.stage}>
        {/* Always the dark token set, whatever the dashboard theme: the backdrop is always ink,
            and a white card on it would be the one surface that changes between visits. */}
        <section className={styles.card} data-theme="dark" aria-labelledby="login-heading">
          <span className={styles.statusStrip} aria-hidden="true" />

          <div className={styles.brand}>
            <Logo size={44} withWordmark />
          </div>
          <h1 id="login-heading" className="raad-visually-hidden">
            Sign in to RAAD
          </h1>

          <form
            className={styles.form}
            onSubmit={(e) => void handleSubmit(e)}
            onFocus={engage}
          >
            <FormField label="Email or phone">
              <Input
                value={identifier}
                onChange={(e) => {
                  setIdentifier(e.target.value);
                  handleEdit();
                }}
                autoComplete="username"
                inputMode="email"
                autoCapitalize="none"
                spellCheck={false}
                autoFocus={autoFocus}
                required
                readOnly={busy}
                invalid={credentialsRejected}
                aria-describedby={describedBy}
                icon={<Mail size={15} />}
                placeholder="admin@school.org or +252…"
              />
            </FormField>

            <FormField
              label="Password"
              hint={capsLockOn ? "Caps Lock is on" : undefined}
            >
              <div className={styles.passwordWrapper}>
                <Input
                  ref={passwordRef}
                  type={showPassword ? "text" : "password"}
                  value={password}
                  onChange={(e) => {
                    setPassword(e.target.value);
                    handleEdit();
                  }}
                  onKeyDown={trackCapsLock}
                  onKeyUp={trackCapsLock}
                  onBlur={() => setCapsLockOn(false)}
                  autoComplete="current-password"
                  required
                  readOnly={busy}
                  invalid={credentialsRejected}
                  aria-describedby={describedBy}
                  icon={<Lock size={15} />}
                  placeholder="Enter your password"
                  className={styles.passwordInput}
                />
                <button
                  type="button"
                  className={styles.passwordToggle}
                  onClick={() => setShowPassword((p) => !p)}
                  aria-label={showPassword ? "Hide password" : "Show password"}
                  disabled={signedIn}
                >
                  {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>
            </FormField>

            {failure && (
              <p id={errorId} className={styles.alert} role="alert">
                {failure.message}
              </p>
            )}

            <Button
              type="submit"
              fullWidth
              loading={phase === "submitting"}
              disabled={signedIn}
              leadingIcon={signedIn ? <CheckCircle2 size={16} /> : undefined}
              className={styles.submitButton}
              data-state={signedIn ? "success" : undefined}
            >
              {phase === "submitting" ? "Signing in…" : signedIn ? "Signed in" : "Sign in"}
            </Button>
          </form>

          <p className="raad-visually-hidden" role="status" aria-live="polite">
            {signedIn ? "Signed in. Opening your dashboard." : ""}
          </p>
        </section>
      </div>
    </main>
  );
}
