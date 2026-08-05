import { apiRequest } from "../../shared/api/client";

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
