import { describe, expect, it, beforeEach, vi } from "vitest";
import { useThemeStore } from "./themeStore";

describe("useThemeStore", () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.removeAttribute("data-theme");
    useThemeStore.getState().setMode("light");
  });

  it("initializes with light mode by default", () => {
    expect(useThemeStore.getState().mode).toBe("light");
    expect(useThemeStore.getState().resolvedTheme).toBe("light");
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
  });

  it("updates to dark mode and sets document attribute and localStorage", () => {
    useThemeStore.getState().setMode("dark");

    expect(useThemeStore.getState().mode).toBe("dark");
    expect(useThemeStore.getState().resolvedTheme).toBe("dark");
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    expect(localStorage.getItem("raad-theme")).toBe("dark");
  });

  it("toggles between dark and light themes seamlessly", () => {
    useThemeStore.getState().setMode("light");
    expect(useThemeStore.getState().resolvedTheme).toBe("light");

    useThemeStore.getState().toggleTheme();
    expect(useThemeStore.getState().resolvedTheme).toBe("dark");
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");

    useThemeStore.getState().toggleTheme();
    expect(useThemeStore.getState().resolvedTheme).toBe("light");
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
  });

  it("handles system mode based on matchMedia", () => {
    window.matchMedia = vi.fn().mockImplementation((query: string) => ({
      matches: true,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }));

    useThemeStore.getState().setMode("system");
    expect(useThemeStore.getState().mode).toBe("system");
    expect(useThemeStore.getState().resolvedTheme).toBe("dark");
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
  });
});
