import type { BadgeVariant } from "../../../shared/components/Badge/Badge";
import type { ParentInvoiceStatus, ParentPaymentStatus, ParentStatus, PaymentMethod } from "./api";

/** Display copy for `transport_ops.domain.value_objects.ParentStatus` — kept in one place so the
 * list table, the detail drawer, and the status-transition buttons all render the exact same
 * wording. */

export function statusLabel(status: ParentStatus): string {
  switch (status) {
    case "active":
      return "Active";
    case "inactive":
      return "Inactive";
    default:
      return status;
  }
}

export function statusTone(status: ParentStatus): BadgeVariant {
  switch (status) {
    case "active":
      return "success";
    case "inactive":
      return "neutral";
    default:
      return "neutral";
  }
}

/** Display copy for `ParentPaymentStatus` (`school_erp.ParentFinancialSummaryDTO.status`,
 * 2026-09-10) — `no_invoices` reads as neutral information ("no fees billed yet"), never as a
 * debt, matching that DTO's own docstring. */
export function paymentStatusLabel(status: ParentPaymentStatus): string {
  switch (status) {
    case "paid":
      return "Paid";
    case "partially_paid":
      return "Partially paid";
    case "unpaid":
      return "Unpaid";
    case "no_invoices":
      return "No fees due";
    default:
      return status;
  }
}

export function paymentStatusTone(status: ParentPaymentStatus): BadgeVariant {
  switch (status) {
    case "paid":
      return "success";
    case "partially_paid":
      return "warning";
    case "unpaid":
      return "danger";
    case "no_invoices":
      return "neutral";
    default:
      return "neutral";
  }
}

/** Display copy for `ParentInvoiceStatus` (ADR-0042) — the real Parent Invoice's own
 * Unpaid/Partial/Paid/Cancelled status, distinct from `ParentPaymentStatus` above (the all-time
 * family summary's `partially_paid`/`no_invoices` shape). Two separate types because they come
 * from two separate DTOs with two separate value sets — not merged into one, to avoid a status
 * string that means something subtly different depending on which screen rendered it. */
export function invoiceStatusLabel(status: ParentInvoiceStatus): string {
  switch (status) {
    case "paid":
      return "Paid";
    case "partial":
      return "Partial";
    case "unpaid":
      return "Unpaid";
    case "cancelled":
      return "Cancelled";
    default:
      return status;
  }
}

export function invoiceStatusTone(status: ParentInvoiceStatus): BadgeVariant {
  switch (status) {
    case "paid":
      return "success";
    case "partial":
      return "warning";
    case "unpaid":
      return "danger";
    case "cancelled":
      return "neutral";
    default:
      return "neutral";
  }
}

/** ADR-0047 — how a school received a payment. Same closed set the backend enforces. */
export const PAYMENT_METHOD_OPTIONS: { value: PaymentMethod; label: string }[] = [
  { value: "cash", label: "Cash" },
  { value: "mobile_money", label: "Mobile money (EVC Plus / Zaad)" },
  { value: "bank_transfer", label: "Bank transfer" },
  { value: "cheque", label: "Cheque" },
  { value: "card", label: "Card" },
  { value: "other", label: "Other" },
];

export function paymentMethodLabel(method: string): string {
  return PAYMENT_METHOD_OPTIONS.find((option) => option.value === method)?.label ?? method;
}
