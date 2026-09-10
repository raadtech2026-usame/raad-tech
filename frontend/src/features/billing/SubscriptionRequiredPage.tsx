import { useMemo } from "react";
import clsx from "clsx";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, CreditCard, LifeBuoy, ReceiptText } from "lucide-react";
import { Badge } from "../../shared/components/Badge/Badge";
import { Button } from "../../shared/components/Button/Button";
import { Card, CardBody, CardHeader } from "../../shared/components/Card/Card";
import { EmptyState } from "../../shared/components/EmptyState/EmptyState";
import { LoadingScreen } from "../../shared/components/LoadingScreen/LoadingScreen";
import { useAuthStore } from "../../shared/stores/authStore";
import {
  getCurrentSubscription,
  listInvoices,
  listPlans,
  type Invoice,
  type SubscriptionStatus,
} from "./api";
import { invoiceStatusLabel, invoiceStatusTone, subscriptionStatusLabel } from "./labels";
import { formatAmount, formatDateOnly } from "./format";
import styles from "./SubscriptionRequiredPage.module.css";

/**
 * The page a blocked organization lands on instead of its dashboard (ADR-0039, amended
 * 2026-09-09).
 *
 * **Reachable precisely because `/billing/*` is exempt from the server-side subscription
 * guard.** That exemption is what stops suspension being a trap: an Org Admin who cannot reach
 * billing can never pay, so the block would be permanent and self-sealing. Every read on this
 * page therefore succeeds even while every other route is refused.
 *
 * **Two different situations, two different pages' worth of copy.** A subscription that lapsed
 * is something the school can fix by paying. An organization that never had a subscription at
 * all is a provisioning problem only RAAD can fix, and telling a bursar to "renew" would send
 * them looking for a button that cannot help them. The server distinguishes them
 * (`ORGANIZATION_SUBSCRIPTION_INACTIVE` vs `..._MISSING`); this page reads the subscription
 * itself and does the same.
 *
 * Non-admin tenant users (Driver, Parent — mobile-only on the web, but reachable) get the
 * status and nothing else: a driver has no business reading their school's billing position,
 * which is the same graded disclosure `subscription_guard._details_for` applies server-side.
 */

const LIST_PARAMS = { page: 1, pageSize: 25, sort: null, filters: {}, search: "" };

/** Statuses that mean "this was sold and then lapsed", as opposed to never sold at all. */
const LAPSED: ReadonlySet<string> = new Set<SubscriptionStatus>([
  "past_due",
  "suspended",
  "expired",
  "cancelled",
]);

function outstandingFirst(invoices: Invoice[]): Invoice[] {
  const rank = (invoice: Invoice) => (invoice.status === "issued" ? 0 : 1);
  return [...invoices].sort((a, b) => rank(a) - rank(b) || b.periodEnd.localeCompare(a.periodEnd));
}

export function SubscriptionRequiredPage() {
  const principal = useAuthStore((s) => s.principal);
  const isOrgAdmin = principal?.role === "org_admin";

  const subscription = useQuery({
    queryKey: ["subscription-gate", principal?.organizationId ?? null],
    queryFn: getCurrentSubscription,
    staleTime: 30_000,
  });

  // Only an Org Admin is shown money. Both reads are on the exempt `/billing` prefix, so they
  // resolve even though the rest of the API is refusing this caller.
  const invoices = useQuery({
    queryKey: ["subscription-required", "invoices"],
    queryFn: () => listInvoices(LIST_PARAMS),
    enabled: isOrgAdmin,
    staleTime: 30_000,
  });
  const plans = useQuery({
    queryKey: ["subscription-required", "plans"],
    queryFn: () => listPlans(LIST_PARAMS),
    enabled: isOrgAdmin && subscription.data !== null,
    staleTime: 5 * 60_000,
  });

  const plan = useMemo(() => {
    if (!subscription.data) return null;
    return (plans.data?.data ?? []).find((p) => p.id === subscription.data?.planId) ?? null;
  }, [plans.data, subscription.data]);

  const dueInvoice = useMemo(() => {
    const rows = outstandingFirst(invoices.data?.data ?? []);
    return rows.find((row) => row.status === "issued") ?? rows[0] ?? null;
  }, [invoices.data]);

  if (subscription.isPending) {
    return <LoadingScreen label="Checking your subscription…" />;
  }

  const status = subscription.data?.status ?? null;
  const neverSubscribed = subscription.data === null;
  const lapsed = status !== null && LAPSED.has(status);

  return (
    <div className={clsx(styles.page, "raad-view-transition")}>
      <Card className={styles.hero}>
        <CardBody>
          <span className={styles.heroIcon}>
            <AlertTriangle size={26} aria-hidden="true" />
          </span>
          <h1 className={styles.heroTitle}>
            {neverSubscribed
              ? "No subscription assigned"
              : "Your subscription needs attention"}
          </h1>
          <p className={styles.heroBody}>
            {neverSubscribed ? (
              <>
                Your organization does not have a RAAD subscription yet, so the dashboard is not
                available. A plan has to be assigned by RAAD before your school can use the
                platform — contact RAAD support and they will set it up.
              </>
            ) : (
              <>
                Access to the dashboard is paused until your subscription is back in good
                standing. Everything below is what your school needs to settle it. Your data is
                untouched and returns the moment payment is confirmed.
              </>
            )}
          </p>
          {status && (
            <div className={styles.heroStatus}>
              <span>Subscription status</span>
              <Badge variant={lapsed ? "danger" : "warning"} dot>
                {subscriptionStatusLabel(status)}
              </Badge>
            </div>
          )}
        </CardBody>
      </Card>

      {!isOrgAdmin ? (
        <Card>
          <CardBody>
            <p className={styles.note}>
              Please contact your organization administrator — they can see the billing details
              and settle the account.
            </p>
          </CardBody>
        </Card>
      ) : (
        <div className={styles.grid}>
          <Card>
            <CardHeader
              icon={<CreditCard size={18} />}
              title="Current plan"
              subtitle={neverSubscribed ? "None assigned" : "What your school subscribes to"}
            />
            <CardBody>
              {neverSubscribed ? (
                <p className={styles.note}>
                  No plan has been assigned to your organization.
                </p>
              ) : (
                <dl className={styles.detail}>
                  <div>
                    <dt>Plan</dt>
                    <dd>{plan ? plan.name : "—"}</dd>
                  </div>
                  <div>
                    <dt>Price</dt>
                    <dd>
                      {plan
                        ? `${formatAmount(plan.amount, plan.currency)} / ${plan.billingCycle}`
                        : "—"}
                    </dd>
                  </div>
                  <div>
                    <dt>Period ends</dt>
                    <dd>
                      {subscription.data?.currentPeriodEnd
                        ? formatDateOnly(subscription.data.currentPeriodEnd)
                        : "—"}
                    </dd>
                  </div>
                  {subscription.data?.gracePeriodEndsAt && (
                    <div>
                      <dt>Grace ends</dt>
                      <dd>{formatDateOnly(subscription.data.gracePeriodEndsAt)}</dd>
                    </div>
                  )}
                </dl>
              )}
            </CardBody>
          </Card>

          <Card>
            <CardHeader
              icon={<ReceiptText size={18} />}
              title="Amount due"
              subtitle="The invoice that needs settling"
            />
            {invoices.isPending ? (
              <CardBody>
                <p className={styles.note}>Loading invoices…</p>
              </CardBody>
            ) : dueInvoice ? (
              <CardBody>
                <p className={styles.amount}>
                  {formatAmount(dueInvoice.amount, dueInvoice.currency)}
                </p>
                <dl className={styles.detail}>
                  <div>
                    <dt>Invoice</dt>
                    <dd className={styles.mono}>{dueInvoice.number}</dd>
                  </div>
                  <div>
                    <dt>Status</dt>
                    <dd>
                      <Badge variant={invoiceStatusTone(dueInvoice.status)} dot>
                        {invoiceStatusLabel(dueInvoice.status)}
                      </Badge>
                    </dd>
                  </div>
                  <div>
                    <dt>Due</dt>
                    <dd>{dueInvoice.dueAt ? formatDateOnly(dueInvoice.dueAt) : "On receipt"}</dd>
                  </div>
                  <div>
                    <dt>Period</dt>
                    <dd>
                      {formatDateOnly(dueInvoice.periodStart)} –{" "}
                      {formatDateOnly(dueInvoice.periodEnd)}
                    </dd>
                  </div>
                </dl>
              </CardBody>
            ) : (
              <EmptyState
                icon={<ReceiptText size={20} />}
                title="No invoice outstanding"
                description="Nothing is currently billed to your organization. If access is still paused, contact RAAD support."
              />
            )}
          </Card>
        </div>
      )}

      <Card>
        <CardHeader
          icon={<LifeBuoy size={18} />}
          title="How to restore access"
          subtitle={neverSubscribed ? "RAAD assigns your plan" : "Settle the invoice above"}
        />
        <CardBody>
          <ol className={styles.steps}>
            {neverSubscribed ? (
              <>
                <li>Contact RAAD support and ask for a plan to be assigned to your school.</li>
                <li>RAAD assigns the plan and your first invoice is issued automatically.</li>
                <li>Settle the invoice; the dashboard opens as soon as payment is confirmed.</li>
              </>
            ) : (
              <>
                <li>Pay the invoice above using the payment method agreed with RAAD.</li>
                <li>
                  Payment is confirmed automatically once your provider notifies RAAD — no
                  further action is needed on your side.
                </li>
                <li>
                  Your subscription returns to active and the dashboard reopens immediately. No
                  data is lost while access is paused.
                </li>
              </>
            )}
          </ol>
          <div className={styles.actions}>
            {/* Deliberately a reload rather than a client-side navigation: the gate is a cached
                query, and re-checking it from scratch is exactly what an operator who has just
                paid wants this button to do. */}
            <Button onClick={() => window.location.reload()}>
              I have paid — re-check
            </Button>
          </div>
          <p className={styles.footnote}>
            Access is enforced by RAAD's servers, not by this page. Nothing here can be bypassed
            from the browser.
          </p>
        </CardBody>
      </Card>
    </div>
  );
}
