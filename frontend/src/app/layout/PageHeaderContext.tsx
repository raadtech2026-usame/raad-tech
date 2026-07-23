import { useEffect } from "react";
import { create } from "zustand";

interface PageHeaderState {
  title: string;
  subtitle?: string;
  setHeader: (title: string, subtitle?: string) => void;
}

const usePageHeaderStore = create<PageHeaderState>((set) => ({
  title: "RAAD",
  subtitle: undefined,
  setHeader: (title, subtitle) => set({ title, subtitle }),
}));

/** Every feature page calls `usePageHeader("Vehicles", "Registry, maintenance & assignment")` —
 * this is how the module title/subtitle in the topbar (the approved design's `{{mod.title}}` /
 * `{{mod.subtitle}}`) gets set without `AppShell` needing to know about every route in advance. */
export function usePageHeader(title: string, subtitle?: string): void {
  const setHeader = usePageHeaderStore((s) => s.setHeader);
  useEffect(() => {
    setHeader(title, subtitle);
  }, [setHeader, title, subtitle]);
}

/** Consumed only by `AppShell`'s own `TopBar`.
 *
 * Deliberately two separate primitive selectors, not one selector returning `{ title,
 * subtitle }`: Zustand's `useStore` (built on `useSyncExternalStore`) compares each selector's
 * return value via `Object.is` to decide whether to re-render. A selector that allocates a new
 * object literal every call (`(s) => ({ title: s.title, subtitle: s.subtitle })`) never equals
 * its previous return value, so React treats the store as "changed" on every single render
 * check — producing an infinite `AppShell` render loop ("Maximum update depth exceeded" /
 * "The result of getSnapshot should be cached to avoid an infinite loop"). Selecting each
 * primitive field independently keeps every individual snapshot stable via `Object.is` when
 * that field hasn't changed, matching this codebase's own established selector convention
 * (`useAuthStore((s) => s.principal)` etc. never constructs an object inside the selector). */
export function useCurrentPageHeader(): { title: string; subtitle?: string } {
  const title = usePageHeaderStore((s) => s.title);
  const subtitle = usePageHeaderStore((s) => s.subtitle);
  return { title, subtitle };
}
