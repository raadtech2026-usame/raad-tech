import { Outlet } from "react-router-dom";
import { useAuthStore } from "../shared/stores/authStore";

/** The authenticated shell every feature module renders inside (`<Outlet />`). Deliberately
 * minimal this phase — a real nav/design-system component lands in `shared/components/` once
 * the first feature module needs one, not invented ahead of that need. */
export function DashboardLayout() {
  const principal = useAuthStore((s) => s.principal);
  const logout = useAuthStore((s) => s.logout);

  return (
    <div>
      <header>
        <span>RAAD</span>
        {principal && <span> — {principal.role}</span>}
        <button onClick={() => void logout()}>Sign out</button>
      </header>
      <main>
        <Outlet />
      </main>
    </div>
  );
}
