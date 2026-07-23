import { apiRequest } from "../../../shared/api/client";
import { buildOffsetListQuery, type OffsetListParams } from "../../../shared/api/listParams";
import { toOffsetPage, type OffsetPage, type OffsetPageWire } from "../../../shared/api/types";

/** `organization.domain.value_objects.RegionStatus` (Database Design §4.1's
 * `status ENUM(active,inactive)`). Deliberately its own self-contained copy of the shape
 * `../api.ts` already defines for its own read-only region-picker use — see this module's own
 * `RegionsPage.tsx` docstring for why a dedicated management surface didn't reuse that read
 * path (`.claude/rules/frontend.md` #1's "own self-contained read" precedent, the same
 * discipline `listOrganizationsForPicker` already establishes across every entity subfolder in
 * this codebase). */
export type RegionStatus = "active" | "inactive";

export interface Region {
  id: string;
  name: string;
  geographicScope: string | null;
  status: RegionStatus;
  createdAt: string;
  updatedAt: string;
}

/** Wire shape of `organization.api.schemas.RegionResponse` — snake_case, exactly as the
 * backend serializes it. */
interface RegionWire {
  id: string;
  name: string;
  geographic_scope: string | null;
  status: string;
  created_at: string;
  updated_at: string;
}

function toRegion(wire: RegionWire): Region {
  return {
    id: wire.id,
    name: wire.name,
    geographicScope: wire.geographic_scope,
    status: wire.status as RegionStatus,
    createdAt: wire.created_at,
    updatedAt: wire.updated_at,
  };
}

/** `GET /regions` (API Contracts §4.1) — paginated/filterable/sortable via `usePaginatedQuery`.
 * Whitelist confirmed against `modules/organization/infra/repositories.py`'s
 * `SqlAlchemyRegionRepository`: sortable `name`/`status`, searchable `name`. */
export async function listRegions(params: OffsetListParams): Promise<OffsetPage<Region>> {
  const wire = await apiRequest<OffsetPageWire<RegionWire>>(`/regions?${buildOffsetListQuery(params)}`);
  return toOffsetPage(wire, toRegion);
}

export async function getRegion(id: string): Promise<Region> {
  const wire = await apiRequest<RegionWire>(`/regions/${id}`);
  return toRegion(wire);
}

export interface CreateRegionInput {
  name: string;
  geographicScope?: string | null;
}

/** `POST /regions` (`CreateRegionRequest`) exactly: `name`, `geographic_scope`. Only `founder`
 * holds `organization.regions.create` in the seeded RBAC matrix — `RegionsPage.tsx`'s own
 * `canManage` flag mirrors this exactly (regions are a rare, platform-wide structuring
 * decision, not delegated to `regional_manager`, who holds `.read` only). */
export async function createRegion(input: CreateRegionInput): Promise<Region> {
  const wire = await apiRequest<RegionWire>("/regions", {
    method: "POST",
    body: {
      name: input.name,
      geographic_scope: input.geographicScope ?? null,
    },
  });
  return toRegion(wire);
}

/** `PATCH /regions/{id}` sending only `status` — dispatches to `activate_region`/
 * `deactivate_region`. `name`/`geographic_scope` editing is not wired to any UI this phase,
 * the same restraint every other entity in this codebase already documents for its own
 * status-only PATCH. */
export async function updateRegionStatus(id: string, status: RegionStatus): Promise<Region> {
  const wire = await apiRequest<RegionWire>(`/regions/${id}`, {
    method: "PATCH",
    body: { status },
  });
  return toRegion(wire);
}
