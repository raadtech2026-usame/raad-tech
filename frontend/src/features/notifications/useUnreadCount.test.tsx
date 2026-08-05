import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";

vi.mock("./api", () => ({ listNotifications: vi.fn() }));
vi.mock("../../shared/hooks/useWebSocket", () => ({
  useWebSocketChannel: () => ({ status: "closed", lastCloseCode: null, send: vi.fn() }),
}));

import { listNotifications } from "./api";
import { useUnreadCount } from "./useUnreadCount";

function wrapper({ children }: { children: ReactNode }) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}

describe("useUnreadCount", () => {
  beforeEach(() => {
    vi.mocked(listNotifications).mockReset();
  });

  it("counts unread notifications among the most recent page", async () => {
    vi.mocked(listNotifications).mockResolvedValue({
      data: [
        { id: "n1", status: "unread" },
        { id: "n2", status: "unread" },
        { id: "n3", status: "read" },
      ] as never,
      page: { limit: 50, nextCursor: null, hasMore: false },
    });

    const { result } = renderHook(() => useUnreadCount(), { wrapper });

    await waitFor(() => expect(result.current).toBe(2));
    expect(listNotifications).toHaveBeenCalledWith({ limit: 50, cursor: null, filters: {} });
  });

  it("returns 0 while loading or when there are no unread notifications", async () => {
    vi.mocked(listNotifications).mockResolvedValue({
      data: [],
      page: { limit: 50, nextCursor: null, hasMore: false },
    });

    const { result } = renderHook(() => useUnreadCount(), { wrapper });

    expect(result.current).toBe(0);
    await waitFor(() => expect(listNotifications).toHaveBeenCalled());
    expect(result.current).toBe(0);
  });
});
