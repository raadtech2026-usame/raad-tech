import { zodResolver } from "@hookform/resolvers/zod";
import { useEffect } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Receipt } from "lucide-react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { Button } from "../../../shared/components/Button/Button";
import { FormDrawer } from "../../../shared/components/Drawer/FormDrawer";
import { FormField } from "../../../shared/components/FormField/FormField";
import { Input } from "../../../shared/components/Input/Input";
import { Select } from "../../../shared/components/Select/Select";
import { useToast } from "../../../shared/components/Toast/toastStore";
import { ApiError } from "../../../shared/api/types";
import { saveParentBillingProfile, type ParentBillingProfile } from "./api";
import styles from "./forms.module.css";

const AMOUNT_PATTERN = /^\d{1,13}(\.\d{1,2})?$/;
const PERIOD_PATTERN = /^\d{4}-(0[1-9]|1[0-2])$/;

const schema = z.object({
  monthlyFee: z
    .string()
    .min(1, "Monthly fee is required")
    .refine((value) => AMOUNT_PATTERN.test(value), { message: "Use a decimal amount, e.g. 80.00" })
    .refine((value) => Number(value) > 0, { message: "Monthly fee must be greater than zero" }),
  currency: z.string().length(3, "Use a 3-letter currency code, e.g. USD"),
  billingStartPeriod: z.string().regex(PERIOD_PATTERN, "Use YYYY-MM, e.g. 2026-09"),
  dueDay: z.coerce.number().int().min(1).max(28),
});

type FormValues = z.infer<typeof schema>;

function currentPeriod(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

export interface BillingProfileFormProps {
  open: boolean;
  onClose: () => void;
  parentId: string | null;
  parentName?: string;
  existing: ParentBillingProfile | null;
}

/**
 * `PUT /school-finance/parents/{parent_id}/billing-profile` — the directive's Part 5: the
 * organization types the family's actual monthly transportation charge directly, no Fee Plan
 * required. Creates the Billing Profile if the parent has none yet, otherwise edits the existing
 * one in place; editing never rewrites an already-generated Parent Invoice (Part 17/40 — a fee
 * change applies from the next period onward, the historical invoice keeps its own frozen amount).
 */
export function BillingProfileForm({ open, onClose, parentId, parentName, existing }: BillingProfileFormProps) {
  const toast = useToast();
  const queryClient = useQueryClient();

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { monthlyFee: "", currency: "USD", billingStartPeriod: currentPeriod(), dueDay: 10 },
  });

  useEffect(() => {
    if (open) {
      reset(
        existing
          ? {
              monthlyFee: existing.monthlyFee,
              currency: existing.currency,
              billingStartPeriod: existing.billingStartPeriod,
              dueDay: existing.dueDay,
            }
          : { monthlyFee: "", currency: "USD", billingStartPeriod: currentPeriod(), dueDay: 10 },
      );
    }
  }, [open, existing, reset]);

  const mutation = useMutation({
    mutationFn: (values: FormValues) => {
      if (!parentId) return Promise.reject(new Error("No parent selected."));
      return saveParentBillingProfile(parentId, values);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["parents", "billing-profile", parentId] });
      toast.success(
        existing ? "Billing updated" : "Billing configured",
        `${parentName ?? "This family"} is now billed monthly. Future invoices use the new amount; past invoices are unchanged.`,
      );
      onClose();
    },
    onError: (error) => {
      toast.error(
        "Could not save billing",
        error instanceof ApiError ? error.message : "Something went wrong. Please try again.",
      );
    },
  });

  function handleClose(): void {
    if (mutation.isPending) return;
    onClose();
  }

  if (!open || !parentId) return null;

  return (
    <FormDrawer
      open={open}
      onClose={handleClose}
      icon={<Receipt size={18} />}
      iconTint="var(--color-brand-primary-tint)"
      iconColor="var(--color-brand-primary)"
      title="Parent billing"
      subtitle={parentName ?? "Monthly transportation fee"}
      footer={
        <>
          <Button variant="ghost" onClick={handleClose} disabled={mutation.isPending}>
            Cancel
          </Button>
          <Button type="submit" form="billing-profile-form" loading={mutation.isPending}>
            Save
          </Button>
        </>
      }
    >
      <form id="billing-profile-form" className={styles.form} onSubmit={handleSubmit((values) => mutation.mutate(values))}>
        <FormField
          label="Monthly transportation fee"
          hint="This parent is charged this amount every month starting from the billing start period. No Fee Plan required."
          error={errors.monthlyFee?.message}
        >
          <Input {...register("monthlyFee")} inputMode="decimal" placeholder="80.00" invalid={Boolean(errors.monthlyFee)} autoFocus />
        </FormField>

        <FormField label="Currency" error={errors.currency?.message}>
          <Select {...register("currency")}>
            <option value="USD">USD</option>
            <option value="SOS">SOS</option>
            <option value="KES">KES</option>
          </Select>
        </FormField>

        <FormField label="Billing start" hint="First month this parent is billed, e.g. 2026-09." error={errors.billingStartPeriod?.message}>
          <Input {...register("billingStartPeriod")} placeholder="2026-09" invalid={Boolean(errors.billingStartPeriod)} />
        </FormField>

        <FormField label="Due day" hint="Day of the month the invoice is due (1–28)." error={errors.dueDay?.message}>
          <Input {...register("dueDay")} type="number" min={1} max={28} invalid={Boolean(errors.dueDay)} />
        </FormField>
      </form>
    </FormDrawer>
  );
}
