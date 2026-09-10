import { listAuditEntries } from "../../platform-analytics/api";
import { listInvoices, listPayments, listPlans } from "../api";

/**
 * Subscription Details — one subscription, read through the endpoints that already own each
 * slice of it. Mirrors `features/organizations/details/api.ts`'s own documented shape: nothing
 * here is a new query, every function composes a list client that already exists (`../api.ts`,
 * `../../platform-analytics/api.ts`), and the composition is the whole design.
 *
 * `getSubscription`/`getOrganization` themselves are not re-exported from here — the page reads
 * those straight from `../api` and `../../organizations/api`, the same "aggregation page imports
 * across features, but does not hide where a function actually lives" precedent
 * `organizations/details/api.ts` already sets.
 */

/** Every invoice belonging to one subscription. `subscription_id` is a real filterable field on
 * `GET /billing/invoices` (`../api.ts`'s own docstring) — this is a server-side filter, not a
 * client-side one. Sorted newest-first so the most recent invoice — "the current invoice" — is
 * always `data[0]`. */
export function subscriptionInvoices(subscriptionId: string) {
  return listInvoices({
    page: 1,
    pageSize: 100,
    sort: { field: "created_at", direction: "desc" },
    filters: { subscription_id: subscriptionId },
    search: "",
  });
}

/** Every payment against this organization's invoices. `Payment` carries no `subscription_id` of
 * its own — only `invoice_id` — so this reads the organization's full payment history; the page
 * filters it down client-side to the invoice ids `subscriptionInvoices` already resolved, the
 * same "resolve one hop further client-side" shape `organizations/details/api.ts` already uses
 * for names it cannot filter by server-side. */
export function organizationPayments(organizationId: string) {
  return listPayments({
    page: 1,
    pageSize: 100,
    sort: { field: "created_at", direction: "desc" },
    filters: { organization_id: organizationId },
    search: "",
  });
}

/** The plan catalogue — small and cached, mirrors `BillingPage.tsx`'s own `plansLookup`. */
export function planCatalog() {
  return listPlans({
    page: 1,
    pageSize: 100,
    sort: { field: "name", direction: "asc" },
    filters: {},
    search: "",
  });
}

/** This subscription's own lifecycle events — every domain event `Subscription` itself raised
 * (`SubscriptionOpened`/`Renewed`/`PastDue`/`GracePeriodExtended`/`Suspended`/`Reactivated`/
 * `Expired`/`Cancelled`), newest first. This is what "Status Timeline" and "Subscription Events"
 * both mean on this page: the same ordered fact list, since a subscription's status is entirely
 * a function of which of these events fired last. "Renewal History" is a filtered view of this
 * same list (`Opened`/`Renewed` only) — not a second query. */
export function subscriptionEvents(subscriptionId: string) {
  return listAuditEntries({
    page: 1,
    pageSize: 100,
    sort: { field: "created_at", direction: "desc" },
    filters: { entity_type: "Subscription", entity_id: subscriptionId },
    search: "",
  });
}

/** The organization's own broader audit feed — every recorded action against it, not only this
 * subscription's own lifecycle (invoices issued, payments recorded, and anything else touching
 * this tenant). Capped at the most recent 50 entries, the same disclosed cap
 * `AppShell`'s unread-notification badge already uses for an analogous "recent, not exhaustive"
 * feed. */
export function organizationAuditTimeline(organizationId: string) {
  return listAuditEntries({
    page: 1,
    pageSize: 50,
    sort: { field: "created_at", direction: "desc" },
    filters: { organization_id: organizationId },
    search: "",
  });
}
