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
  };
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
    },
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
 * does not perform; consumers show the action/entity/time only. */
export interface AuditEntry {
  id: string;
  organizationId: string | null;
  actorUserId: string | null;
  action: string;
  entityType: string | null;
  entityId: string | null;
  createdAt: string;
}

interface AuditEntryWire {
  id: string;
  organization_id: string | null;
  actor_user_id: string | null;
  action: string;
  entity_type: string | null;
  entity_id: string | null;
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
