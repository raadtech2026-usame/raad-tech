import { useMemo, useState } from "react";
import { keepPreviousData, useQuery, type UseQueryResult } from "@tanstack/react-query";
import type { OffsetPage } from "../api/types";
import type { OffsetListParams, SortState } from "../api/listParams";

export type { SortState } from "../api/listParams";

export interface UsePaginatedQueryOptions<T> {
  /** TanStack Query key identifying this resource + list, e.g. `["organizations", "list"]`
   * (roadmap §3.2's convention: `[resource, 'list', paramsHash]`) — the current
   * page/sort/filter/search state is appended automatically, so a change to any of them is a
   * cache-key change TanStack Query already handles correctly. Do not include page/sort/filter
   * state in this array yourself. */
  queryKey: readonly unknown[];
  /** Fetches one page from the backend's exact `OffsetPage<T>` envelope — the caller owns the
   * wire-to-app-type mapping (e.g. `features/organizations/api.ts`'s `listOrganizations`), this
   * hook only owns pagination/sort/filter/search *state* and the TanStack Query wiring around
   * it. */
  fetcher: (params: OffsetListParams) => Promise<OffsetPage<T>>;
  pageSize?: number;
  initialSort?: SortState | null;
  initialFilters?: Record<string, string>;
  /** Matches `useQuery`'s own `enabled` — e.g. gate the request on a required parent id
   * existing yet. Defaults to `true`. */
  enabled?: boolean;
}

export interface UsePaginatedQueryResult<T> {
  rows: T[];
  total: number;
  page: number;
  pageSize: number;
  pageCount: number;
  sort: SortState | null;
  filters: Record<string, string>;
  search: string;
  /** True only while the *first* page load for the current params has no data to show yet —
   * the signal `DataTable`'s `isLoading` (-> skeleton rows) should use. Changing page/sort/
   * filter afterwards keeps showing the previous page's rows (`placeholderData: keepPreviousData`
   * below) while `isFetching` is true instead, so the table never flashes back to a skeleton on
   * every click. */
  isLoading: boolean;
  /** True during any fetch, including a background refetch after a param change. */
  isFetching: boolean;
  isError: boolean;
  error: unknown;
  setPage: (page: number) => void;
  /** Mirrors `DataTable`'s `onSortChange(field)` contract: first click on a column sorts it
   * ascending, second click flips to descending, third click clears sorting entirely — never a
   * client-side re-sort, only a new server request (sorting is always server-side per
   * `DataTableColumnMeta`'s own docstring). */
  toggleSort: (field: string) => void;
  /** `value === null` (or `""`) removes the filter. Every filter/sort/search change resets to
   * page 1 — staying on a since-invalidated page number would be confusing, not helpful. */
  setFilter: (field: string, value: string | null) => void;
  setSearch: (value: string) => void;
  refetch: UseQueryResult<OffsetPage<T>>["refetch"];
}

/** Generic wrapper around the backend's `OffsetPage<T>` envelope (API Contracts §7 "offered for
 * admin tables where total counts matter") — built once so every list-view feature (F1
 * Organizations today; F2 Users, F3 Fleet, F4-F6 Transport Ops, F12 Audit tomorrow) writes a
 * column definition and a fetcher, not pagination/sort/filter state-management logic of its
 * own. */
export function usePaginatedQuery<T>({
  queryKey,
  fetcher,
  pageSize = 25,
  initialSort = null,
  initialFilters = {},
  enabled = true,
}: UsePaginatedQueryOptions<T>): UsePaginatedQueryResult<T> {
  const [page, setPageState] = useState(1);
  const [sort, setSort] = useState<SortState | null>(initialSort);
  const [filters, setFilters] = useState<Record<string, string>>(initialFilters);
  const [search, setSearchState] = useState("");

  const params: OffsetListParams = useMemo(
    () => ({ page, pageSize, sort, filters, search }),
    [page, pageSize, sort, filters, search],
  );

  const query = useQuery({
    queryKey: [...queryKey, params],
    queryFn: () => fetcher(params),
    placeholderData: keepPreviousData,
    enabled,
  });

  function setPage(next: number): void {
    setPageState(Math.max(1, next));
  }

  function toggleSort(field: string): void {
    setPageState(1);
    setSort((current) => {
      if (!current || current.field !== field) {
        return { field, direction: "asc" };
      }
      if (current.direction === "asc") {
        return { field, direction: "desc" };
      }
      return null;
    });
  }

  function setFilter(field: string, value: string | null): void {
    setPageState(1);
    setFilters((current) => {
      if (value === null || value === "") {
        const { [field]: _removed, ...rest } = current;
        return rest;
      }
      return { ...current, [field]: value };
    });
  }

  function setSearch(value: string): void {
    setPageState(1);
    setSearchState(value);
  }

  const total = query.data?.page.total ?? 0;
  const resolvedPageSize = query.data?.page.pageSize ?? pageSize;

  return {
    rows: query.data?.data ?? [],
    total,
    page: query.data?.page.page ?? page,
    pageSize: resolvedPageSize,
    pageCount: Math.max(1, Math.ceil(total / resolvedPageSize)),
    sort,
    filters,
    search,
    isLoading: query.isLoading,
    isFetching: query.isFetching,
    isError: query.isError,
    error: query.error,
    setPage,
    toggleSort,
    setFilter,
    setSearch,
    refetch: query.refetch,
  };
}
