import type { BadgeVariant } from "../../shared/components/Badge/Badge";
import type { BillingCycle, InvoiceStatus, PlanStatus, SubscriptionStatus } from "./api";

/** Display copy for `billing` enums — kept in one place so the Plans/Subscriptions/Invoices
 * tabs and their detail drawers all render the exact same wording, mirroring
 * `features/organizations/labels.ts`'s own convention. */

export function planStatusLabel(status: PlanStatus): string {
  switch (status) {
    case "active":
      return "Active";
    case "inactive":
      return "Inactive";
    default:
      return status;
  }
}

export function planStatusTone(status: PlanStatus): BadgeVariant {
  switch (status) {
    case "active":
      return "success";
    case "inactive":
      return "neutral";
    default:
      return "neutral";
  }
}

export function billingCycleLabel(cycle: BillingCycle): string {
  switch (cycle) {
    case "monthly":
      return "Monthly";
    case "quarterly":
      return "Quarterly";
    case "annual":
      return "Annual";
    default:
      return cycle;
  }
}

export function subscriptionStatusLabel(status: SubscriptionStatus): string {
  switch (status) {
    case "trial":
      return "Trial";
    case "active":
      return "Active";
    case "suspended":
      return "Suspended";
    case "expired":
      return "Expired";
    case "cancelled":
      return "Cancelled";
    default:
      return status;
  }
}

export function subscriptionStatusTone(status: SubscriptionStatus): BadgeVariant {
  switch (status) {
    case "trial":
      return "info";
    case "active":
      return "success";
    case "suspended":
      return "warning";
    case "expired":
      return "danger";
    case "cancelled":
      return "neutral";
    default:
      return "neutral";
  }
}

/** No `failed` member (`InvoiceStatus`'s own docstring — Database Design §8.3 is exhaustively
 * four values). */
export function invoiceStatusLabel(status: InvoiceStatus): string {
  switch (status) {
    case "draft":
      return "Draft";
    case "issued":
      return "Issued";
    case "paid":
      return "Paid";
    case "void":
      return "Void";
    default:
      return status;
  }
}

export function invoiceStatusTone(status: InvoiceStatus): BadgeVariant {
  switch (status) {
    case "draft":
      return "neutral";
    case "issued":
      return "warning";
    case "paid":
      return "success";
    case "void":
      return "danger";
    default:
      return "neutral";
  }
}
