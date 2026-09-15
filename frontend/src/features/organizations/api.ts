import { apiRequest } from "../../shared/api/client";
import { buildOffsetListQuery, type OffsetListParams } from "../../shared/api/listParams";
import { toOffsetPage, type OffsetPage, type OffsetPageWire } from "../../shared/api/types";

/** `organization.domain.value_objects.OrgType` (Database Design §4.2's `org_type ENUM`). **D3**:
 * only `school` is an active value — the enum is "a documented seam for future variants," not a
 * set this frontend invents additional options for ahead of an approved backend extension. The
 * create-organization form therefore offers exactly one, fixed choice, never a dropdown implying
 * others exist. */
export type OrgType = "school";

/** `organization.domain.value_objects.OrganizationStatus` (Database Design §4.2's
 * `status ENUM(active,suspended,inactive)`) — the tenant's administrative lifecycle. Deliberately
 * distinct from `TrialState`/`billing`'s `SubscriptionStatus` below: an organization can be
 * `active` (administratively fine) while its trial is `expired` and it has no subscription yet. */
export type OrganizationStatus = "active" | "suspended" | "inactive";

/** `organization.domain.value_objects.TrialState` — derived, never a stored column (computed by
 * `Organization.trial_state()` from `trial_started_at`/`trial_ends_at`). Deliberately independent
 * of `billing`'s own `SubscriptionStatus.TRIAL` enum value, which means something unrelated (a
 * subscription's permanent "just opened, not yet paid" starting label) — see that type's own
 * comment in `features/billing/api.ts`. */
export type TrialState = "not_started" | "trialing" | "expired";

export interface Organization {
  id: string;
  name: string;
  orgType: OrgType;
  parentOrgId: string | null;
  regionId: string;
  status: OrganizationStatus;
  createdAt: string;
  updatedAt: string;
  trialStartedAt: string | null;
  trialEndsAt: string | null;
  trialState: TrialState;
}

/** `organization.domain.value_objects.RegionStatus` (Database Design §4.1's
 * `status ENUM(active,inactive)`). */
export type RegionStatus = "active" | "inactive";

export interface Region {
  id: string;
  name: string;
  geographicScope: string | null;
  status: RegionStatus;
  createdAt: string;
  updatedAt: string;
}

/** Wire shape of `organization.api.schemas.OrganizationResponse` — snake_case, exactly as the
 * backend serializes it. */
interface OrganizationWire {
  id: string;
  name: string;
  org_type: string;
  parent_org_id: string | null;
  region_id: string;
  status: string;
  created_at: string;
  updated_at: string;
  trial_started_at?: string | null;
  trial_ends_at?: string | null;
  trial_state?: string;
}

/** Wire shape of `organization.api.schemas.RegionResponse`. */
interface RegionWire {
  id: string;
  name: string;
  geographic_scope: string | null;
  status: string;
  created_at: string;
  updated_at: string;
}

function toOrganization(wire: OrganizationWire): Organization {
  return {
    id: wire.id,
    name: wire.name,
    orgType: wire.org_type as OrgType,
    parentOrgId: wire.parent_org_id,
    regionId: wire.region_id,
    status: wire.status as OrganizationStatus,
    createdAt: wire.created_at,
    updatedAt: wire.updated_at,
    trialStartedAt: wire.trial_started_at ?? null,
    trialEndsAt: wire.trial_ends_at ?? null,
    trialState: (wire.trial_state as TrialState) ?? "not_started",
  };
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

/** `GET /organizations` (API Contracts §4.1/§7/§8) — paginated/filterable/sortable via
 * `usePaginatedQuery`. Not yet scope-filtered server-side (CLAUDE.md's own flagged, system-wide
 * gap: every `list_page` still applies an unrestricted `TenantRegionScope`) — every platform
 * role that can reach this route currently sees every organization, not just their own
 * region/assignment. Nothing this frontend can fix; noted so it isn't mistaken for a UI bug. */
export async function listOrganizations(params: OffsetListParams): Promise<OffsetPage<Organization>> {
  const wire = await apiRequest<OffsetPageWire<OrganizationWire>>(
    `/organizations?${buildOffsetListQuery(params)}`,
  );
  return toOffsetPage(wire, toOrganization);
}

export async function getOrganization(id: string): Promise<Organization> {
  const wire = await apiRequest<OrganizationWire>(`/organizations/${id}`);
  return toOrganization(wire);
}

export interface CreateOrganizationInput {
  name: string;
  orgType: OrgType;
  regionId: string;
  parentOrgId?: string | null;
  /** ADR-0040 §5. When supplied, onboarding also opens the organization's subscription and
   * issues its first invoice, reusing `open_subscription`'s own period arithmetic. Optional so
   * an organization can be created before its commercial tier is agreed. A failure on the
   * billing side is logged, not propagated — the organization still exists, and the platform
   * Subscriptions view surfaces the gap. Mutually exclusive with `trialEnabled` — the backend
   * rejects a request that sets both. */
  planId?: string | null;
  /** Starts the organization on a time-boxed trial instead of selecting a plan now — a trial
   * defers subscription/plan selection entirely (`organization.domain.entities.Organization.
   * start_trial`). Mutually exclusive with `planId`. */
  trialEnabled?: boolean;
  /** Required when `trialEnabled` is set. */
  trialDurationDays?: number | null;
  /** ADR-0017: Organization Onboarding is one guided workflow now — these identity fields
   * provision the Organization's first Org Admin login in the same request. At least one of
   * `adminEmail`/`adminPhone` is required (`iam.User`'s own invariant). */
  adminFullName: string;
  adminEmail?: string | null;
  adminPhone?: string | null;
}

/** Wire shape of `organization.api.schemas.OrganizationOnboardedResponse` (ADR-0017) —
 * `POST /organizations`'s actual response shape: the usual `OrganizationResponse` plus the
 * newly-provisioned Org Admin's `user_id` and a one-time temporary password. */
interface OrganizationOnboardedWire {
  organization: OrganizationWire;
  admin_user_id: string;
  temporary_password: string;
}

export interface OnboardedOrganization {
  organization: Organization;
  adminUserId: string;
  /** Surfaced exactly once, in this response — never retrievable again via any other
   * endpoint. Hand it off to the Org Admin immediately; do not persist it client-side beyond
   * this one-time reveal. */
  temporaryPassword: string;
}

/** `POST /organizations` (ADR-0017, API Contracts §4.1). */
export async function createOrganization(
  input: CreateOrganizationInput,
): Promise<OnboardedOrganization> {
  const wire = await apiRequest<OrganizationOnboardedWire>("/organizations", {
    method: "POST",
    body: {
      name: input.name,
      org_type: input.orgType,
      region_id: input.regionId,
      parent_org_id: input.parentOrgId ?? null,
      plan_id: input.planId ?? null,
      trial_enabled: input.trialEnabled ?? false,
      trial_duration_days: input.trialDurationDays ?? null,
      admin_full_name: input.adminFullName,
      admin_email: input.adminEmail ?? null,
      admin_phone: input.adminPhone ?? null,
    },
  });
  return {
    organization: toOrganization(wire.organization),
    adminUserId: wire.admin_user_id,
    temporaryPassword: wire.temporary_password,
  };
}

/** `PATCH /organizations/{id}` (API Contracts §4.1) — limited to the `status` transition the
 * Application layer actually exposes (`suspend_organization`/`reactivate_organization`/
 * `deactivate_organization`). API Contracts §4.1 also lists `billing_model` as a `PATCH`
 * input, but ADR-0016 (RAAD business model realignment) removed that field from `Organization`
 * entirely — RAAD bills Organizations only now, so there is nothing left to edit. */
export async function updateOrganizationStatus(
  id: string,
  status: OrganizationStatus,
): Promise<Organization> {
  const wire = await apiRequest<OrganizationWire>(`/organizations/${id}`, {
    method: "PATCH",
    body: { status },
  });
  return toOrganization(wire);
}

/** `PATCH /organizations/{id}` with `name` (Organization Management phase) — the one identity
 * field this backend has real write support for (`Organization.rename`); `region_id`/`org_type`/
 * `parent_org_id` remain deliberately constructor-set-only, per that entity's own documented
 * decision. Same route as `updateOrganizationStatus`, a different body field — the backend
 * accepts either or both in one request, though this frontend only ever sends one at a time. */
export async function renameOrganization(id: string, name: string): Promise<Organization> {
  const wire = await apiRequest<OrganizationWire>(`/organizations/${id}`, {
    method: "PATCH",
    body: { name },
  });
  return toOrganization(wire);
}

/** `GET /regions` (API Contracts §4.1) — read-only lookup consumed by the organization
 * create-form's region picker and the list/detail views' region-name display. This module does
 * not build a Regions management feature (no regions list page, no create/edit-region UI) —
 * only the minimal read path `RegisterOrganizationRequest.region_id` (a required field) makes
 * unavoidable. */
export async function listRegions(params: OffsetListParams): Promise<OffsetPage<Region>> {
  const wire = await apiRequest<OffsetPageWire<RegionWire>>(`/regions?${buildOffsetListQuery(params)}`);
  return toOffsetPage(wire, toRegion);
}
