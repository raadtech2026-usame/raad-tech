import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { usePaginatedQuery } from "./usePaginatedQuery";
import type { OffsetPage } from "../api/types";

interface Widget {
  id: string;
  name: string;
}

function page(data: Widget[], total: number, pageNo = 1, pageSize = 25): OffsetPage<Widget> {
  return { data, page: { total, page: pageNo, pageSize } };
}

function wrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  };
}

describe("usePaginatedQuery", () => {
  it("fetches the first page and exposes rows/total/loading state", async () => {
    const fetcher = vi.fn().mockResolvedValue(page([{ id: "1", name: "Alpha" }], 1));

    const { result } = renderHook(
      () => usePaginatedQuery({ queryKey: ["widgets", "list"], fetcher }),
      { wrapper: wrapper() },
    );

    expect(result.current.isLoading).toBe(true);
    expect(result.current.rows).toEqual([]);

    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.rows).toEqual([{ id: "1", name: "Alpha" }]);
    expect(result.current.total).toBe(1);
    expect(result.current.page).toBe(1);
    expect(fetcher).toHaveBeenCalledWith({
      page: 1,
      pageSize: 25,
      sort: null,
      filters: {},
      search: "",
    });
  });

  it("setPage triggers a re-fetch with the new page number", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(page([{ id: "1", name: "Alpha" }], 60, 1))
      .mockResolvedValueOnce(page([{ id: "2", name: "Beta" }], 60, 2));

    const { result } = renderHook(
      () => usePaginatedQuery({ queryKey: ["widgets", "list"], fetcher }),
      { wrapper: wrapper() },
    );

    await waitFor(() => expect(result.current.isLoading).toBe(false));

    act(() => result.current.setPage(2));

    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2));
    expect(fetcher).toHaveBeenLastCalledWith(
      expect.objectContaining({ page: 2 }),
    );
  });

  it("toggleSort cycles asc -> desc -> cleared and resets to page 1", async () => {
    const fetcher = vi.fn().mockResolvedValue(page([], 0));

    const { result } = renderHook(
      () => usePaginatedQuery({ queryKey: ["widgets", "list"], fetcher }),
      { wrapper: wrapper() },
    );
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    act(() => result.current.toggleSort("name"));
    expect(result.current.sort).toEqual({ field: "name", direction: "asc" });

    act(() => result.current.toggleSort("name"));
    expect(result.current.sort).toEqual({ field: "name", direction: "desc" });

    act(() => result.current.toggleSort("name"));
    expect(result.current.sort).toBeNull();
  });

  it("setFilter adds and removes a filter, resetting to page 1", async () => {
    const fetcher = vi.fn().mockResolvedValue(page([], 0));

    const { result } = renderHook(
      () => usePaginatedQuery({ queryKey: ["widgets", "list"], fetcher }),
      { wrapper: wrapper() },
    );
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    act(() => result.current.setFilter("status", "active"));
    expect(result.current.filters).toEqual({ status: "active" });

    act(() => result.current.setFilter("status", null));
    expect(result.current.filters).toEqual({});
  });

  it("surfaces a fetch error via isError/error", async () => {
    const fetcher = vi.fn().mockRejectedValue(new Error("network down"));

    const { result } = renderHook(
      () => usePaginatedQuery({ queryKey: ["widgets", "list"], fetcher }),
      { wrapper: wrapper() },
    );

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.rows).toEqual([]);
  });
});
