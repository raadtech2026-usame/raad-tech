import "@testing-library/jest-dom/vitest";

// Polyfill localStorage for environments where Node 22+ experimental global shadows jsdom's window.localStorage
if (typeof window !== "undefined") {
  const createStorageMock = () => {
    let store: Record<string, string> = {};
    return {
      getItem: (key: string): string | null => store[key] ?? null,
      setItem: (key: string, value: string): void => {
        store[key] = String(value);
      },
      removeItem: (key: string): void => {
        delete store[key];
      },
      clear: (): void => {
        store = {};
      },
      get length(): number {
        return Object.keys(store).length;
      },
      key: (i: number): string | null => Object.keys(store)[i] ?? null,
    };
  };

  const storageInstance = createStorageMock();

  Object.defineProperty(window, "localStorage", {
    value: storageInstance,
    configurable: true,
    enumerable: true,
    writable: true,
  });

  Object.defineProperty(globalThis, "localStorage", {
    value: storageInstance,
    configurable: true,
    enumerable: true,
    writable: true,
  });
}

