import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Info } from "lucide-react";
import { Badge } from "../../../shared/components/Badge/Badge";
import { Button } from "../../../shared/components/Button/Button";
import { ConfirmDialog } from "../../../shared/components/ConfirmDialog/ConfirmDialog";
import { useToast } from "../../../shared/components/Toast/toastStore";
import { ApiError } from "../../../shared/api/types";
import {
  updateOrganizationStatus,
  type Organization,
  type OrganizationStatus,
} from "../api";
import { statusLabel, statusTone } from "../labels";
import styles from "./OrganizationDetailsPage.module.css";

/**
 * Lifecycle actions for one organization.
 *
 * **Only the transitions the backend actually exposes.** `PATCH /organizations/{id}` accepts a
 * status change and nothing else — `billing_model` was removed outright by ADR-0016, and no
 * route exists to rename an organization or move it between regions. Rendering fields for those
 * would be offering controls guaranteed to fail, which this codebase treats as a defect in its
 * own right ("fail loudly, don't fake it", extended from data to affordances).
 *
 * **Deactivating an organization is not the same as suspending its subscription**, and the copy
 * says so: one is the tenant's own lifecycle, the other is billing. Conflating them is how an
 * operator suspends the wrong thing.
 */

const TRANSITIONS: {
  target: OrganizationStatus;
  label: string;
  tone: "primary" | "danger";
  confirm: string;
}[] = [
  {
    target: "active",
    label: "Reactivate",
    tone: "primary",
    confirm:
      "The organization becomes usable again. This does not change its RAAD subscription — if that is suspended or expired, its users still cannot open the dashboard.",
  },
  {
    target: "suspended",
    label: "Suspend",
    tone: "danger",
    confirm:
      "The organization is marked suspended. This is the tenant's own lifecycle, separate from its RAAD subscription — suspend the subscription on the Subscription tab if the intent is to stop access for non-payment.",
  },
  {
    target: "inactive",
    label: "Deactivate",
    tone: "danger",
    confirm:
      "The organization is marked inactive. Its data is retained and nothing is deleted; the organization simply stops being treated as live.",
  },
];

export function OrganizationSettingsTab({ organization }: { organization: Organization }) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [pending, setPending] = useState<OrganizationStatus | null>(null);

  const mutation = useMutation({
    mutationFn: (status: OrganizationStatus) =>
      updateOrganizationStatus(organization.id, status),
    onSuccess: (updated) => {
      queryClient.invalidateQueries({ queryKey: ["organizations"] });
      toast.success(
        "Organization updated",
        `${updated.name} is now ${statusLabel(updated.status).toLowerCase()}.`,
      );
      setPending(null);
    },
    onError: (error) => {
      toast.error(
        "Could not update the organization",
        error instanceof ApiError ? error.message : "Something went wrong. Please try again.",
      );
    },
  });

  const available = TRANSITIONS.filter((t) => t.target !== organization.status);
  const chosen = TRANSITIONS.find((t) => t.target === pending) ?? null;

  return (
    <div className={styles.stack}>
      <dl className={styles.detail}>
        <div>
          <dt>Current status</dt>
          <dd>
            <Badge variant={statusTone(organization.status)} dot>
              {statusLabel(organization.status)}
            </Badge>
          </dd>
        </div>
      </dl>

      <div className={styles.actions}>
        {available.map((transition) => (
          <Button
            key={transition.target}
            variant={transition.tone === "danger" ? "secondary" : "primary"}
            onClick={() => setPending(transition.target)}
            disabled={mutation.isPending}
          >
            {transition.label}
          </Button>
        ))}
      </div>

      <div className={styles.notice}>
        <Info size={16} className={styles.noticeIcon} aria-hidden="true" />
        <p className={styles.noticeText}>
          Status is the only editable field here, because it is the only one the API accepts.
          Renaming an organization or moving it to another region has no endpoint — those would be
          controls that always fail, so they are not offered.
        </p>
      </div>

      <ConfirmDialog
        open={chosen !== null}
        title={chosen ? `${chosen.label} ${organization.name}?` : ""}
        description={chosen?.confirm}
        confirmLabel={chosen?.label}
        tone={chosen?.tone ?? "primary"}
        loading={mutation.isPending}
        onConfirm={() => chosen && mutation.mutate(chosen.target)}
        onCancel={() => setPending(null)}
      />
    </div>
  );
}
