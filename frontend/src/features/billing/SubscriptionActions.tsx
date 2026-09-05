import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Button } from "../../shared/components/Button/Button";
import { ConfirmDialog } from "../../shared/components/ConfirmDialog/ConfirmDialog";
import { FormField } from "../../shared/components/FormField/FormField";
import { Input } from "../../shared/components/Input/Input";
import { useToast } from "../../shared/components/Toast/toastStore";
import { ApiError } from "../../shared/api/types";
import {
  extendGracePeriod,
  reactivateSubscription,
  suspendSubscription,
  type Subscription,
} from "./api";
import styles from "./SubscriptionActions.module.css";

/** ADR-0039 §5 lifecycle actions, platform-admin only.
 *
 * These three are gated on `billing.subscriptions.manage`, which `org_admin` deliberately does
 * NOT hold - a school cannot lift its own suspension. The server is the real gate; rendering the
 * buttons only for eligible roles is presentation of that, never a second authorization system
 * (`.claude/rules/frontend.md` #2).
 *
 * Which action is offered depends on the state, because the domain rejects the others: a
 * suspended subscription can only be reactivated, and grace can only be extended for one that is
 * actually in a grace-bearing state. Offering a control that is guaranteed to 400 is the same
 * "don't offer an affordance that cannot work" posture `features/billing/api.ts` already took by
 * shipping no client function for an unbound payment provider.
 */

type PendingAction = "suspend" | "reactivate" | "extend" | null;

/** `past_due` and `grace_period` are the two states where extending grace is meaningful: the
 * first is the automatic window running, the second one an admin already extended. */
const GRACE_EXTENDABLE: ReadonlySet<Subscription["status"]> = new Set(["past_due", "grace_period"]);

/** Everything except an already-suspended or terminal subscription can be suspended. */
const SUSPENDABLE: ReadonlySet<Subscription["status"]> = new Set([
  "trial",
  "active",
  "past_due",
  "grace_period",
]);

export interface SubscriptionActionsProps {
  subscription: Subscription;
}

export function SubscriptionActions({ subscription }: SubscriptionActionsProps) {
  const [pending, setPending] = useState<PendingAction>(null);
  const [graceEndsAt, setGraceEndsAt] = useState("");
  const queryClient = useQueryClient();
  const toast = useToast();

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ["billing", "subscriptions"] });
  };

  const onError = (error: unknown) => {
    // The backend's own DomainError message is the real explanation of why a transition was
    // refused, so it is surfaced verbatim rather than replaced with a generic string.
    toast.error(
      "Action failed",
      error instanceof ApiError ? error.message : "The action could not be completed.",
    );
  };

  const suspend = useMutation({
    mutationFn: () => suspendSubscription(subscription.id),
    onSuccess: () => {
      toast.success("Subscription suspended");
      invalidate();
      setPending(null);
    },
    onError,
  });

  const reactivate = useMutation({
    mutationFn: () => reactivateSubscription(subscription.id),
    onSuccess: () => {
      toast.success("Subscription reactivated");
      invalidate();
      setPending(null);
    },
    onError,
  });

  const extend = useMutation({
    // `datetime-local` yields a naive local string; the API takes an absolute instant, so it is
    // converted here rather than sent ambiguously.
    mutationFn: () => extendGracePeriod(subscription.id, new Date(graceEndsAt).toISOString()),
    onSuccess: () => {
      toast.success("Grace period extended");
      invalidate();
      setPending(null);
      setGraceEndsAt("");
    },
    onError,
  });

  const canSuspend = SUSPENDABLE.has(subscription.status);
  const canReactivate = subscription.status === "suspended";
  const canExtend = GRACE_EXTENDABLE.has(subscription.status);

  if (!canSuspend && !canReactivate && !canExtend) {
    // Expired or cancelled: nothing to do from here, and an inert row of disabled buttons would
    // only invite a click that cannot succeed.
    return <span className={styles.none}>—</span>;
  }

  return (
    <div className={styles.actions}>
      {canSuspend && (
        <Button variant="ghost" size="sm" onClick={() => setPending("suspend")}>
          Suspend
        </Button>
      )}
      {canReactivate && (
        <Button variant="ghost" size="sm" onClick={() => setPending("reactivate")}>
          Reactivate
        </Button>
      )}
      {canExtend && (
        <Button variant="ghost" size="sm" onClick={() => setPending("extend")}>
          Extend grace
        </Button>
      )}

      <ConfirmDialog
        open={pending === "suspend"}
        tone="danger"
        title="Suspend this subscription?"
        description="Every user in this organization loses access immediately - staff, drivers and parents, not just the admin. Safety-critical tracking is unaffected."
        confirmLabel="Suspend"
        loading={suspend.isPending}
        onConfirm={() => suspend.mutate()}
        onCancel={() => setPending(null)}
      />

      <ConfirmDialog
        open={pending === "reactivate"}
        tone="primary"
        title="Reactivate this subscription?"
        description="Access is restored for every user in this organization."
        confirmLabel="Reactivate"
        loading={reactivate.isPending}
        onConfirm={() => reactivate.mutate()}
        onCancel={() => setPending(null)}
      />

      <ConfirmDialog
        open={pending === "extend"}
        tone="primary"
        title="Extend the grace period"
        description="The organization keeps full access until this moment. Recorded as an explicit, audited decision rather than a silent date change."
        confirmLabel="Extend"
        loading={extend.isPending}
        confirmDisabled={graceEndsAt === ""}
        onConfirm={() => extend.mutate()}
        onCancel={() => {
          setPending(null);
          setGraceEndsAt("");
        }}
      >
        <FormField label="Grace period ends at">
          <Input
            type="datetime-local"
            value={graceEndsAt}
            onChange={(event) => setGraceEndsAt(event.target.value)}
          />
        </FormField>
      </ConfirmDialog>
    </div>
  );
}
