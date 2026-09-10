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
import { createPlatformCategory, type PlatformCategoryKind } from "./api";
// Reuses `PlatformEntryForm`'s own stylesheet rather than a third near-duplicate file — same
// folder, same drawer-form shape, and that file's own header already explains why this domain
// keeps its CSS separate from `school-erp/forms.module.css`.
import styles from "./PlatformEntryForm.module.css";

/**
 * Create a platform financial category — the heading RAAD's own income/expense entries are
 * filed under.
 *
 * Create-only, deliberately: `platform_finance`'s backend has no update or archive route for
 * categories (unlike `school_erp`'s), so there is nothing for an edit affordance to call. Kind
 * is fixed at creation for the same reason `school_erp`'s own category kind is — it is what
 * keeps an expense from being filed under an income heading.
 */

const schema = z.object({
  name: z.string().min(1, "Name is required").max(160),
  kind: z.enum(["income", "expense"]),
  description: z.string().max(500).optional(),
});

type FormValues = z.infer<typeof schema>;

export interface PlatformCategoryFormProps {
  open: boolean;
  onClose: () => void;
  defaultKind: PlatformCategoryKind;
}

export function PlatformCategoryForm({ open, onClose, defaultKind }: PlatformCategoryFormProps) {
  const toast = useToast();
  const queryClient = useQueryClient();

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { name: "", kind: defaultKind },
  });

  useEffect(() => {
    if (open) {
      reset({ name: "", kind: defaultKind, description: "" });
    }
  }, [open, defaultKind, reset]);

  const mutation = useMutation({
    mutationFn: (values: FormValues) =>
      createPlatformCategory({
        name: values.name,
        kind: values.kind,
        description: values.description || null,
      }),
    onSuccess: (category) => {
      queryClient.invalidateQueries({ queryKey: ["platform-finance", "categories"] });
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
      title="New platform category"
      subtitle="A heading for RAAD's own income or expenses"
      footer={
        <>
          <Button variant="ghost" onClick={handleClose} disabled={mutation.isPending}>
            Cancel
          </Button>
          <Button type="submit" form="platform-category-form" loading={mutation.isPending}>
            Create category
          </Button>
        </>
      }
    >
      <form
        id="platform-category-form"
        className={styles.form}
        onSubmit={handleSubmit((values) => mutation.mutate(values))}
      >
        <FormField label="Name" error={errors.name?.message}>
          <Input {...register("name")} placeholder="Cloud infrastructure" invalid={Boolean(errors.name)} autoFocus />
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

        <FormField label="Description" error={errors.description?.message}>
          <Input {...register("description")} placeholder="Optional" />
        </FormField>
      </form>
    </FormDrawer>
  );
}
