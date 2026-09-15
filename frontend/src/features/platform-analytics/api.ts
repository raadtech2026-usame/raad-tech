import { apiRequest } from "../../shared/api/client";
import { buildOffsetListQuery, type OffsetListParams } from "../../shared/api/listParams";
import { toOffsetPage, type OffsetPage, type OffsetPageWire } from "../../shared/api/types";

/** ADR-0020. Wire shape of `platform_audit.api.schemas.PlatformStatsResponse` — snake_case,
 * exactly as the backend serializes it. */
interface OrganizationStatsWire {
  total: number;
  by_status: Record<string, number>;
  created_today: number;
}

interface VehicleStatsWire {
  total: number;
}

interface DeviceStatsWire {
  total: number;
  online: number;
  offline: number;
}

interface UserStatsWire {
  total: number;
  by_status: Record<string, number>;
  monthly_active: number;
  created_today: number;
}

interface BillingStatsWire {
  subscription_by_status: Record<string, number>;
  expiring_soon: number;
  revenue: number;
  active_by_billing_cycle: Record<string, number>;
}

interface SystemHealthWire {
  database: string;
  broker: string;
}

interface PlatformStatsWire {
  organizations: OrganizationStatsWire;
  vehicles: VehicleStatsWire;
  devices: DeviceStatsWire;
  users: UserStatsWire;
  billing: BillingStatsWire;
  payment_due_organizations: number;
  system_health: SystemHealthWire;
}

export interface PlatformStats {
  organizations: {
    total: number;
    byStatus: Record<string, number>;
    createdToday: number;
  };
  vehicles: {
    total: number;
  };
  devices: {
    total: number;
    online: number;
    offline: number;
  };
  users: {
    total: number;
    byStatus: Record<string, number>;
    monthlyActive: number;
    createdToday: number;
  };
  billing: {
    subscriptionByStatus: Record<string, number>;
    expiringSoon: number;
    revenue: number;
    /** Organization Management phase — `count_active_by_billing_cycle` (a JOIN to `Plan`,
     * platform-wide, non-terminal subscriptions only). Keys are `BillingCycle` values
     * (`"monthly" | "quarterly" | "annual"`); a cycle with zero active subscribers is simply
     * absent from the map, never a `0` entry. */
    activeByBillingCycle: Record<string, number>;
  };
  /** Organization Management phase — organizations whose trial has expired and which have no
   * subscription row at all yet (an expired-trial organization that already has *any*
   * subscription, in any status, is not counted here — its own subscription status already
   * speaks for it). */
  paymentDueOrganizations: number;
  /** `"ok" | "down" | "not_configured"` — `core.health.service.DependencyStatus.label`'s own
   * three values, passed through verbatim rather than re-derived here. */
  systemHealth: {
    database: string;
    broker: string;
  };
}

function toPlatformStats(wire: PlatformStatsWire): PlatformStats {
  return {
    organizations: {
      total: wire.organizations.total,
      byStatus: wire.organizations.by_status,
      createdToday: wire.organizations.created_today,
    },
    vehicles: {
      total: wire.vehicles.total,
    },
    devices: {
      total: wire.devices.total,
      online: wire.devices.online,
      offline: wire.devices.offline,
    },
    users: {
      total: wire.users.total,
      byStatus: wire.users.by_status,
      monthlyActive: wire.users.monthly_active,
      createdToday: wire.users.created_today,
    },
    billing: {
      subscriptionByStatus: wire.billing.subscription_by_status,
      expiringSoon: wire.billing.expiring_soon,
      revenue: wire.billing.revenue,
      activeByBillingCycle: wire.billing.active_by_billing_cycle,
    },
    paymentDueOrganizations: wire.payment_due_organizations,
    systemHealth: {
      database: wire.system_health.database,
      broker: wire.system_health.broker,
    },
  };
}

/** `GET /admin/platform-stats` (ADR-0020). Founder / Regional Manager / Support Staff / Finance
 * Staff — gated server-side by the `admin.platform_stats.read` permission; this function makes
 * no client-side role check of its own (`.claude/rules/frontend.md` #2). */
export async function getPlatformStats(): Promise<PlatformStats> {
  const wire = await apiRequest<PlatformStatsWire>("/admin/platform-stats");
  return toPlatformStats(wire);
}

/** `platform_audit.api.schemas.AuditEntryResponse` — one row of the shared-kernel `audit_entries`
 * ledger (ADR-0007). `action` is the raw domain event type verbatim (e.g. `"VehicleActivated"`,
 * `core/audit/writer.py`'s own module docstring), `entityType`/`entityId` map from
 * `aggregate_type`/`aggregate_id`. No actor *name* is available here — only `actorUserId` (a raw
 * ULID) — resolving it to a display name would need a second, per-row user lookup this frontend
 * does not perform; consumers show the action/entity/time only.
 *
 * `metadata` is the domain event's own payload (e.g. a `SubscriptionGracePeriodExtended` entry
 * carries `grace_period_ends_at`) — the response has always carried it (`api/schemas.py`'s
 * `AuditEntryResponse.metadata`); it was simply never mapped here because no consumer needed it
 * before the Subscription Details troubleshooting page (2026-09-10), which reads it to explain
 * *why* a transition happened, not only that it did. */
export interface AuditEntry {
  id: string;
  organizationId: string | null;
  actorUserId: string | null;
  action: string;
  entityType: string | null;
  entityId: string | null;
  metadata: Record<string, unknown> | null;
  createdAt: string;
}

interface AuditEntryWire {
  id: string;
  organization_id: string | null;
  actor_user_id: string | null;
  action: string;
  entity_type: string | null;
  entity_id: string | null;
  metadata: Record<string, unknown> | null;
  created_at: string;
}

function toAuditEntry(wire: AuditEntryWire): AuditEntry {
  return {
    id: wire.id,
    organizationId: wire.organization_id,
    actorUserId: wire.actor_user_id,
    action: wire.action,
    entityType: wire.entity_type,
    entityId: wire.entity_id,
    metadata: wire.metadata ?? null,
    createdAt: wire.created_at,
  };
}

/** `GET /admin/audit` — Founder / Regional Manager / Support Staff (gated server-side by
 * `admin.audit.read`; **Finance Staff does not hold this grant** in the seeded RBAC matrix, per
 * this file's own `getPlatformStats` precedent for `admin.platform_stats.read` — callers must
 * account for a 403 from this specific role rather than assuming every platform role can reach
 * it). Paginated per API Contracts §7 like every other list route in this codebase; sortable by
 * `created_at`/`action` (`platform_audit/infra/repositories.py`'s own whitelist). */
export async function listAuditEntries(params: OffsetListParams): Promise<OffsetPage<AuditEntry>> {
  const wire = await apiRequest<OffsetPageWire<AuditEntryWire>>(`/admin/audit?${buildOffsetListQuery(params)}`);
  return toOffsetPage(wire, toAuditEntry);
}
