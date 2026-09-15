import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CalendarClock,
  CreditCard,
  History,
  Info,
  Plus,
  ReceiptText,
  RefreshCcw,
  ShieldOff,
  Wallet,
} from "lucide-react";
import { Badge } from "../../../shared/components/Badge/Badge";
import { Button } from "../../../shared/components/Button/Button";
import { Card, CardBody, CardHeader } from "../../../shared/components/Card/Card";
import { ConfirmDialog } from "../../../shared/components/ConfirmDialog/ConfirmDialog";
import { EmptyState } from "../../../shared/components/EmptyState/EmptyState";
import { FormField } from "../../../shared/components/FormField/FormField";
import { Input } from "../../../shared/components/Input/Input";
import { Select } from "../../../shared/components/Select/Select";
import { Skeleton } from "../../../shared/components/Skeleton/Skeleton";
import { StatCard } from "../../../shared/components/StatCard/StatCard";
import { useToast } from "../../../shared/components/Toast/toastStore";
import { ApiError } from "../../../shared/api/types";
import { useAuthStore } from "../../../shared/stores/authStore";
import {
  activateSubscription,
  cancelSubscription,
  changeSubscriptionPlan,
  openOrCreateNextInvoice,
  recordManualSubscriptionPayment,
  type Invoice,
  type Subscription,
} from "../../billing/api";
import { formatAmount, formatDateOnly, formatDateTime } from "../../billing/format";
import {
  billingCycleLabel,
  invoiceStatusLabel,
  invoiceStatusTone,
  subscriptionStatusLabel,
  subscriptionStatusTone,
} from "../../billing/labels";
import { SubscriptionActions } from "../../billing/SubscriptionActions";
import type { Organization } from "../api";
import { trialStateLabel, trialStateTone } from "../labels";
import { orgPlanCatalog, orgSubscriptionInvoices, orgSubscriptions } from "./api";
import styles from "./OrganizationDetailsPage.module.css";
import type { StatCardTone } from "../../../shared/components/StatCard/StatCard";

/** `subscriptionStatusTone` returns a `BadgeVariant`, which has `"info"` where `StatCardTone`
 * has `"brand"` instead — the two enums are otherwise identical. */
function statusStatCardTone(status: Subscription["status"]): StatCardTone {
  const tone = subscriptionStatusTone(status);
  return tone === "info" ? "brand" : tone;
}

/** Non-terminal — a subscription in one of these statuses is "the current one" for the
 * organization; `cancelled`/`expired` never are, even if it's the most recently created row. */
const NON_TERMINAL: ReadonlySet<Subscription["status"]> = new Set([
  "trial",
  "active",
  "past_due",
  "grace_period",
  "suspended",
]);

/** Picks the subscription this panel treats as "current": the most recent non-terminal one, or
 * (for an organization with only ever-cancelled/expired history) the most recently created row,
 * so the panel still has something to show rather than pretending the organization never had
 * one. Mirrors `BillingApplicationService.get_active_by_organization`'s own "most relevant one"
 * reading, since the list endpoint returns every historical row, not just the live one. */
function pickCurrentSubscription(subscriptions: Subscription[]): Subscription | null {
  if (subscriptions.length === 0) return null;
  const nonTerminal = subscriptions.find((s) => NON_TERMINAL.has(s.status));
  return nonTerminal ?? subscriptions[0];
}

type PendingAction =
  | { kind: "create-subscription" }
  | { kind: "create-invoice" }
  | { kind: "record-payment"; invoice: Invoice }
  | { kind: "activate" }
  | { kind: "change-plan" }
  | { kind: "cancel" }
  | null;

export interface OrganizationSubscriptionPanelProps {
  organizationId: string;
  organization: Organization;
}

/**
 * The Subscription Control Center for one organization (Organization Management phase).
 *
 * A composition, exactly like `OrganizationTabPanel`'s other tabs: every read goes through a
 * client that already exists (`./api.ts`, `../../billing/api.ts`), and every action calls a real
 * backend endpoint — `billing.subscriptions.manage`/`billing.plans.manage`-gated, the same
 * platform-admin-only posture `SubscriptionActions.tsx` already established. No client-side
 * permission check substitutes for that gate; `canManage` below only decides what this component
 * renders, never what the server accepts.
 *
 * **"Create Subscription" and "Create Invoice" are one backend call** (`openOrCreateNextInvoice`,
 * `POST /billing/subscriptions`) shown as two differently-labelled buttons depending on whether a
 * non-terminal subscription already exists — see that function's own docstring.
 */
export function OrganizationSubscriptionPanel({
  organizationId,
  organization,
}: OrganizationSubscriptionPanelProps) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const principal = useAuthStore((s) => s.principal);
  const canManage = principal?.role === "founder" || principal?.role === "finance_staff";

  const [pending, setPending] = useState<PendingAction>(null);
  const [selectedPlanId, setSelectedPlanId] = useState("");
  const [paymentReference, setPaymentReference] = useState("");

  const subscriptionsQuery = useQuery({
    queryKey: ["organizations", "detail", organizationId, "subscriptions", "control-center"],
    queryFn: () => orgSubscriptions(organizationId),
    staleTime: 15_000,
  });

  const subscription = useMemo(
    () => pickCurrentSubscription(subscriptionsQuery.data?.data ?? []),
    [subscriptionsQuery.data],
  );

  const plansQuery = useQuery({
    queryKey: ["organizations", "detail", organizationId, "plan-catalog"],
    queryFn: orgPlanCatalog,
    staleTime: 60_000,
  });
  const plans = plansQuery.data?.data ?? [];
  const activePlans = plans.filter((p) => p.status === "active");
  const plan = useMemo(
    () => plans.find((p) => p.id === subscription?.planId) ?? null,
    [plans, subscription],
  );

  const invoicesQuery = useQuery({
    queryKey: ["organizations", "detail", organizationId, "subscriptions", subscription?.id, "invoices"],
    queryFn: () => orgSubscriptionInvoices(subscription!.id),
    enabled: Boolean(subscription),
    staleTime: 15_000,
  });
  const invoices = invoicesQuery.data?.data ?? [];
  const currentInvoice = invoices[0] ?? null;
  const historyInvoices = invoices.slice(1);

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ["organizations", "detail", organizationId] });
    void queryClient.invalidateQueries({ queryKey: ["billing"] });
  };

  const onError = (error: unknown) => {
    toast.error(
      "Action failed",
      error instanceof ApiError ? error.message : "The action could not be completed.",
    );
  };

  const closeDialog = () => {
    setPending(null);
    setSelectedPlanId("");
    setPaymentReference("");
  };

  const createInvoiceMutation = useMutation({
    mutationFn: (planId: string) => openOrCreateNextInvoice(organizationId, planId),
    onSuccess: (invoice) => {
      toast.success(
        subscription ? "Invoice created" : "Subscription opened",
        `Invoice ${invoice.number} — ${formatAmount(invoice.amount, invoice.currency)}.`,
      );
      invalidate();
      closeDialog();
    },
    onError,
  });

  const recordPaymentMutation = useMutation({
    mutationFn: ({ invoiceId, reference }: { invoiceId: string; reference: string }) =>
      recordManualSubscriptionPayment(invoiceId, reference || null),
    onSuccess: () => {
      toast.success("Payment recorded", "The invoice is now marked paid.");
      invalidate();
      closeDialog();
    },
    onError,
  });

  const activateMutation = useMutation({
    mutationFn: () => activateSubscription(subscription!.id),
    onSuccess: () => {
      toast.success("Subscription activated");
      invalidate();
      closeDialog();
    },
    onError,
  });

  const changePlanMutation = useMutation({
    mutationFn: (planId: string) => changeSubscriptionPlan(subscription!.id, planId),
    onSuccess: () => {
      toast.success(
        "Plan changed",
        "The current period and every already-issued invoice are unaffected — the new plan applies from the next invoice.",
      );
      invalidate();
      closeDialog();
    },
    onError,
  });

  const cancelMutation = useMutation({
    mutationFn: () => cancelSubscription(subscription!.id),
    onSuccess: () => {
      toast.success("Subscription cancelled");
      invalidate();
      closeDialog();
    },
    onError,
  });

  if (subscriptionsQuery.isPending || plansQuery.isPending) {
    return (
      <div className={styles.stack}>
        <Skeleton height={100} />
        <Skeleton height={200} />
      </div>
    );
  }

  if (subscriptionsQuery.isError) {
    return (
      <EmptyState
        icon={<Info size={20} />}
        title="Could not load the subscription"
        description={
          subscriptionsQuery.error instanceof ApiError
            ? subscriptionsQuery.error.message
            : "Something went wrong. Please try again."
        }
      />
    );
  }

  const isTerminal = subscription ? !NON_TERMINAL.has(subscription.status) : false;
  const canCreateSubscription = !subscription || isTerminal;
  const hasUnpaidInvoice = currentInvoice?.status === "issued";
  const canCreateInvoice = Boolean(subscription) && !isTerminal && !hasUnpaidInvoice;
  const canRecordPayment = hasUnpaidInvoice;
  const canActivate = subscription && !isTerminal && subscription.status !== "active";
  const canChangePlan = subscription && !isTerminal;
  const canCancel = subscription && !isTerminal;

  return (
    <div className={styles.stack}>
      {!subscription && (
        <EmptyState
          icon={<CreditCard size={20} />}
          title="No subscription"
          description="This organization has no RAAD subscription. Its users cannot open the dashboard until a plan is assigned."
        />
      )}

      {subscription && (
        <>
          <div className={styles.statGrid}>
            <StatCard
              icon={<CreditCard size={16} />}
              tone={statusStatCardTone(subscription.status)}
              label="Status"
              value={subscriptionStatusLabel(subscription.status)}
              meta={plan?.name ?? subscription.planId}
              metaTone="neutral"
              footnote={plan ? billingCycleLabel(plan.billingCycle) : undefined}
            />
            <StatCard
              icon={<Wallet size={16} />}
              tone="success"
              label="Amount"
              value={plan ? formatAmount(plan.amount, plan.currency) : "—"}
              footnote={plan ? billingCycleLabel(plan.billingCycle) : "Plan no longer in the catalogue"}
            />
            <StatCard
              icon={<CalendarClock size={16} />}
              tone="warning"
              label="Current period"
              value={
                subscription.currentPeriodStart && subscription.currentPeriodEnd
                  ? `${formatDateOnly(subscription.currentPeriodStart)} – ${formatDateOnly(subscription.currentPeriodEnd)}`
                  : "—"
              }
              footnote={subscription.autoRenew ? "Auto-renew on" : "Auto-renew off"}
            />
            <StatCard
              icon={<History size={16} />}
              tone="purple"
              label="Started"
              value={formatDateOnly(subscription.createdAt)}
              footnote={`Subscription ID: ${subscription.id}`}
            />
          </div>

          {(organization.trialStartedAt || organization.trialState !== "not_started") && (
            <div className={styles.notice}>
              <Info size={16} className={styles.noticeIcon} aria-hidden="true" />
              <p className={styles.noticeText}>
                Trial: <Badge variant={trialStateTone(organization.trialState)} dot>{trialStateLabel(organization.trialState)}</Badge>
                {organization.trialStartedAt && ` · Started ${formatDateOnly(organization.trialStartedAt)}`}
                {organization.trialEndsAt && ` · Ends ${formatDateOnly(organization.trialEndsAt)}`}
                {" — a permanent, separate concept from this subscription's own one-time \"trial\" status label (never re-entered, no duration of its own)."}
              </p>
            </div>
          )}
        </>
      )}

      {canManage && (
        <Card padded>
          <CardHeader title="Actions" subtitle="Platform-admin subscription lifecycle controls" />
          <div className={styles.actions}>
            {canCreateSubscription && (
              <Button leadingIcon={<Plus size={14} />} onClick={() => setPending({ kind: "create-subscription" })}>
                Create subscription
              </Button>
            )}
            {canCreateInvoice && (
              <Button leadingIcon={<ReceiptText size={14} />} onClick={() => setPending({ kind: "create-invoice" })}>
                Create invoice
              </Button>
            )}
            {canRecordPayment && currentInvoice && (
              <Button
                variant="secondary"
                leadingIcon={<Wallet size={14} />}
                onClick={() => setPending({ kind: "record-payment", invoice: currentInvoice })}
              >
                Record manual payment
              </Button>
            )}
            {canActivate && (
              <Button variant="secondary" onClick={() => setPending({ kind: "activate" })}>
                Activate
              </Button>
            )}
            {canChangePlan && (
              <Button
                variant="ghost"
                leadingIcon={<RefreshCcw size={14} />}
                onClick={() => setPending({ kind: "change-plan" })}
              >
                Change plan
              </Button>
            )}
            {subscription && !isTerminal && <SubscriptionActions subscription={subscription} />}
            {canCancel && (
              <Button
                variant="ghost"
                leadingIcon={<ShieldOff size={14} />}
                onClick={() => setPending({ kind: "cancel" })}
              >
                Cancel
              </Button>
            )}
          </div>
        </Card>
      )}

      {subscription && (
        <Card>
          <CardHeader
            icon={<ReceiptText size={18} />}
            title="Current invoice"
            action={
              <Link to={`/platform/billing/subscriptions/${subscription.id}`} className={styles.link}>
                View full subscription details →
              </Link>
            }
          />
          <CardBody>
            {invoicesQuery.isPending ? (
              <Skeleton height={18} />
            ) : invoicesQuery.isError ? (
              <EmptyState icon={<ReceiptText size={20} />} title="Could not load invoices" />
            ) : !currentInvoice ? (
              <EmptyState
                icon={<ReceiptText size={20} />}
                title="No invoice yet"
                description="No invoice has been issued against this subscription."
              />
            ) : (
              <dl className={styles.detail}>
                <div>
                  <dt>Number</dt>
                  <dd className={styles.mono}>{currentInvoice.number}</dd>
                </div>
                <div>
                  <dt>Amount</dt>
                  <dd>{formatAmount(currentInvoice.amount, currentInvoice.currency)}</dd>
                </div>
                <div>
                  <dt>Status</dt>
                  <dd>
                    <Badge variant={invoiceStatusTone(currentInvoice.status)} dot>
                      {invoiceStatusLabel(currentInvoice.status)}
                    </Badge>
                  </dd>
                </div>
                <div>
                  <dt>Period</dt>
                  <dd>
                    {formatDateOnly(currentInvoice.periodStart)} – {formatDateOnly(currentInvoice.periodEnd)}
                  </dd>
                </div>
                <div>
                  <dt>Issued</dt>
                  <dd>{currentInvoice.issuedAt ? formatDateTime(currentInvoice.issuedAt) : "—"}</dd>
                </div>
                <div>
                  <dt>Paid</dt>
                  <dd>{currentInvoice.paidAt ? formatDateTime(currentInvoice.paidAt) : "—"}</dd>
                </div>
              </dl>
            )}
          </CardBody>
        </Card>
      )}

      {subscription && historyInvoices.length > 0 && (
        <Card>
          <CardHeader icon={<History size={18} />} title="Invoice history" subtitle="Previously issued invoices" />
          <div className={styles.tableScroll}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>Number</th>
                  <th>Amount</th>
                  <th>Status</th>
                  <th>Period</th>
                  <th>Issued</th>
                </tr>
              </thead>
              <tbody>
                {historyInvoices.map((invoice) => (
                  <tr key={invoice.id}>
                    <td className={styles.mono}>{invoice.number}</td>
                    <td>{formatAmount(invoice.amount, invoice.currency)}</td>
                    <td>
                      <Badge variant={invoiceStatusTone(invoice.status)} dot>
                        {invoiceStatusLabel(invoice.status)}
                      </Badge>
                    </td>
                    <td>
                      {formatDateOnly(invoice.periodStart)} – {formatDateOnly(invoice.periodEnd)}
                    </td>
                    <td>{invoice.issuedAt ? formatDateOnly(invoice.issuedAt) : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {/* ---- Create subscription / Create invoice — one backend call, two entry points ---- */}
      <ConfirmDialog
        open={pending?.kind === "create-subscription" || pending?.kind === "create-invoice"}
        title={pending?.kind === "create-subscription" ? "Create a subscription" : "Create the next invoice"}
        description={
          pending?.kind === "create-subscription"
            ? "Opens a subscription for this organization and issues its first invoice."
            : `Issues the next invoice for the current plan (${plan?.name ?? subscription?.planId}).`
        }
        confirmLabel={pending?.kind === "create-subscription" ? "Create subscription" : "Create invoice"}
        loading={createInvoiceMutation.isPending}
        confirmDisabled={pending?.kind === "create-subscription" && !selectedPlanId}
        onConfirm={() =>
          createInvoiceMutation.mutate(
            pending?.kind === "create-subscription" ? selectedPlanId : (subscription?.planId ?? ""),
          )
        }
        onCancel={closeDialog}
      >
        {pending?.kind === "create-subscription" && (
          <FormField label="Plan">
            <Select value={selectedPlanId} onChange={(e) => setSelectedPlanId(e.target.value)}>
              <option value="">Select a plan…</option>
              {activePlans.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name} — {formatAmount(p.amount, p.currency)} ({billingCycleLabel(p.billingCycle)})
                </option>
              ))}
            </Select>
          </FormField>
        )}
      </ConfirmDialog>

      {/* ---- Record manual payment ---- */}
      <ConfirmDialog
        open={pending?.kind === "record-payment"}
        title="Record a manual payment"
        description={
          pending?.kind === "record-payment"
            ? `Marks invoice ${pending.invoice.number} (${formatAmount(pending.invoice.amount, pending.invoice.currency)}) as paid. Use this for money received outside Stripe — a bank transfer, for example.`
            : undefined
        }
        confirmLabel="Record payment"
        loading={recordPaymentMutation.isPending}
        onConfirm={() =>
          pending?.kind === "record-payment" &&
          recordPaymentMutation.mutate({ invoiceId: pending.invoice.id, reference: paymentReference })
        }
        onCancel={closeDialog}
      >
        <FormField label="Reference (optional)" hint="e.g. a bank transfer reference or receipt number">
          <Input value={paymentReference} onChange={(e) => setPaymentReference(e.target.value)} />
        </FormField>
      </ConfirmDialog>

      {/* ---- Activate ---- */}
      <ConfirmDialog
        open={pending?.kind === "activate"}
        title="Activate this subscription?"
        description="Moves the subscription to Active. Refused if any invoice is still unpaid."
        confirmLabel="Activate"
        loading={activateMutation.isPending}
        onConfirm={() => activateMutation.mutate()}
        onCancel={closeDialog}
      />

      {/* ---- Change plan ---- */}
      <ConfirmDialog
        open={pending?.kind === "change-plan"}
        title="Change the plan"
        description="The current billing period and every already-issued invoice are unaffected — the new plan's price and cycle apply starting with the next invoice."
        confirmLabel="Change plan"
        loading={changePlanMutation.isPending}
        confirmDisabled={!selectedPlanId}
        onConfirm={() => changePlanMutation.mutate(selectedPlanId)}
        onCancel={closeDialog}
      >
        <FormField label="New plan">
          <Select value={selectedPlanId} onChange={(e) => setSelectedPlanId(e.target.value)}>
            <option value="">Select a plan…</option>
            {activePlans
              .filter((p) => p.id !== subscription?.planId)
              .map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name} — {formatAmount(p.amount, p.currency)} ({billingCycleLabel(p.billingCycle)})
                </option>
              ))}
          </Select>
        </FormField>
      </ConfirmDialog>

      {/* ---- Cancel ---- */}
      <ConfirmDialog
        open={pending?.kind === "cancel"}
        tone="danger"
        title="Cancel this subscription?"
        description="This is a terminal transition — there is no reactivation path back from Cancelled. A new subscription would have to be opened from scratch."
        confirmLabel="Cancel subscription"
        loading={cancelMutation.isPending}
        onConfirm={() => cancelMutation.mutate()}
        onCancel={closeDialog}
      />
    </div>
  );
}
