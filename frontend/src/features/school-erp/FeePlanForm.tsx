import { useEffect } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { FileSpreadsheet } from "lucide-react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { Button } from "../../shared/components/Button/Button";
import { FormDrawer } from "../../shared/components/Drawer/FormDrawer";
import { FormField } from "../../shared/components/FormField/FormField";
import { Input } from "../../shared/components/Input/Input";
import { useToast } from "../../shared/components/Toast/toastStore";
import { ApiError } from "../../shared/api/types";
import { createFeePlan, updateFeePlan, type FeePlan } from "./api";
import styles from "./forms.module.css";

/**
 * Create or edit a fee plan — the named recurring charge a monthly billing run bills students
 * against.
 *
 * A plan is a *template*, not a bill: changing or archiving one later never alters an invoice
 * already issued, because each invoice captures its own amount and discount at issue time. That
 * is why this form has no "apply to existing invoices" affordance to offer, and why editing an
 * amount here is safe even for a plan with issued invoices already outstanding against it.
 */

const AMOUNT_PATTERN = /^\d{1,13}(\.\d{1,2})?$/;

const schema = z
  .object({
    name: z.string().min(1, "Name is required").max(160),
    amount: z
      .string()
      .min(1, "Amount is required")
      .refine((value) => AMOUNT_PATTERN.test(value), {
        message: "Use a decimal amount, e.g. 50.00",
      })
      .refine((value) => Number(value) > 0, { message: "Amount must be greater than zero" }),
    currency: z.string().length(3, "Use a 3-letter currency code"),
    defaultDiscountAmount: z
      .string()
      .refine((value) => value === "" || AMOUNT_PATTERN.test(value), {
        message: "Use a decimal amount, e.g. 5.00",
      }),
    description: z.string().max(500).optional(),
  })
  .refine(
    (values) =>
      !values.defaultDiscountAmount ||
      Number(values.defaultDiscountAmount) <= Number(values.amount),
    { message: "Discount cannot exceed the fee", path: ["defaultDiscountAmount"] },
  );

type FormValues = z.infer<typeof schema>;

export interface FeePlanFormProps {
  open: boolean;
  onClose: () => void;
  currency: string;
  /** Present -> edit this existing plan instead of creating a new one. */
  editing?: FeePlan | null;
}

export function FeePlanForm({ open, onClose, currency, editing = null }: FeePlanFormProps) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const isEditing = editing !== null;

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { name: "", amount: "", currency, defaultDiscountAmount: "0.00" },
  });

  useEffect(() => {
    if (open) {
      reset(
        editing
          ? {
              name: editing.name,
              amount: editing.amount,
              currency: editing.currency,
              defaultDiscountAmount: editing.defaultDiscountAmount,
              description: editing.description ?? "",
            }
          : {
              name: "",
              amount: "",
              currency,
              defaultDiscountAmount: "0.00",
              description: "",
            },
      );
    }
  }, [open, currency, editing, reset]);

  const mutation = useMutation({
    mutationFn: (values: FormValues) => {
      const input = {
        name: values.name,
        amount: values.amount,
        currency: values.currency.toUpperCase(),
        defaultDiscountAmount: values.defaultDiscountAmount || "0.00",
        description: values.description || null,
      };
      return editing ? updateFeePlan(editing.id, input) : createFeePlan(input);
    },
    onSuccess: (plan) => {
      queryClient.invalidateQueries({ queryKey: ["school-finance"] });
      toast.success(
        isEditing ? "Fee plan updated" : "Fee plan created",
        isEditing
          ? `${plan.name} has been updated. Already-issued invoices are unaffected.`
          : `${plan.name} is ready to bill against.`,
      );
      onClose();
    },
    onError: (error) => {
      toast.error(
        isEditing ? "Could not update the fee plan" : "Could not create the fee plan",
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
      icon={<FileSpreadsheet size={18} />}
      iconTint="var(--color-brand-primary-tint)"
      iconColor="var(--color-brand-primary)"
      title={isEditing ? "Edit fee plan" : "New fee plan"}
      subtitle={
        isEditing
          ? "Changes never retro-apply to invoices already issued"
          : "A recurring charge to bill students against"
      }
      footer={
        <>
          <Button variant="ghost" onClick={handleClose} disabled={mutation.isPending}>
            Cancel
          </Button>
          <Button type="submit" form="fee-plan-form" loading={mutation.isPending}>
            {isEditing ? "Save changes" : "Create fee plan"}
          </Button>
        </>
      }
    >
      <form
        id="fee-plan-form"
        className={styles.form}
        onSubmit={handleSubmit((values) => mutation.mutate(values))}
      >
        <FormField
          label="Name"
          hint="What families will see it called, e.g. “Monthly transport — Term 1”."
          error={errors.name?.message}
        >
          <Input {...register("name")} invalid={Boolean(errors.name)} autoFocus />
        </FormField>

        <div className={styles.row}>
          <FormField label="Amount per period" error={errors.amount?.message}>
            <Input
              {...register("amount")}
              inputMode="decimal"
              placeholder="50.00"
              invalid={Boolean(errors.amount)}
            />
          </FormField>
          <FormField label="Currency" error={errors.currency?.message}>
            <Input {...register("currency")} maxLength={3} invalid={Boolean(errors.currency)} />
          </FormField>
        </div>

        <FormField
          label="Standard discount"
          hint="Applied to every invoice issued from this plan. Leave at 0.00 for none."
          error={errors.defaultDiscountAmount?.message}
        >
          <Input
            {...register("defaultDiscountAmount")}
            inputMode="decimal"
            invalid={Boolean(errors.defaultDiscountAmount)}
          />
        </FormField>

        <FormField label="Description" error={errors.description?.message}>
          <Input {...register("description")} placeholder="Optional" />
        </FormField>
      </form>
    </FormDrawer>
  );
}
