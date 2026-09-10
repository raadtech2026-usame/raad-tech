import type { OffsetListParams } from "../../../shared/api/listParams";
import { listAuditEntries } from "../../platform-analytics/api";
import { listUsers } from "../../admin/users/api";
import { listVehicles } from "../../fleet-devices/vehicles/api";
import { listDevices } from "../../fleet-devices/devices/api";
import { listDrivers } from "../../transport-ops/drivers/api";
import { listRoutes } from "../../transport-ops/routes/api";
import { countStudents } from "../../transport-ops/students/api";
import { countParents } from "../../transport-ops/parents/api";
import { listInvoices, listPayments, listSubscriptions } from "../../billing/api";
import {
  listExpenses,
  listIncome,
  listStudentInvoices,
  listStudentPayments,
} from "../../school-erp/api";

/**
 * Organization Details — one organization, read through the endpoints that already own each
 * slice of it.
 *
 * **Nothing here is a new query.** Every function below calls a list client that already exists
 * in the feature that owns that resource, passing one extra filter. That is the whole design:
 * the Organization Details page is a *composition*, not a new read model, so a fix to how
 * vehicles are listed lands here for free and there is no second implementation to drift.
 *
 * **Cross-feature imports, deliberately.** This file breaks the usual "a feature imports only
 * its own `api.ts`" discipline, and it is the one place where doing so is right: an aggregation
 * page spans contexts by definition, and the alternative — reimplementing eight list clients
 * here — is exactly the duplication that rule exists to prevent. The imports go *into* the
 * owning feature's public client, never around it.
 *
 * **What the backend genuinely cannot give us, and why.** RAAD staff hold `.count` but not
 * `.list` for students and parents: the platform manages organizations, not individual children
 * and families (CLAUDE.md, Business Model). Those two tabs therefore show a real count and say
 * plainly why there is no roster — inventing one would mean granting RAAD a permission the
 * product deliberately withholds.
 */

/** Every list on this page is the same shape: one organization, first page, no search. */
export function orgScopedParams(
  organizationId: string,
  overrides: Partial<OffsetListParams> = {},
): OffsetListParams {
  return {
    page: 1,
    pageSize: 25,
    sort: null,
    search: "",
    ...overrides,
    filters: { organization_id: organizationId, ...(overrides.filters ?? {}) },
  };
}

export const orgUsers = (organizationId: string, params?: Partial<OffsetListParams>) =>
  listUsers(orgScopedParams(organizationId, params));

export const orgVehicles = (organizationId: string, params?: Partial<OffsetListParams>) =>
  listVehicles(orgScopedParams(organizationId, params));

export const orgDevices = (organizationId: string, params?: Partial<OffsetListParams>) =>
  listDevices(orgScopedParams(organizationId, params));

export const orgDrivers = (organizationId: string, params?: Partial<OffsetListParams>) =>
  listDrivers(orgScopedParams(organizationId, params));

export const orgRoutes = (organizationId: string, params?: Partial<OffsetListParams>) =>
  listRoutes(orgScopedParams(organizationId, params));

export const orgSubscriptions = (organizationId: string) =>
  listSubscriptions(orgScopedParams(organizationId));

export const orgInvoices = (organizationId: string, params?: Partial<OffsetListParams>) =>
  listInvoices(orgScopedParams(organizationId, params));

export const orgPayments = (organizationId: string, params?: Partial<OffsetListParams>) =>
  listPayments(orgScopedParams(organizationId, params));

export const orgAudit = (organizationId: string, params?: Partial<OffsetListParams>) =>
  listAuditEntries(orgScopedParams(organizationId, params));

export const orgStudentInvoices = (organizationId: string) =>
  listStudentInvoices(orgScopedParams(organizationId));

export const orgStudentPayments = (organizationId: string) =>
  listStudentPayments(orgScopedParams(organizationId));

export const orgIncome = (organizationId: string) =>
  listIncome(orgScopedParams(organizationId));

export const orgExpenses = (organizationId: string) =>
  listExpenses(orgScopedParams(organizationId));

/** Count-only, by design — see this module's docstring. */
export const orgStudentCount = (organizationId: string) => countStudents(organizationId);
export const orgParentCount = (organizationId: string) => countParents(organizationId);
