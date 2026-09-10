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
  expenseKindLabel,
  listPlatformCategories,
  recordPlatformExpense,
  recordPlatformIncome,
  type ExpenseKind,
  type PlatformIncomeKind,
} from "./api";
import styles from "./PlatformEntryForm.module.css";

/**
 * Record one of RAAD's own operating costs, or a non-subscription income entry.
 *
 * **Subscription revenue is deliberately absent from the income headings.** It belongs to
 * `billing`, and the Platform P&L already reads what RAAD actually collected from there. Posting
 * it here too would count the same organization payments twice — the backend refuses it at the
 * aggregate (`PlatformIncome.__init__`), the route's schema refuses it, and this form does not
 * offer it. Three layers for one rule, because the rule is that the books stay right.
 */

const AMOUNT_PATTERN = /^\d{1,13}(\.\d{1,2})?$/;

const EXPENSE_KINDS: ExpenseKind[] = [
  "salaries",
  "rent",
  "electricity",
  "water",
  "internet",
  "equipment",
  "maintenance",
  "fuel",
  "marketing",
  "travel",
  "software",
  "professional_fees",
  "taxes",
  "other",
];

const INCOME_KINDS: { value: PlatformIncomeKind; label: string }[] = [
  { value: "hardware_sale", label: "Hardware sale" },
  { value: "installation", label: "Installation" },
  { value: "support_contract", label: "Support contract" },
  { value: "grant", label: "Grant" },
  { value: "other", label: "Other" },
];

const schema = z.object({
  kind: z.string().min(1, "Choose a heading"),
  amount: z
    .string()
    .min(1, "Amount is required")
    .refine((value) => AMOUNT_PATTERN.test(value), {
      message: "Use a decimal amount, e.g. 1200.00",
    })
    .refine((value) => Number(value) > 0, { message: "Amount must be greater than zero" }),
  currency: z.string().length(3, "Use a 3-letter currency code"),
  occurredOn: z.string().min(1, "Date is required"),
  counterparty: z.string().max(160).optional(),
  description: z.string().max(500).optional(),
  reference: z.string().max(120).optional(),
  categoryId: z.string().optional(),
});

type FormValues = z.infer<typeof schema>;

export type PlatformEntryMode = "income" | "expense";

export interface PlatformEntryFormProps {
  open: boolean;
  onClose: () => void;
  mode: PlatformEntryMode;
  currency: string;
}

function today(): string {
  return new Date().toISOString().slice(0, 10);
}

export function PlatformEntryForm({
  open,
  onClose,
  mode,
  currency,
}: PlatformEntryFormProps) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const isIncome = mode === "income";

  // Categories are shared across both directions of the ledger but filtered here to the
  // matching kind, mirroring `school_erp`'s own `CategoryForm` picker convention — an income
  // entry should never be filed under an expense heading or vice versa.
  const categoriesQuery = useQuery({
    queryKey: ["platform-finance", "categories"],
    queryFn: listPlatformCategories,
    staleTime: 60_000,
  });
  const categoryOptions = (categoriesQuery.data ?? []).filter(
    (category) => category.kind === mode && category.status === "active",
  );

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      kind: isIncome ? "hardware_sale" : "salaries",
      amount: "",
      currency,
      occurredOn: today(),
    },
  });

  useEffect(() => {
    if (open) {
      reset({
        kind: isIncome ? "hardware_sale" : "salaries",
        amount: "",
        currency,
        occurredOn: today(),
        counterparty: "",
        description: "",
        reference: "",
        categoryId: "",
      });
    }
  }, [open, isIncome, currency, reset]);

  const mutation = useMutation({
    // Explicit return type: the two branches produce different DTOs, and TypeScript infers the
    // union rather than widening, which `MutationFunction` will not accept. Nothing here reads
    // the result, so `void` is both honest and the narrowest thing that works.
    mutationFn: async (values: FormValues): Promise<void> => {
      const common = {
        amount: values.amount,
        currency: values.currency.toUpperCase(),
        occurredOn: values.occurredOn,
        description: values.description || null,
        reference: values.reference || null,
        categoryId: values.categoryId || null,
      };
      if (isIncome) {
        await recordPlatformIncome({
          ...common,
          kind: values.kind as PlatformIncomeKind,
          source: values.counterparty || null,
        });
      } else {
        await recordPlatformExpense({
          ...common,
          kind: values.kind as ExpenseKind,
          vendor: values.counterparty || null,
        });
      }
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["platform-finance"] });
      toast.success(
        isIncome ? "Income recorded" : "Expense recorded",
        "The platform profit & loss and its reports are updated.",
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
      title={isIncome ? "Record platform income" : "Record an operating cost"}
      subtitle={
        isIncome
          ? "Hardware, installation, support contracts and grants"
          : "Salaries, rent, utilities, equipment and other RAAD costs"
      }
      footer={
        <>
          <Button variant="ghost" onClick={handleClose} disabled={mutation.isPending}>
            Cancel
          </Button>
          <Button type="submit" form="platform-entry-form" loading={mutation.isPending}>
            {isIncome ? "Record income" : "Record expense"}
          </Button>
        </>
      }
    >
      <form
        id="platform-entry-form"
        className={styles.form}
        onSubmit={handleSubmit((values) => mutation.mutate(values))}
      >
        {isIncome && (
          <div className={styles.notice}>
            <Info size={16} className={styles.noticeIcon} aria-hidden="true" />
            <div className={styles.noticeBody}>
              <span className={styles.noticeTitle}>Not for subscription revenue</span>
              <span className={styles.noticeText}>
                What organizations pay for their RAAD subscription is already counted, read
                directly from billing into the platform P&amp;L. Recording it here as well would
                count the same payments twice, so it is not offered as a heading.
              </span>
            </div>
          </div>
        )}

        <FormField label="Heading" error={errors.kind?.message}>
          <Select {...register("kind")}>
            {isIncome
              ? INCOME_KINDS.map((kind) => (
                  <option key={kind.value} value={kind.value}>
                    {kind.label}
                  </option>
                ))
              : EXPENSE_KINDS.map((kind) => (
                  <option key={kind} value={kind}>
                    {expenseKindLabel(kind)}
                  </option>
                ))}
          </Select>
        </FormField>

        <div className={styles.row}>
          <FormField label="Amount" error={errors.amount?.message}>
            <Input
              {...register("amount")}
              inputMode="decimal"
              placeholder="1200.00"
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
          hint="Optional, but what the Categories breakdown groups by."
          error={errors.categoryId?.message}
        >
          <Select {...register("categoryId")}>
            <option value="">Uncategorised</option>
            {categoryOptions.map((category) => (
              <option key={category.id} value={category.id}>
                {category.name}
              </option>
            ))}
          </Select>
        </FormField>

        <FormField
          label={isIncome ? "Source" : "Vendor"}
          hint="Who the money came from, or who was paid. Optional."
          error={errors.counterparty?.message}
        >
          <Input
            {...register("counterparty")}
            placeholder={isIncome ? "Reseller" : "Landlord"}
          />
        </FormField>

        <FormField label="Description" error={errors.description?.message}>
          <Input
            {...register("description")}
            placeholder={isIncome ? "20 MDVR units" : "Office rent — September"}
          />
        </FormField>

        <FormField
          label="Reference"
          hint="Invoice or receipt number. Optional."
          error={errors.reference?.message}
        >
          <Input {...register("reference")} />
        </FormField>
      </form>
    </FormDrawer>
  );
}
