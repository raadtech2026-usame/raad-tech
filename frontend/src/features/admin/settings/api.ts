import { apiRequest } from "../../../shared/api/client";
import { buildOffsetListQuery, type OffsetListParams } from "../../../shared/api/listParams";
import type { OffsetPage, OffsetPageWire } from "../../../shared/api/types";

export interface SystemSetting {
  key: string;
  value: Record<string, unknown>;
  scope: string;
}

interface SystemSettingWire {
  key: string;
  value: Record<string, unknown>;
  scope: string;
}

function toSystemSetting(wire: SystemSettingWire): SystemSetting {
  return {
    key: wire.key,
    value: wire.value ?? {},
    scope: wire.scope,
  };
}

export async function listSystemSettings(params?: Partial<OffsetListParams>): Promise<OffsetPage<SystemSetting>> {
  const query = buildOffsetListQuery({
    page: params?.page ?? 1,
    pageSize: params?.pageSize ?? 50,
    sort: params?.sort ?? { field: "key", direction: "asc" },
    filters: params?.filters ?? {},
    search: params?.search ?? "",
  });
  const wire = await apiRequest<OffsetPageWire<SystemSettingWire>>(`/admin/settings?${query}`);
  return {
    data: (wire.data || []).map(toSystemSetting),
    page: {
      total: wire.page.total,
      page: wire.page.page,
      pageSize: wire.page.page_size,
    },
  };
}

export async function updateSystemSetting(
  key: string,
  value: Record<string, unknown>,
  scope: string = "platform",
): Promise<SystemSetting> {
  const wire = await apiRequest<SystemSettingWire>("/admin/settings", {
    method: "PATCH",
    body: {
      key,
      value,
      scope,
    },
  });
  return toSystemSetting(wire);
}
