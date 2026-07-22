import { useState, type FormEvent } from "react";
import { Navigate, useLocation, type Location } from "react-router-dom";
import { useAuthStore } from "../shared/stores/authStore";

export function LoginPage() {
  const location = useLocation();
  const status = useAuthStore((s) => s.status);
  const error = useAuthStore((s) => s.error);
  const login = useAuthStore((s) => s.login);

  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");

  if (status === "authenticated") {
    const from = (location.state as { from?: Location } | null)?.from;
    return <Navigate to={from?.pathname ?? "/"} replace />;
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
    <main>
      <h1>RAAD — Sign in</h1>
      <form onSubmit={(e) => void handleSubmit(e)}>
        <label>
          Email or phone
          <input
            value={identifier}
            onChange={(e) => setIdentifier(e.target.value)}
            autoComplete="username"
            required
          />
        </label>
        <label>
          Password
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            required
          />
        </label>
        {error && <p role="alert">{error}</p>}
        <button type="submit" disabled={status === "authenticating"}>
          {status === "authenticating" ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </main>
  );
}
