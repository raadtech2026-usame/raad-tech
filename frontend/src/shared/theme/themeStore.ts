import { create } from "zustand";

export type ThemeMode = "light" | "dark" | "system";
export type ResolvedTheme = "light" | "dark";

interface ThemeState {
  mode: ThemeMode;
  resolvedTheme: ResolvedTheme;
  setMode: (mode: ThemeMode) => void;
  toggleTheme: () => void;
}

const STORAGE_KEY = "raad-theme";

function getSystemTheme(): ResolvedTheme {
  if (typeof window === "undefined" || !window.matchMedia) {
    return "light";
  }
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function resolveTheme(mode: ThemeMode): ResolvedTheme {
  return mode === "system" ? getSystemTheme() : mode;
}

function applyThemeToDocument(theme: ResolvedTheme): void {
  if (typeof document !== "undefined") {
    document.documentElement.setAttribute("data-theme", theme);
    document.documentElement.style.colorScheme = theme;
  }
}

const initialMode: ThemeMode = (() => {
  if (typeof window === "undefined") return "light";
  try {
    const saved = localStorage.getItem(STORAGE_KEY) as ThemeMode | null;
    if (saved === "light" || saved === "dark" || saved === "system") {
      return saved;
    }
  } catch {
    // LocalStorage inaccessible
  }
  return "light";
})();

const initialResolved = resolveTheme(initialMode);
applyThemeToDocument(initialResolved);

export const useThemeStore = create<ThemeState>((set, get) => ({
  mode: initialMode,
  resolvedTheme: initialResolved,

  setMode: (mode: ThemeMode) => {
    try {
      localStorage.setItem(STORAGE_KEY, mode);
    } catch {
      // LocalStorage inaccessible
    }
    const resolved = resolveTheme(mode);
    applyThemeToDocument(resolved);
    set({ mode, resolvedTheme: resolved });
  },

  toggleTheme: () => {
    const current = get().resolvedTheme;
    const next: ThemeMode = current === "dark" ? "light" : "dark";
    get().setMode(next);
  },
}));

// Setup media listener if system mode is used
if (typeof window !== "undefined" && window.matchMedia) {
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
    if (useThemeStore.getState().mode === "system") {
      const resolved = getSystemTheme();
      applyThemeToDocument(resolved);
      useThemeStore.setState({ resolvedTheme: resolved });
    }
  });
}
