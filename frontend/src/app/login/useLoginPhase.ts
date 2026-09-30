import { useCallback, useEffect, useRef, useState } from "react";
import type { LoginFailureKind } from "./loginErrors";

/**
 * The sign-in screen's visual state. It only ever *reflects* the auth result — the store has
 * already accepted or refused the credentials by the time any of these is set.
 *
 *   idle ─focus─▶ engaged ─submit─▶ submitting ─┬─ok──▶ success ─(hold)─▶ done
 *                   ▲                            ├─401/429/network─▶ error ─(settle)─┐
 *                   └────────────────────────────┴─ACCOUNT_LOCKED─▶ locked ─(edit)───┘
 *
 * `done` is where the page hands over to the dashboard redirect.
 */
export type LoginPhase = "idle" | "engaged" | "submitting" | "error" | "locked" | "success" | "done";

/** Long enough for the door/route beat to read, short enough that nobody waits on it: every
 * hard reload signs the user out (tokens are memory-only), so this runs on most visits. */
export const SUCCESS_HOLD_MS = 800;
/** Two hazard blinks (see `LoginScene.module.css`), then back to rest. */
export const ERROR_SETTLE_MS = 1400;

const REDUCED_MOTION_QUERY = "(prefers-reduced-motion: reduce)";

function readReducedMotion(): boolean {
  return typeof window !== "undefined" && typeof window.matchMedia === "function"
    ? window.matchMedia(REDUCED_MOTION_QUERY).matches
    : false;
}

/** The global CSS rule in `global.css` already flattens CSS animations for these users; this is
 * for the parts CSS cannot reach — SMIL motion and the success hold timer. */
export function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState(readReducedMotion);

  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
      return;
    }
    const query = window.matchMedia(REDUCED_MOTION_QUERY);
    const onChange = () => setReduced(query.matches);
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, []);

  return reduced;
}

export function useLoginPhase() {
  const [phase, setPhase] = useState<LoginPhase>("idle");
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const clearTimer = useCallback(() => {
    if (timer.current !== null) {
      clearTimeout(timer.current);
      timer.current = null;
    }
  }, []);

  useEffect(() => clearTimer, [clearTimer]);

  const engage = useCallback(() => {
    setPhase((current) => (current === "idle" ? "engaged" : current));
  }, []);

  /** Editing a field after a lockout clears it back to rest; any other state is left alone. */
  const edit = useCallback(() => {
    setPhase((current) => (current === "locked" ? "engaged" : current));
  }, []);

  const submit = useCallback(() => {
    clearTimer();
    setPhase("submitting");
  }, [clearTimer]);

  const fail = useCallback(
    (kind: LoginFailureKind) => {
      clearTimer();
      if (kind === "locked") {
        setPhase("locked");
        return;
      }
      setPhase("error");
      timer.current = setTimeout(() => {
        timer.current = null;
        setPhase((current) => (current === "error" ? "engaged" : current));
      }, ERROR_SETTLE_MS);
    },
    [clearTimer],
  );

  const succeed = useCallback(
    (holdMs: number) => {
      clearTimer();
      if (holdMs <= 0) {
        setPhase("done");
        return;
      }
      setPhase("success");
      timer.current = setTimeout(() => {
        timer.current = null;
        setPhase("done");
      }, holdMs);
    },
    [clearTimer],
  );

  return { phase, engage, edit, submit, fail, succeed };
}
