import { zodResolver } from "@hookform/resolvers/zod";
import { useEffect } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Receipt } from "lucide-react";
import { useFieldArray, useForm } from "react-hook-form";
import { z } from "zod";
import { Button } from "../../../shared/components/Button/Button";
import { FormDrawer } from "../../../shared/components/Drawer/FormDrawer";
import { FormField } from "../../../shared/components/FormField/FormField";
import { Input } from "../../../shared/components/Input/Input";
import { Select } from "../../../shared/components/Select/Select";
import { Skeleton } from "../../../shared/components/Skeleton/Skeleton";
import { useToast } from "../../../shared/components/Toast/toastStore";
import { ApiError } from "../../../shared/api/types";
import {
  formatParentAmount,
  getFamilyFees,
  saveParentBillingProfile,
  setStudentBillingFee,
  type ParentBillingProfile,
} from "./api";
import styles from "./forms.module.css";

const AMOUNT_PATTERN = /^\d{1,13}(\.\d{1,2})?$/;
const PERIOD_PATTERN = /^\d{4}-(0[1-9]|1[0-2])$/;

const schema = z.object({
  currency: z.string().length(3, "Use a 3-letter currency code, e.g. USD"),
  billingStartPeriod: z.string().regex(PERIOD_PATTERN, "Use YYYY-MM, e.g. 2026-09"),
  dueDay: z.coerce.number().int().min(1).max(28),
  fees: z.array(
    z
      .object({
        studentId: z.string(),
        fullName: z.string(),
        status: z.string(),
        original: z.string(),
        monthlyFee: z.string().trim(),
      })
      .refine((fee) => fee.monthlyFee === "" || AMOUNT_PATTERN.test(fee.monthlyFee), {
        message: "Use a decimal amount, e.g. 20.00",
        path: ["monthlyFee"],
      })
      // No route removes a fee, so blanking one would silently keep charging it. Zero is the
      // explicit way to stop billing a child.
      .refine((fee) => fee.original === "" || fee.monthlyFee !== "", {
        message: "Enter 0.00 to stop billing this child",
        path: ["monthlyFee"],
      }),
  ),
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
 * The family's billing (ADR-0048): the account terms — currency, first billed month, due day —
 * and **each child's own monthly fee**. The family's monthly invoice is one line per active
 * child at that child's fee, so the total shown here is exactly what the next invoice bills.
 *
 * Saves the account (`PUT .../billing-profile`) and then each fee that changed
 * (`PUT /school-finance/students/{id}/billing-fee`). A fee change applies from the next
 * generated invoice; invoices already generated keep their own frozen line amounts.
 */
export function BillingProfileForm({ open, onClose, parentId, parentName, existing }: BillingProfileFormProps) {
  const toast = useToast();
  const queryClient = useQueryClient();

  const feesQuery = useQuery({
    queryKey: ["parents", "family-fees", parentId],
    queryFn: () => getFamilyFees(parentId!),
    enabled: open && !!parentId,
  });

  const {
    register,
    handleSubmit,
    reset,
    control,
    watch,
    formState: { errors },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { currency: "USD", billingStartPeriod: currentPeriod(), dueDay: 10, fees: [] },
  });
  const { fields } = useFieldArray({ control, name: "fees" });

  useEffect(() => {
    if (!open) return;
    const students = feesQuery.data?.students ?? [];
    reset({
      currency: existing?.currency ?? feesQuery.data?.currency ?? "USD",
      billingStartPeriod: existing?.billingStartPeriod ?? currentPeriod(),
      dueDay: existing?.dueDay ?? 10,
      fees: students.map((student) => ({
        studentId: student.studentId,
        fullName: student.fullName,
        status: student.status,
        original: student.monthlyFee ?? "",
        monthlyFee: student.monthlyFee ?? "",
      })),
    });
  }, [open, existing, feesQuery.data, reset]);

  const currency = watch("currency");
  const watchedFees = watch("fees");
  const activeFees = watchedFees.filter((fee) => fee.status === "active");
  const unpriced = activeFees.filter((fee) => fee.monthlyFee === "").length;
  const total = activeFees
    .filter((fee) => AMOUNT_PATTERN.test(fee.monthlyFee))
    .reduce((sum, fee) => sum + Math.round(Number(fee.monthlyFee) * 100), 0);

  const mutation = useMutation({
    mutationFn: async (values: FormValues) => {
      if (!parentId) throw new Error("No parent selected.");
      await saveParentBillingProfile(parentId, {
        currency: values.currency,
        billingStartPeriod: values.billingStartPeriod,
        dueDay: values.dueDay,
      });
      const changed = values.fees.filter(
        (fee) => fee.monthlyFee !== "" && Number(fee.monthlyFee).toFixed(2) !== (fee.original || null),
      );
      for (const fee of changed) {
        await setStudentBillingFee(fee.studentId, { monthlyFee: fee.monthlyFee, currency: values.currency });
      }
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["parents", "billing-profile", parentId] });
      queryClient.invalidateQueries({ queryKey: ["parents", "family-fees", parentId] });
      queryClient.invalidateQueries({ queryKey: ["school-finance"] });
      toast.success(
        existing ? "Billing updated" : "Billing configured",
        `${parentName ?? "This family"}'s next invoice uses these fees. Invoices already generated are unchanged.`,
      );
      onClose();
    },
    onError: (error) => {
      // The account is saved before any fee, so a failure part-way leaves earlier fees saved.
      queryClient.invalidateQueries({ queryKey: ["parents", "family-fees", parentId] });
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
      title="Family billing"
      subtitle={parentName ?? "Monthly transportation fees"}
      footer={
        <>
          <Button variant="ghost" onClick={handleClose} disabled={mutation.isPending}>
            Cancel
          </Button>
          <Button type="submit" form="billing-profile-form" loading={mutation.isPending} disabled={feesQuery.isLoading}>
            Save
          </Button>
        </>
      }
    >
      <form id="billing-profile-form" className={styles.form} onSubmit={handleSubmit((values) => mutation.mutate(values))}>
        <div className={styles.fieldGroup}>
          <span className={styles.groupTitle}>Monthly fee per student</span>
          <p className={styles.groupHint}>
            Each child is billed their own fee on the family's monthly invoice. Enter 0.00 for a child who rides free.
            A child with no fee is left off the invoice until one is set.
          </p>
          {feesQuery.isLoading && <Skeleton height={60} />}
          {feesQuery.isError && (
            <span className={styles.groupHint}>
              {feesQuery.error instanceof ApiError ? feesQuery.error.message : "Could not load this family's children."}
            </span>
          )}
          {feesQuery.isSuccess && fields.length === 0 && (
            <span className={styles.groupHint}>This family has no children yet. Add a student first.</span>
          )}
          {fields.map((field, index) => (
            <FormField
              key={field.id}
              label={`${field.fullName} (${currency || "USD"})`}
              hint={field.status === "active" ? undefined : `Not billed while ${field.status}.`}
              error={errors.fees?.[index]?.monthlyFee?.message}
            >
              <Input
                {...register(`fees.${index}.monthlyFee` as const)}
                inputMode="decimal"
                placeholder="Not set"
                aria-label={`Monthly fee for ${field.fullName}`}
                invalid={Boolean(errors.fees?.[index]?.monthlyFee)}
              />
            </FormField>
          ))}
          {fields.length > 0 && (
            <p className={styles.groupHint} aria-live="polite">
              Monthly total: <strong>{formatParentAmount((total / 100).toFixed(2), currency || "USD")}</strong>
              {unpriced > 0 && ` — ${unpriced} active ${unpriced === 1 ? "child has" : "children have"} no fee yet`}
            </p>
          )}
        </div>

        <FormField label="Currency" error={errors.currency?.message}>
          <Select {...register("currency")}>
            <option value="USD">USD</option>
            <option value="SOS">SOS</option>
            <option value="KES">KES</option>
          </Select>
        </FormField>

        <FormField label="Billing start" hint="First month this family is billed, e.g. 2026-09." error={errors.billingStartPeriod?.message}>
          <Input {...register("billingStartPeriod")} placeholder="2026-09" invalid={Boolean(errors.billingStartPeriod)} />
        </FormField>

        <FormField label="Due day" hint="Day of the month the invoice is due (1–28)." error={errors.dueDay?.message}>
          <Input {...register("dueDay")} type="number" min={1} max={28} invalid={Boolean(errors.dueDay)} />
        </FormField>
      </form>
    </FormDrawer>
  );
}
