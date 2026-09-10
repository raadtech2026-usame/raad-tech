import { useEffect } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Layers } from "lucide-react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { Button } from "../../shared/components/Button/Button";
import { FormDrawer } from "../../shared/components/Drawer/FormDrawer";
import { FormField } from "../../shared/components/FormField/FormField";
import { Input } from "../../shared/components/Input/Input";
import { Select } from "../../shared/components/Select/Select";
import { useToast } from "../../shared/components/Toast/toastStore";
import { ApiError } from "../../shared/api/types";
import { createPlan, updatePlan, type BillingCycle, type Plan } from "./api";
import styles from "./PlanForm.module.css";

/**
 * Create or edit a subscription plan (ADR-0040 §4) — Founder-only, behind `billing.plans.manage`.
 *
 * **Monthly and annual are two rows sharing a name, not one row with two prices.**
 * `billingCycle` drives every period date a subscription computes, so a single row carrying both
 * would make "which amount applies" ambiguous at invoice-issue time. A commercial tier billed
 * both ways is therefore created twice, and the catalogue groups by name to present it as one.
 * That is why the cycle is fixed after creation and this form hides it when editing — changing a
 * live subscription's cycle would silently move its renewal date.
 *
 * **Editing a plan is not retroactive.** Invoices capture their own amount at issue time, so a
 * price change applies from the next issuance onward. There is deliberately no "apply to
 * existing subscriptions" control, because the backend has no such operation to offer.
 */

const schema = z.object({
  name: z.string().trim().min(1, "Name is required").max(160),
  amount: z
    .string()
    .min(1, "Amount is required")
    .refine((value) => /^\d{1,13}(\.\d{1,2})?$/.test(value), {
      message: "Use a decimal amount, e.g. 199.00",
    }),
  currency: z.string().length(3, "Use a 3-letter currency code"),
  billingCycle: z.enum(["monthly", "quarterly", "annual"]),
  vehicleLimit: z.string(),
  deviceLimit: z.string(),
  userLimit: z.string(),
});

type FormValues = z.infer<typeof schema>;

/** Blank means unlimited — the shape the backend uses (`null`) for an Enterprise tier. */
function toLimit(value: string): number | null {
  return value.trim() === "" ? null : Number(value);
}

function fromLimit(value: number | null): string {
  return value === null ? "" : String(value);
}

export interface PlanFormProps {
  open: boolean;
  onClose: () => void;
  /** `null` creates a new plan; a plan edits it in place. */
  plan: Plan | null;
}

export function PlanForm({ open, onClose, plan }: PlanFormProps) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const isEdit = plan !== null;

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      name: "",
      amount: "",
      currency: "USD",
      billingCycle: "monthly",
      vehicleLimit: "",
      deviceLimit: "",
      userLimit: "",
    },
  });

  useEffect(() => {
    if (!open) return;
    reset(
      plan
        ? {
            name: plan.name,
            amount: plan.amount.toFixed(2),
            currency: plan.currency,
            billingCycle: plan.billingCycle,
            vehicleLimit: fromLimit(plan.vehicleLimit),
            deviceLimit: fromLimit(plan.deviceLimit),
            userLimit: fromLimit(plan.userLimit),
          }
        : {
            name: "",
            amount: "",
            currency: "USD",
            billingCycle: "monthly",
            vehicleLimit: "",
            deviceLimit: "",
            userLimit: "",
          },
    );
  }, [open, plan, reset]);

  const mutation = useMutation({
    mutationFn: (values: FormValues) => {
      const common = {
        name: values.name,
        amount: Number(values.amount),
        currency: values.currency.toUpperCase(),
        vehicleLimit: toLimit(values.vehicleLimit),
        deviceLimit: toLimit(values.deviceLimit),
        userLimit: toLimit(values.userLimit),
      };
      return plan
        ? updatePlan(plan.id, common)
        : createPlan({ ...common, billingCycle: values.billingCycle as BillingCycle });
    },
    onSuccess: (saved) => {
      queryClient.invalidateQueries({ queryKey: ["billing", "plans"] });
      toast.success(
        isEdit ? "Plan updated" : "Plan created",
        isEdit
          ? `${saved.name} applies from the next invoice issued — bills already sent keep their own amounts.`
          : `${saved.name} can now be selected when onboarding an organization.`,
      );
      onClose();
    },
    onError: (error) => {
      toast.error(
        isEdit ? "Could not update the plan" : "Could not create the plan",
        error instanceof ApiError ? error.message : "Something went wrong. Please try again.",
      );
    },
  });

  function handleClose(): void {
    if (mutation.isPending) return;
    onClose();
  }

  return (
    <FormDrawer
      open={open}
      onClose={handleClose}
      icon={<Layers size={18} />}
      iconTint="var(--color-brand-primary-tint)"
      iconColor="var(--color-brand-primary)"
      title={isEdit ? "Edit plan" : "New plan"}
      subtitle={
        isEdit
          ? "Applies from the next invoice — issued bills are unchanged"
          : "A commercial tier organizations subscribe to"
      }
      footer={
        <>
          <Button variant="ghost" onClick={handleClose} disabled={mutation.isPending}>
            Cancel
          </Button>
          <Button type="submit" form="plan-form" loading={mutation.isPending}>
            {isEdit ? "Save changes" : "Create plan"}
          </Button>
        </>
      }
    >
      <form
        id="plan-form"
        className={styles.form}
        onSubmit={handleSubmit((values) => mutation.mutate(values))}
      >
        <FormField
          label="Name"
          hint="Monthly and annual rows of the same tier share a name and are grouped in the catalogue."
          error={errors.name?.message}
        >
          <Input {...register("name")} placeholder="Standard" invalid={Boolean(errors.name)} autoFocus />
        </FormField>

        <div className={styles.row}>
          <FormField label="Amount per period" error={errors.amount?.message}>
            <Input
              {...register("amount")}
              inputMode="decimal"
              placeholder="199.00"
              invalid={Boolean(errors.amount)}
            />
          </FormField>
          <FormField label="Currency" error={errors.currency?.message}>
            <Input {...register("currency")} maxLength={3} invalid={Boolean(errors.currency)} />
          </FormField>
        </div>

        {!isEdit && (
          <FormField
            label="Billing cycle"
            hint="Fixed once created — it drives every renewal date a subscription computes."
            error={errors.billingCycle?.message}
          >
            <Select {...register("billingCycle")}>
              <option value="monthly">Monthly</option>
              <option value="quarterly">Quarterly</option>
              <option value="annual">Annual</option>
            </Select>
          </FormField>
        )}

        <p className={styles.limitsNote}>
          Included allowances. Leave a field blank for unlimited.
        </p>

        <div className={styles.limitsRow}>
          <FormField label="Vehicles" error={errors.vehicleLimit?.message}>
            <Input {...register("vehicleLimit")} inputMode="numeric" placeholder="Unlimited" />
          </FormField>
          <FormField label="Devices" error={errors.deviceLimit?.message}>
            <Input {...register("deviceLimit")} inputMode="numeric" placeholder="Unlimited" />
          </FormField>
          <FormField label="Users" error={errors.userLimit?.message}>
            <Input {...register("userLimit")} inputMode="numeric" placeholder="Unlimited" />
          </FormField>
        </div>
      </form>
    </FormDrawer>
  );
}
