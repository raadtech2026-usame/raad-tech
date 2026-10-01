import { apiRequest } from "../../../shared/api/client";
import { buildOffsetListQuery, type OffsetListParams } from "../../../shared/api/listParams";
import { toOffsetPage, type OffsetPage, type OffsetPageWire } from "../../../shared/api/types";

/**
 * Transport staff, bus crew and staff documents (ADR-0049, ADR-0050, ADR-0051).
 *
 * Everyone who works on a school bus is a staff member; a driver is a staff member who also has
 * a licence and a login. Job titles and document types are each organization's own. Emergency
 * contacts and document numbers come back `null` for everyone but the Org Admin — the server
 * nulls them, and `privateFieldsVisible` says when that happened so the UI never shows "not
 * recorded" for a value it simply may not see.
 */

export type StaffStatus = "active" | "inactive" | "left";
export type AssignmentKind = "permanent" | "temporary";
export type DocumentStatus = "valid" | "expiring" | "expired" | "no_expiry" | "superseded";

export interface StaffRole {
  id: string;
  organizationId: string;
  name: string;
  sortOrder: number;
  isArchived: boolean;
}

export interface StaffSummary {
  id: string;
  organizationId: string;
  fullName: string;
  phone: string | null;
  roleId: string | null;
  roleName: string | null;
  employeeRef: string | null;
  status: StaffStatus;
  isDriver: boolean;
  /** ADR-0058; `null` for someone who has left. */
  complianceStatus: ComplianceStatus | null;
}

export type ComplianceStatus = "compliant" | "expiring" | "not_compliant";
export type DocumentRequirement = "none" | "drivers" | "all_staff";
export type DocumentEnforcement = "warn" | "block";

export interface ComplianceGap {
  typeId: string;
  typeName: string;
  reason: "missing" | "expired";
  expiredOn: string | null;
  /** The type blocks new planning (ADR-0059 §3). */
  blocks: boolean;
}

/** ADR-0058 §2. Computed by the server on every read; never carries a document number. */
export interface Compliance {
  status: ComplianceStatus;
  gaps: ComplianceGap[];
  expiring: { typeId: string; typeName: string; expiresOn: string }[];
  isBlocked: boolean;
}

export interface StaffComplianceRow {
  staffId: string;
  staffName: string;
  roleName: string | null;
  isDriver: boolean;
  compliance: Compliance;
}

export interface DocumentTypeImpact {
  appliesTo: number;
  notCompliant: number;
}

export interface StaffDriverProfile {
  driverId: string;
  userId: string;
  licenseNo: string;
  status: "active" | "inactive";
}

export interface Staff {
  id: string;
  organizationId: string;
  fullName: string;
  phone: string | null;
  alternatePhone: string | null;
  roleId: string | null;
  roleName: string | null;
  employeeRef: string | null;
  startDate: string | null;
  status: StaffStatus;
  emergencyContactName: string | null;
  emergencyContactPhone: string | null;
  notes: string | null;
  leftOn: string | null;
  driver: StaffDriverProfile | null;
  privateFieldsVisible: boolean;
  createdAt: string;
  updatedAt: string;
  compliance: Compliance | null;
}

export interface CrewAssignment {
  id: string;
  organizationId: string;
  staffId: string;
  staffName: string;
  vehicleId: string;
  roleId: string | null;
  roleName: string | null;
  routeId: string | null;
  startsOn: string;
  endsOn: string | null;
  kind: AssignmentKind;
  reason: string | null;
  isCurrent: boolean;
  createdAt: string;
  /** ADR-0059 §3: only on the response to assigning; empty on reads. */
  warnings: string[];
}

export interface DocumentType {
  id: string;
  organizationId: string;
  name: string;
  alertLeadDays: number[];
  isArchived: boolean;
  requiredFor: DocumentRequirement;
  enforcement: DocumentEnforcement;
}

export interface StaffDocument {
  id: string;
  organizationId: string;
  staffId: string;
  staffName: string;
  typeId: string;
  typeName: string;
  number: string | null;
  issuedOn: string | null;
  expiresOn: string | null;
  notes: string | null;
  status: DocumentStatus;
  daysLeft: number | null;
  replacedById: string | null;
  privateFieldsVisible: boolean;
  createdAt: string;
}

// ---- wire shapes ----------------------------------------------------------------------------

interface StaffRoleWire {
  id: string;
  organization_id: string;
  name: string;
  sort_order: number;
  is_archived: boolean;
}

interface StaffSummaryWire {
  id: string;
  organization_id: string;
  full_name: string;
  phone: string | null;
  role_id: string | null;
  role_name: string | null;
  employee_ref: string | null;
  status: string;
  is_driver: boolean;
  compliance_status?: string | null;
}

/* eslint-disable @typescript-eslint/no-explicit-any */
export function toCompliance(wire: any): Compliance | null {
  if (!wire) return null;
  return {
    status: wire.status,
    gaps: (wire.gaps ?? []).map((g: any) => ({
      typeId: g.type_id,
      typeName: g.type_name,
      reason: g.reason,
      expiredOn: g.expired_on,
      blocks: g.blocks,
    })),
    expiring: (wire.expiring ?? []).map((e: any) => ({ typeId: e.type_id, typeName: e.type_name, expiresOn: e.expires_on })),
    isBlocked: Boolean(wire.is_blocked),
  };
}
/* eslint-enable @typescript-eslint/no-explicit-any */

interface StaffWire {
  id: string;
  organization_id: string;
  full_name: string;
  phone: string | null;
  alternate_phone: string | null;
  role_id: string | null;
  role_name: string | null;
  employee_ref: string | null;
  start_date: string | null;
  status: string;
  emergency_contact_name: string | null;
  emergency_contact_phone: string | null;
  notes: string | null;
  left_on: string | null;
  driver: { driver_id: string; user_id: string; license_no: string; status: string } | null;
  private_fields_visible: boolean;
  created_at: string;
  updated_at: string;
  compliance?: unknown;
}

interface CrewAssignmentWire {
  id: string;
  organization_id: string;
  staff_id: string;
  staff_name: string;
  vehicle_id: string;
  role_id: string | null;
  role_name: string | null;
  route_id: string | null;
  starts_on: string;
  ends_on: string | null;
  kind: string;
  reason: string | null;
  is_current: boolean;
  created_at: string;
  warnings?: string[];
}

interface DocumentTypeWire {
  id: string;
  organization_id: string;
  name: string;
  alert_lead_days: number[];
  is_archived: boolean;
  required_for?: string;
  enforcement?: string;
}

interface StaffDocumentWire {
  id: string;
  organization_id: string;
  staff_id: string;
  staff_name: string;
  type_id: string;
  type_name: string;
  number: string | null;
  issued_on: string | null;
  expires_on: string | null;
  notes: string | null;
  status: string;
  days_left: number | null;
  replaced_by_id: string | null;
  private_fields_visible: boolean;
  created_at: string;
}

export function toStaffRole(wire: StaffRoleWire): StaffRole {
  return {
    id: wire.id,
    organizationId: wire.organization_id,
    name: wire.name,
    sortOrder: wire.sort_order,
    isArchived: wire.is_archived,
  };
}

function toStaffSummary(wire: StaffSummaryWire): StaffSummary {
  return {
    id: wire.id,
    organizationId: wire.organization_id,
    fullName: wire.full_name,
    phone: wire.phone,
    roleId: wire.role_id,
    roleName: wire.role_name,
    employeeRef: wire.employee_ref,
    status: wire.status as StaffStatus,
    isDriver: wire.is_driver,
    complianceStatus: (wire.compliance_status ?? null) as ComplianceStatus | null,
  };
}

export function toStaff(wire: StaffWire): Staff {
  return {
    id: wire.id,
    organizationId: wire.organization_id,
    fullName: wire.full_name,
    phone: wire.phone,
    alternatePhone: wire.alternate_phone,
    roleId: wire.role_id,
    roleName: wire.role_name,
    employeeRef: wire.employee_ref,
    startDate: wire.start_date,
    status: wire.status as StaffStatus,
    emergencyContactName: wire.emergency_contact_name,
    emergencyContactPhone: wire.emergency_contact_phone,
    notes: wire.notes,
    leftOn: wire.left_on,
    driver: wire.driver
      ? {
          driverId: wire.driver.driver_id,
          userId: wire.driver.user_id,
          licenseNo: wire.driver.license_no,
          status: wire.driver.status as "active" | "inactive",
        }
      : null,
    privateFieldsVisible: wire.private_fields_visible,
    createdAt: wire.created_at,
    updatedAt: wire.updated_at,
    compliance: toCompliance(wire.compliance),
  };
}

function toCrewAssignment(wire: CrewAssignmentWire): CrewAssignment {
  return {
    id: wire.id,
    organizationId: wire.organization_id,
    staffId: wire.staff_id,
    staffName: wire.staff_name,
    vehicleId: wire.vehicle_id,
    roleId: wire.role_id,
    roleName: wire.role_name,
    routeId: wire.route_id,
    startsOn: wire.starts_on,
    endsOn: wire.ends_on,
    kind: wire.kind as AssignmentKind,
    reason: wire.reason,
    isCurrent: wire.is_current,
    createdAt: wire.created_at,
    warnings: wire.warnings ?? [],
  };
}

function toDocumentType(wire: DocumentTypeWire): DocumentType {
  return {
    id: wire.id,
    organizationId: wire.organization_id,
    name: wire.name,
    alertLeadDays: wire.alert_lead_days,
    isArchived: wire.is_archived,
    requiredFor: (wire.required_for ?? "none") as DocumentRequirement,
    enforcement: (wire.enforcement ?? "warn") as DocumentEnforcement,
  };
}

export function toStaffDocument(wire: StaffDocumentWire): StaffDocument {
  return {
    id: wire.id,
    organizationId: wire.organization_id,
    staffId: wire.staff_id,
    staffName: wire.staff_name,
    typeId: wire.type_id,
    typeName: wire.type_name,
    number: wire.number,
    issuedOn: wire.issued_on,
    expiresOn: wire.expires_on,
    notes: wire.notes,
    status: wire.status as DocumentStatus,
    daysLeft: wire.days_left,
    replacedById: wire.replaced_by_id,
    privateFieldsVisible: wire.private_fields_visible,
    createdAt: wire.created_at,
  };
}

function organizationQuery(organizationId: string | null | undefined): string {
  return organizationId ? `?organization_id=${encodeURIComponent(organizationId)}` : "";
}

// ---- job titles -----------------------------------------------------------------------------

export async function listStaffRoles(organizationId?: string | null): Promise<StaffRole[]> {
  const wire = await apiRequest<StaffRoleWire[]>(`/transport-staff-roles${organizationQuery(organizationId)}`);
  return wire.map(toStaffRole);
}

export interface SaveStaffRoleInput {
  name: string;
  sortOrder: number;
  isArchived?: boolean;
}

export async function createStaffRole(input: SaveStaffRoleInput): Promise<StaffRole> {
  const wire = await apiRequest<StaffRoleWire>("/transport-staff-roles", {
    method: "POST",
    body: { name: input.name, sort_order: input.sortOrder },
  });
  return toStaffRole(wire);
}

export async function updateStaffRole(id: string, input: SaveStaffRoleInput): Promise<StaffRole> {
  const wire = await apiRequest<StaffRoleWire>(`/transport-staff-roles/${id}`, {
    method: "PATCH",
    body: { name: input.name, sort_order: input.sortOrder, is_archived: input.isArchived ?? false },
  });
  return toStaffRole(wire);
}

/** Adds whichever default titles are missing; pressing it twice changes nothing. */
export async function addDefaultStaffRoles(): Promise<StaffRole[]> {
  const wire = await apiRequest<StaffRoleWire[]>("/transport-staff-roles/defaults", {
    method: "POST",
    body: {},
  });
  return wire.map(toStaffRole);
}

// ---- staff ----------------------------------------------------------------------------------

export async function listStaff(params: OffsetListParams): Promise<OffsetPage<StaffSummary>> {
  const wire = await apiRequest<OffsetPageWire<StaffSummaryWire>>(`/transport-staff?${buildOffsetListQuery(params)}`);
  return toOffsetPage(wire, toStaffSummary);
}

export async function getStaff(id: string): Promise<Staff> {
  return toStaff(await apiRequest<StaffWire>(`/transport-staff/${id}`));
}

export interface StaffProfileInput {
  fullName: string;
  phone: string | null;
  alternatePhone: string | null;
  roleId: string | null;
  employeeRef: string | null;
  startDate: string | null;
  emergencyContactName: string | null;
  emergencyContactPhone: string | null;
  notes: string | null;
}

function profileBody(input: StaffProfileInput): Record<string, string | null> {
  return {
    full_name: input.fullName,
    phone: input.phone,
    alternate_phone: input.alternatePhone,
    role_id: input.roleId,
    employee_ref: input.employeeRef,
    start_date: input.startDate,
    emergency_contact_name: input.emergencyContactName,
    emergency_contact_phone: input.emergencyContactPhone,
    notes: input.notes,
  };
}

export async function registerStaff(input: StaffProfileInput): Promise<Staff> {
  const wire = await apiRequest<StaffWire>("/transport-staff", { method: "POST", body: profileBody(input) });
  return toStaff(wire);
}

/** Sends every profile field, so a cleared input clears the stored value. */
export async function updateStaff(id: string, input: StaffProfileInput): Promise<Staff> {
  const wire = await apiRequest<StaffWire>(`/transport-staff/${id}`, { method: "PATCH", body: profileBody(input) });
  return toStaff(wire);
}

/** `left` also ends their bus assignments and disables their driver login, in one step. */
export async function changeStaffStatus(id: string, status: StaffStatus): Promise<Staff> {
  const wire = await apiRequest<StaffWire>(`/transport-staff/${id}/status`, { method: "POST", body: { status } });
  return toStaff(wire);
}

export interface GrantDriverAccessInput {
  licenseNo: string;
  email: string | null;
  phone: string | null;
}

export interface GrantDriverAccessResult {
  driverId: string;
  temporaryPassword: string;
}

export async function grantDriverAccess(staffId: string, input: GrantDriverAccessInput): Promise<GrantDriverAccessResult> {
  const wire = await apiRequest<{ driver: { id: string }; temporary_password: string }>(
    `/transport-staff/${staffId}/driver-access`,
    { method: "POST", body: { license_no: input.licenseNo, email: input.email, phone: input.phone } },
  );
  return { driverId: wire.driver.id, temporaryPassword: wire.temporary_password };
}

// ---- bus crew -------------------------------------------------------------------------------

export async function listCrew(filter: { vehicleId?: string; staffId?: string; current?: boolean }): Promise<CrewAssignment[]> {
  const params = new URLSearchParams();
  if (filter.vehicleId) params.set("vehicle_id", filter.vehicleId);
  if (filter.staffId) params.set("staff_id", filter.staffId);
  if (filter.current) params.set("current", "true");
  const wire = await apiRequest<CrewAssignmentWire[]>(`/staff-assignments?${params.toString()}`);
  return wire.map(toCrewAssignment);
}

export interface AssignToBusInput {
  staffId: string;
  vehicleId: string;
  kind: AssignmentKind;
  startsOn: string | null;
  endsOn: string | null;
  routeId: string | null;
  roleId: string | null;
  reason: string | null;
}

export async function assignToBus(input: AssignToBusInput): Promise<CrewAssignment> {
  const wire = await apiRequest<CrewAssignmentWire>("/staff-assignments", {
    method: "POST",
    body: {
      staff_id: input.staffId,
      vehicle_id: input.vehicleId,
      kind: input.kind,
      starts_on: input.startsOn,
      ends_on: input.endsOn,
      route_id: input.routeId,
      role_id: input.roleId,
      reason: input.reason,
    },
  });
  return toCrewAssignment(wire);
}

export async function endCrewAssignment(id: string, endsOn: string | null = null): Promise<CrewAssignment> {
  const wire = await apiRequest<CrewAssignmentWire>(`/staff-assignments/${id}/end`, {
    method: "POST",
    body: { ends_on: endsOn },
  });
  return toCrewAssignment(wire);
}

// ---- documents ------------------------------------------------------------------------------

export async function listDocumentTypes(organizationId?: string | null): Promise<DocumentType[]> {
  const wire = await apiRequest<DocumentTypeWire[]>(`/staff-document-types${organizationQuery(organizationId)}`);
  return wire.map(toDocumentType);
}

export interface SaveDocumentTypeInput {
  name: string;
  alertLeadDays: number[];
  isArchived?: boolean;
  /** ADR-0058 §1. Left out, the server keeps the current setting. */
  requiredFor?: DocumentRequirement;
  enforcement?: DocumentEnforcement;
}

export async function createDocumentType(input: SaveDocumentTypeInput): Promise<DocumentType> {
  const wire = await apiRequest<DocumentTypeWire>("/staff-document-types", {
    method: "POST",
    body: { name: input.name, alert_lead_days: input.alertLeadDays },
  });
  return toDocumentType(wire);
}

export async function updateDocumentType(id: string, input: SaveDocumentTypeInput): Promise<DocumentType> {
  const wire = await apiRequest<DocumentTypeWire>(`/staff-document-types/${id}`, {
    method: "PATCH",
    body: {
      name: input.name,
      alert_lead_days: input.alertLeadDays,
      is_archived: input.isArchived ?? false,
      required_for: input.requiredFor,
      enforcement: input.enforcement,
    },
  });
  return toDocumentType(wire);
}

/** ADR-0058 §3: what the requirement would mean today. Reads only. */
export async function getDocumentTypeImpact(id: string, requiredFor: DocumentRequirement): Promise<DocumentTypeImpact> {
  const wire = await apiRequest<{ applies_to: number; not_compliant: number }>(
    `/staff-document-types/${id}/impact?required_for=${requiredFor}`,
  );
  return { appliesTo: wire.applies_to, notCompliant: wire.not_compliant };
}

export async function listStaffCompliance(): Promise<StaffComplianceRow[]> {
  /* eslint-disable-next-line @typescript-eslint/no-explicit-any */
  const wire = await apiRequest<any[]>("/staff-compliance");
  return wire.map((row) => ({
    staffId: row.staff_id,
    staffName: row.staff_name,
    roleName: row.role_name,
    isDriver: row.is_driver,
    compliance: toCompliance(row.compliance) as Compliance,
  }));
}

export async function addDefaultDocumentTypes(): Promise<DocumentType[]> {
  const wire = await apiRequest<DocumentTypeWire[]>("/staff-document-types/defaults", { method: "POST", body: {} });
  return wire.map(toDocumentType);
}

export async function listStaffDocuments(staffId: string): Promise<StaffDocument[]> {
  const wire = await apiRequest<StaffDocumentWire[]>(`/transport-staff/${staffId}/documents`);
  return wire.map(toStaffDocument);
}

export interface RecordDocumentInput {
  typeId: string;
  number: string | null;
  issuedOn: string | null;
  expiresOn: string | null;
  notes: string | null;
  /** Set when this is a renewal: the old document is marked superseded. */
  replacesId: string | null;
}

export async function recordStaffDocument(staffId: string, input: RecordDocumentInput): Promise<StaffDocument> {
  const wire = await apiRequest<StaffDocumentWire>(`/transport-staff/${staffId}/documents`, {
    method: "POST",
    body: {
      type_id: input.typeId,
      number: input.number,
      issued_on: input.issuedOn,
      expires_on: input.expiresOn,
      notes: input.notes,
      replaces_id: input.replacesId,
    },
  });
  return toStaffDocument(wire);
}

export async function listExpiringDocuments(): Promise<StaffDocument[]> {
  const wire = await apiRequest<StaffDocumentWire[]>("/staff-documents/expiring");
  return wire.map(toStaffDocument);
}

// ---- pickers (self-contained copies, `.claude/rules/frontend.md` #1) ------------------------

export interface VehicleOption {
  id: string;
  plateNo: string;
  label: string | null;
}

export async function listVehiclesForPicker(organizationId: string | null): Promise<VehicleOption[]> {
  const filters: Record<string, string> = { status: "active" };
  if (organizationId) filters.organization_id = organizationId;
  const query = buildOffsetListQuery({
    page: 1,
    pageSize: 100,
    sort: { field: "plate_no", direction: "asc" },
    filters,
    search: "",
  });
  const wire = await apiRequest<OffsetPageWire<{ id: string; plate_no: string; label: string | null }>>(`/vehicles?${query}`);
  return wire.data.map((vehicle) => ({ id: vehicle.id, plateNo: vehicle.plate_no, label: vehicle.label }));
}

export interface RouteOption {
  id: string;
  name: string;
}

export async function listRoutesForPicker(): Promise<RouteOption[]> {
  const query = buildOffsetListQuery({
    page: 1,
    pageSize: 100,
    sort: { field: "name", direction: "asc" },
    filters: { status: "active" },
    search: "",
  });
  const wire = await apiRequest<OffsetPageWire<{ id: string; name: string }>>(`/routes?${query}`);
  return wire.data.map((route) => ({ id: route.id, name: route.name }));
}
