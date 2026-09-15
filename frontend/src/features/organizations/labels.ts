import type { BadgeVariant } from "../../shared/components/Badge/Badge";
import type { OrganizationStatus, OrgType, TrialState } from "./api";

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

/** `TrialState` (derived, never stored — see `Organization.trialState`'s own docstring in
 * `api.ts`) — deliberately independent of `billing.SubscriptionStatus.TRIAL`'s own label
 * (`billing/labels.ts`'s `subscriptionStatusLabel`), which means something unrelated. */
export function trialStateLabel(state: TrialState): string {
  switch (state) {
    case "not_started":
      return "No trial";
    case "trialing":
      return "Trialing";
    case "expired":
      return "Trial expired";
    default:
      return state;
  }
}

export function trialStateTone(state: TrialState): BadgeVariant {
  switch (state) {
    case "not_started":
      return "neutral";
    case "trialing":
      return "info";
    case "expired":
      return "danger";
    default:
      return "neutral";
  }
}
