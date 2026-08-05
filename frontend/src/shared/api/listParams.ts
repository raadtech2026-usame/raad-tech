/** Wire-shaped list-query parameters every offset-paginated endpoint accepts
 * (`.claude/rules/api.md` derives from `docs/business/RAAD_Phase3.3_API_Contracts_v1.md` §7/§8;
 * backend implementation: `raad/core/pagination/__init__.py` + `raad/interfaces/http/deps.py`):
 * `?page&page_size`, `?sort=field` (ascending) / `?sort=-field` (descending), `?filter[field]=
 * value` (implicit `eq` only — this frontend never needs `gte`/`lte`/`gt`/`lt`/`in` yet, so only
 * the equality shape is built), `?q=` full-text search.
 *
 * One implementation shared by every feature's list fetcher (`usePaginatedQuery`'s own
 * consumers, `features/organizations/api.ts` today, F2+ tomorrow) instead of each feature
 * hand-rolling the same `URLSearchParams` construction. */

export interface SortState {
  field: string;
  direction: "asc" | "desc";
}

export interface OffsetListParams {
  page: number;
  pageSize: number;
  sort: SortState | null;
  /** `{ field: value }` — one equality filter per field, matching `?filter[field]=value`. */
  filters: Record<string, string>;
  search: string;
}

/** Builds the query string for a `GET` list request. Does not include the leading `?` — call
 * sites compose `` `${path}?${buildOffsetListQuery(params)}` ``. */
export function buildOffsetListQuery(params: OffsetListParams): string {
  const qs = new URLSearchParams();
  qs.set("page", String(params.page));
  qs.set("page_size", String(params.pageSize));

  if (params.sort) {
    qs.set("sort", params.sort.direction === "desc" ? `-${params.sort.field}` : params.sort.field);
  }

  for (const [field, value] of Object.entries(params.filters)) {
    if (value !== "" && value !== undefined && value !== null) {
      qs.set(`filter[${field}]`, value);
    }
  }

  if (params.search) {
    qs.set("q", params.search);
  }

  return qs.toString();
}

/** `?limit&cursor` (`.claude/rules/api.md` derives from API Contracts §7) — the cursor
 * counterpart of `OffsetListParams`, used only by the two routes §7 documents as cursor-paginated
 * (`GET /notifications`, `GET /tracking/trips/{id}/positions`). No `sort` field — cursor mode
 * paginates over one fixed, server-chosen keyset, never a client-chosen sort (`core/pagination`'s
 * own module docstring, mirrored here rather than inventing a sort option the backend rejects). */
export interface CursorListParams {
  limit: number;
  /** `null` means "first page." Always a value previously returned as `page.nextCursor` — never
   * constructed by this app itself (the backend's own cursor is opaque). */
  cursor: string | null;
  filters: Record<string, string>;
}

export function buildCursorListQuery(params: CursorListParams): string {
  const qs = new URLSearchParams();
  qs.set("limit", String(params.limit));

  if (params.cursor) {
    qs.set("cursor", params.cursor);
  }

  for (const [field, value] of Object.entries(params.filters)) {
    if (value !== "" && value !== undefined && value !== null) {
      qs.set(`filter[${field}]`, value);
    }
  }

  return qs.toString();
}
