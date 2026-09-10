import { useEffect } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Tags } from "lucide-react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { Button } from "../../shared/components/Button/Button";
import { FormDrawer } from "../../shared/components/Drawer/FormDrawer";
import { FormField } from "../../shared/components/FormField/FormField";
import { Input } from "../../shared/components/Input/Input";
import { Select } from "../../shared/components/Select/Select";
import { useToast } from "../../shared/components/Toast/toastStore";
import { ApiError } from "../../shared/api/types";
import { createCategory, type CategoryKind, type FinancialCategory } from "./api";
import styles from "./forms.module.css";

/**
 * Create a financial category — the heading income and expenses are filed under, and what the
 * Profit & Loss breakdown groups by.
 *
 * `kind` is fixed at creation and cannot be changed afterwards: it is what stops an expense being
 * filed under an income heading, and letting it flip would silently reclassify every entry
 * already filed under it.
 */

const schema = z.object({
  name: z.string().min(1, "Name is required").max(160),
  kind: z.enum(["income", "expense"]),
  parentCategoryId: z.string().optional(),
  description: z.string().max(500).optional(),
});

type FormValues = z.infer<typeof schema>;

export interface CategoryFormProps {
  open: boolean;
  onClose: () => void;
  /** Which side of the ledger the tab the operator came from is showing. */
  defaultKind: CategoryKind;
  /** Existing categories, so a new one can be nested under a matching-kind parent. */
  categories: FinancialCategory[];
}

export function CategoryForm({
  open,
  onClose,
  defaultKind,
  categories,
}: CategoryFormProps) {
  const toast = useToast();
  const queryClient = useQueryClient();

  const {
    register,
    handleSubmit,
    reset,
    watch,
    formState: { errors },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { name: "", kind: defaultKind },
  });

  const kind = watch("kind");

  useEffect(() => {
    if (open) {
      reset({ name: "", kind: defaultKind, parentCategoryId: "", description: "" });
    }
  }, [open, defaultKind, reset]);

  // A parent must share its child's kind — the backend enforces it, and offering a mismatched
  // parent here would just produce a rejection the operator could not have predicted.
  const parentOptions = categories.filter(
    (category) => category.kind === kind && category.parentCategoryId === null && category.status === "active",
  );

  const mutation = useMutation({
    mutationFn: (values: FormValues) =>
      createCategory({
        name: values.name,
        kind: values.kind,
        parentCategoryId: values.parentCategoryId || null,
        description: values.description || null,
      }),
    onSuccess: (category) => {
      queryClient.invalidateQueries({ queryKey: ["school-finance"] });
      toast.success("Category created", `${category.name} can now be used to file entries.`);
      onClose();
    },
    onError: (error) => {
      toast.error(
        "Could not create the category",
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
      icon={<Tags size={18} />}
      iconTint="var(--color-brand-primary-tint)"
      iconColor="var(--color-brand-primary)"
      title="New category"
      subtitle="A heading for income or expenses"
      footer={
        <>
          <Button variant="ghost" onClick={handleClose} disabled={mutation.isPending}>
            Cancel
          </Button>
          <Button type="submit" form="category-form" loading={mutation.isPending}>
            Create category
          </Button>
        </>
      }
    >
      <form
        id="category-form"
        className={styles.form}
        onSubmit={handleSubmit((values) => mutation.mutate(values))}
      >
        <FormField label="Name" error={errors.name?.message}>
          <Input
            {...register("name")}
            placeholder={kind === "income" ? "Donations" : "Fuel"}
            invalid={Boolean(errors.name)}
            autoFocus
          />
        </FormField>

        <FormField
          label="Side of the ledger"
          hint="Fixed once created — it is what keeps an expense out of an income heading."
          error={errors.kind?.message}
        >
          <Select {...register("kind")}>
            <option value="income">Income</option>
            <option value="expense">Expense</option>
          </Select>
        </FormField>

        <FormField
          label="Nest under"
          hint="Optional, one level — e.g. “Utilities” → “Electricity”."
          error={errors.parentCategoryId?.message}
        >
          <Select {...register("parentCategoryId")}>
            <option value="">Top level</option>
            {parentOptions.map((category) => (
              <option key={category.id} value={category.id}>
                {category.name}
              </option>
            ))}
          </Select>
        </FormField>

        <FormField label="Description" error={errors.description?.message}>
          <Input {...register("description")} placeholder="Optional" />
        </FormField>
      </form>
    </FormDrawer>
  );
}
