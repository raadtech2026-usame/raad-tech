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

/** Consumed only by `AppShell`'s own `TopBar`. */
export function useCurrentPageHeader(): { title: string; subtitle?: string } {
  return usePageHeaderStore((s) => ({ title: s.title, subtitle: s.subtitle }));
}
