import { useEffect } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Info, TrendingDown, TrendingUp } from "lucide-react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { Button } from "../../shared/components/Button/Button";
import { FormDrawer } from "../../shared/components/Drawer/FormDrawer";
import { FormField } from "../../shared/components/FormField/FormField";
import { Input } from "../../shared/components/Input/Input";
import { Select } from "../../shared/components/Select/Select";
import { useToast } from "../../shared/components/Toast/toastStore";
import { ApiError } from "../../shared/api/types";
import {
  listCategories,
  listVehiclesForPicker,
  recordExpense,
  recordIncome,
} from "./api";
import styles from "./forms.module.css";

/**
 * Record a manual income or expense entry. One component, two modes — the two forms differ only
 * in which categories they offer, whether a bus can be attributed, and the notice at the top.
 *
 * **The notice on the income mode is the point of this file, not decoration.** School transport
 * revenue must never be entered here: it reaches the ledger automatically through
 * `StudentPayment`, and a manual "Transport fees" income row would be counted a second time
 * against the same money — once in Profit & Loss's `student_revenue` line (derived from
 * payments) and again in `other_income`. The backend keeps those two lines separate precisely so
 * a double entry is *visible*; this notice is what stops one being made in the first place.
 * Manual income is for money that has no invoice behind it: donations, sponsorships, grants,
 * government support.
 */

const AMOUNT_PATTERN = /^\d{1,13}(\.\d{1,2})?$/;
const LIST_PARAMS = { page: 1, pageSize: 100, sort: null, filters: {}, search: "" };

const schema = z.object({
  amount: z
    .string()
    .min(1, "Amount is required")
    .refine((value) => AMOUNT_PATTERN.test(value), {
      message: "Use a decimal amount, e.g. 250.00",
    })
    .refine((value) => Number(value) > 0, { message: "Amount must be greater than zero" }),
  currency: z.string().length(3, "Use a 3-letter currency code"),
  occurredOn: z.string().min(1, "Date is required"),
  categoryId: z.string().optional(),
  vehicleId: z.string().optional(),
  description: z.string().max(500).optional(),
  reference: z.string().max(120).optional(),
});

type FormValues = z.infer<typeof schema>;

export type LedgerEntryMode = "income" | "expense";

export interface LedgerEntryFormProps {
  open: boolean;
  onClose: () => void;
  mode: LedgerEntryMode;
  /** Organization currency, so the field starts on the one every other figure is shown in. */
  currency: string;
}

function today(): string {
  return new Date().toISOString().slice(0, 10);
}

export function LedgerEntryForm({ open, onClose, mode, currency }: LedgerEntryFormProps) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const isIncome = mode === "income";

  const categories = useQuery({
    queryKey: ["school-finance", "categories", "picker"],
    queryFn: () => listCategories(LIST_PARAMS),
    enabled: open,
    staleTime: 60_000,
  });

  const vehicles = useQuery({
    queryKey: ["school-finance", "vehicles", "picker"],
    queryFn: () => listVehiclesForPicker(),
    enabled: open && !isIncome,
    staleTime: 60_000,
  });

  const matchingCategories = (categories.data?.data ?? []).filter(
    (category) => category.kind === mode && category.status === "active",
  );

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { amount: "", currency, occurredOn: today() },
  });

  useEffect(() => {
    if (open) {
      reset({
        amount: "",
        currency,
        occurredOn: today(),
        categoryId: "",
        vehicleId: "",
        description: "",
        reference: "",
      });
    }
  }, [open, mode, currency, reset]);

  const mutation = useMutation({
    mutationFn: (values: FormValues) => {
      const common = {
        amount: values.amount,
        currency: values.currency.toUpperCase(),
        occurredOn: values.occurredOn,
        categoryId: values.categoryId || null,
        description: values.description || null,
        reference: values.reference || null,
      };
      return isIncome
        ? recordIncome(common)
        : recordExpense({ ...common, vehicleId: values.vehicleId || null });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["school-finance"] });
      toast.success(
        isIncome ? "Income recorded" : "Expense recorded",
        isIncome
          ? "Added to other income. Profit & Loss and reports are updated."
          : "Added to expenses. Profit & Loss, per-bus cost and reports are updated.",
      );
      onClose();
    },
    onError: (error) => {
      toast.error(
        isIncome ? "Could not record the income" : "Could not record the expense",
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
      icon={isIncome ? <TrendingUp size={18} /> : <TrendingDown size={18} />}
      iconTint="var(--color-brand-primary-tint)"
      iconColor="var(--color-brand-primary)"
      title={isIncome ? "Record other income" : "Record an expense"}
      subtitle={
        isIncome
          ? "Donations, sponsorships, grants and other non-student income"
          : "School and fleet running costs"
      }
      footer={
        <>
          <Button variant="ghost" onClick={handleClose} disabled={mutation.isPending}>
            Cancel
          </Button>
          <Button type="submit" form="ledger-entry-form" loading={mutation.isPending}>
            {isIncome ? "Record income" : "Record expense"}
          </Button>
        </>
      }
    >
      <form
        id="ledger-entry-form"
        className={styles.form}
        onSubmit={handleSubmit((values) => mutation.mutate(values))}
      >
        {isIncome && (
          <div className={styles.notice}>
            <Info size={16} className={styles.noticeIcon} aria-hidden="true" />
            <div className={styles.noticeBody}>
              <span className={styles.noticeTitle}>Not for student transport fees</span>
              <span className={styles.noticeText}>
                Student revenue is recorded automatically when a family's payment is entered
                against their invoice — it already appears in Profit &amp; Loss, per-bus revenue
                and every report. Adding it here as well would count the same money twice. Use
                this form only for income with no student invoice behind it.
              </span>
            </div>
          </div>
        )}

        <div className={styles.row}>
          <FormField label="Amount" error={errors.amount?.message}>
            <Input
              {...register("amount")}
              inputMode="decimal"
              placeholder="250.00"
              invalid={Boolean(errors.amount)}
              autoFocus
            />
          </FormField>
          <FormField label="Currency" error={errors.currency?.message}>
            <Input {...register("currency")} maxLength={3} invalid={Boolean(errors.currency)} />
          </FormField>
        </div>

        <FormField label="Date" error={errors.occurredOn?.message}>
          <Input type="date" {...register("occurredOn")} invalid={Boolean(errors.occurredOn)} />
        </FormField>

        <FormField
          label="Category"
          hint={
            matchingCategories.length === 0
              ? "No categories yet — create one on the Categories tab to break this down in reports."
              : "Optional, but it is what the Profit & Loss breakdown groups by."
          }
          error={errors.categoryId?.message}
        >
          <Select {...register("categoryId")}>
            <option value="">Uncategorised</option>
            {matchingCategories.map((category) => (
              <option key={category.id} value={category.id}>
                {category.name}
              </option>
            ))}
          </Select>
        </FormField>

        {!isIncome && (
          <FormField
            label="Attribute to a bus"
            hint="Optional. Attributed costs appear against that bus in the Vehicle financial overview."
            error={errors.vehicleId?.message}
          >
            <Select {...register("vehicleId")}>
              <option value="">Not bus-specific</option>
              {(vehicles.data ?? []).map((vehicle) => (
                <option key={vehicle.id} value={vehicle.id}>
                  {vehicle.label}
                </option>
              ))}
            </Select>
          </FormField>
        )}

        <FormField label="Description" error={errors.description?.message}>
          <Input
            {...register("description")}
            placeholder={isIncome ? "Community donation" : "Diesel — September"}
          />
        </FormField>

        <FormField
          label="Reference"
          hint="Receipt or voucher number. Optional."
          error={errors.reference?.message}
        >
          <Input {...register("reference")} />
        </FormField>
      </form>
    </FormDrawer>
  );
}
