import type { BadgeVariant } from "../../shared/components/Badge/Badge";
import type { BillingModel, OrganizationStatus, OrgType } from "./api";

/** Display copy for `organization.domain.value_objects` enums — kept in one place so the list
 * table, the detail drawer, and the create form all render the exact same wording. */

export function orgTypeLabel(orgType: OrgType): string {
  switch (orgType) {
    case "school":
      return "School";
    default:
      return orgType;
  }
}

export function billingModelLabel(model: BillingModel): string {
  switch (model) {
    case "organization_pays":
      return "Organization pays";
    case "parent_pays":
      return "Parent pays";
    default:
      return model;
  }
}

export function statusLabel(status: OrganizationStatus): string {
  switch (status) {
    case "active":
      return "Active";
    case "suspended":
      return "Suspended";
    case "inactive":
      return "Inactive";
    default:
      return status;
  }
}

/** No `trial` tone exists — only the three real `OrganizationStatus` values are ever mapped. */
export function statusTone(status: OrganizationStatus): BadgeVariant {
  switch (status) {
    case "active":
      return "success";
    case "suspended":
      return "warning";
    case "inactive":
      return "neutral";
    default:
      return "neutral";
  }
}
