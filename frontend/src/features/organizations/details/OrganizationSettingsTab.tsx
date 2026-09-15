import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Info } from "lucide-react";
import { Badge } from "../../../shared/components/Badge/Badge";
import { Button } from "../../../shared/components/Button/Button";
import { ConfirmDialog } from "../../../shared/components/ConfirmDialog/ConfirmDialog";
import { FormField } from "../../../shared/components/FormField/FormField";
import { Input } from "../../../shared/components/Input/Input";
import { useToast } from "../../../shared/components/Toast/toastStore";
import { ApiError } from "../../../shared/api/types";
import {
  renameOrganization,
  updateOrganizationStatus,
  type Organization,
  type OrganizationStatus,
} from "../api";
import { orgTypeLabel, statusLabel, statusTone } from "../labels";
import type { OrganizationDetailTabId } from "./tabs";
import styles from "./OrganizationDetailsPage.module.css";

/**
 * Organization Settings, reorganized into named sections (Organization Management phase):
 * **General** (the one identity field with real backend support), **Billing** (a link to the
 * Subscription Control Center — settings for a subscription live there, not duplicated here),
 * **Lifecycle** (the pre-existing status transitions, unchanged, framed as "Deactivate
 * (Archive)" per this phase's own delete-safety finding: no hard-delete capability exists or is
 * added — see `OrganizationSubscriptionPanel`/this file's own git history for the full
 * reasoning). Localization/Branding/Notifications sections are **not built** — no backend field
 * exists for any of them (confirmed by exhaustive grep before this phase), disclosed here rather
 * than silently omitted.
 *
 * **Only controls that persist via a real backend endpoint are ever shown.** `PATCH
 * /organizations/{id}` accepts exactly `status` and (as of this phase) `name` — `region_id`/
 * `org_type`/`parent_org_id`/`billing_model` (the last removed outright by ADR-0016) all remain
 * unofferable, and the notice below says so rather than rendering a control guaranteed to fail.
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
    label: "Deactivate (Archive)",
    tone: "danger",
    confirm:
      "The organization is archived: marked inactive, and its data is retained in full — nothing is deleted. This is the safe alternative to deletion this platform offers; no hard-delete capability exists for an organization with any operational or financial history.",
  },
];

export function OrganizationSettingsTab({
  organization,
  onSelectTab,
}: {
  organization: Organization;
  onSelectTab: (tab: OrganizationDetailTabId) => void;
}) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [pending, setPending] = useState<OrganizationStatus | null>(null);
  const [nameDraft, setNameDraft] = useState(organization.name);

  const statusMutation = useMutation({
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

  const renameMutation = useMutation({
    mutationFn: (name: string) => renameOrganization(organization.id, name),
    onSuccess: (updated) => {
      queryClient.invalidateQueries({ queryKey: ["organizations"] });
      toast.success("Name updated", `This organization is now named ${updated.name}.`);
    },
    onError: (error) => {
      toast.error(
        "Could not rename the organization",
        error instanceof ApiError ? error.message : "Something went wrong. Please try again.",
      );
    },
  });

  const available = TRANSITIONS.filter((t) => t.target !== organization.status);
  const chosen = TRANSITIONS.find((t) => t.target === pending) ?? null;
  const trimmedDraft = nameDraft.trim();
  const nameChanged = trimmedDraft.length > 0 && trimmedDraft !== organization.name;

  return (
    <div className={styles.stack}>
      <section>
        <h3 className={styles.sectionTitle}>General</h3>
        <FormField label="Organization name">
          <div className={styles.actions}>
            <Input
              value={nameDraft}
              onChange={(e) => setNameDraft(e.target.value)}
              style={{ flex: 1, minWidth: 220 }}
            />
            <Button
              size="sm"
              disabled={!nameChanged}
              loading={renameMutation.isPending}
              onClick={() => renameMutation.mutate(trimmedDraft)}
            >
              Save
            </Button>
          </div>
        </FormField>
        <dl className={styles.detail}>
          <div>
            <dt>Type</dt>
            <dd>{orgTypeLabel(organization.orgType)}</dd>
          </div>
          <div>
            <dt>Region</dt>
            <dd className={styles.mono}>{organization.regionId}</dd>
          </div>
        </dl>
        <div className={styles.notice}>
          <Info size={16} className={styles.noticeIcon} aria-hidden="true" />
          <p className={styles.noticeText}>
            Name is the only identity field this backend can persist a change to. Type and region
            are set once at onboarding and have no edit endpoint — <code>Organization</code>'s own
            domain model deliberately keeps them constructor-set-only, so no control for either is
            offered here rather than one that would always fail. Contact details, address,
            timezone, currency and branding have no backend field at all yet — a separate,
            larger initiative, not silently dropped from this one.
          </p>
        </div>
      </section>

      <section>
        <h3 className={styles.sectionTitle}>Billing</h3>
        <p className={styles.muted}>
          Plan, billing cycle, invoices and payment actions live on the Subscription tab — they
          are not duplicated here.
        </p>
        <Button variant="secondary" size="sm" onClick={() => onSelectTab("subscription")}>
          Open Subscription →
        </Button>
      </section>

      <section>
        <h3 className={styles.sectionTitle}>Lifecycle</h3>
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
              disabled={statusMutation.isPending}
            >
              {transition.label}
            </Button>
          ))}
        </div>

        <div className={styles.notice}>
          <Info size={16} className={styles.noticeIcon} aria-hidden="true" />
          <p className={styles.noticeText}>
            "Deactivate (Archive)" is the safe alternative to deletion on this platform — it marks
            the organization inactive and retains every record. No hard-delete exists for an
            organization: its data is referenced by other modules (users, vehicles, invoices) that
            are not database-enforced foreign keys across module boundaries, so deleting the row
            outright would silently orphan them. Suspending or deactivating an organization does
            not change its RAAD subscription — suspend that separately on the Subscription tab.
          </p>
        </div>
      </section>

      <ConfirmDialog
        open={chosen !== null}
        title={chosen ? `${chosen.label} ${organization.name}?` : ""}
        description={chosen?.confirm}
        confirmLabel={chosen?.label}
        tone={chosen?.tone ?? "primary"}
        loading={statusMutation.isPending}
        onConfirm={() => chosen && statusMutation.mutate(chosen.target)}
        onCancel={() => setPending(null)}
      />
    </div>
  );
}
