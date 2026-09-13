import { zodResolver } from "@hookform/resolvers/zod";
import { useEffect } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Pencil } from "lucide-react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { Button } from "../../../shared/components/Button/Button";
import { FormDrawer } from "../../../shared/components/Drawer/FormDrawer";
import { FormField } from "../../../shared/components/FormField/FormField";
import { Input } from "../../../shared/components/Input/Input";
import { useToast } from "../../../shared/components/Toast/toastStore";
import { ApiError } from "../../../shared/api/types";
import { updateParent, type Parent } from "./api";
import styles from "./CreateParentForm.module.css";

const E164_PATTERN = /^\+[1-9]\d{1,14}$/;
const PHONE_MAX_LENGTH = 32;
const FULL_NAME_MAX_LENGTH = 200;
const ADDRESS_MAX_LENGTH = 255;
const EMERGENCY_CONTACT_NAME_MAX_LENGTH = 200;
const NOTES_MAX_LENGTH = 500;

const optionalPhone = z
  .string()
  .trim()
  .refine((value) => value === "" || (E164_PATTERN.test(value) && value.length <= PHONE_MAX_LENGTH), {
    message: "Phone must be E.164 format, e.g. +252612345678",
  });

const schema = z.object({
  fullName: z
    .string()
    .trim()
    .min(1, "Full name is required")
    .max(FULL_NAME_MAX_LENGTH, `Full name must be at most ${FULL_NAME_MAX_LENGTH} characters`),
  phone: optionalPhone,
  alternatePhone: optionalPhone,
  address: z.string().trim().max(ADDRESS_MAX_LENGTH, `Address must be at most ${ADDRESS_MAX_LENGTH} characters`),
  emergencyContactName: z
    .string()
    .trim()
    .max(
      EMERGENCY_CONTACT_NAME_MAX_LENGTH,
      `Emergency contact name must be at most ${EMERGENCY_CONTACT_NAME_MAX_LENGTH} characters`,
    ),
  emergencyContactPhone: optionalPhone,
  notes: z.string().trim().max(NOTES_MAX_LENGTH, `Notes must be at most ${NOTES_MAX_LENGTH} characters`),
});

type FormValues = z.infer<typeof schema>;

function toFormValues(parent: Parent): FormValues {
  return {
    fullName: parent.fullName,
    phone: parent.phone ?? "",
    alternatePhone: parent.alternatePhone ?? "",
    address: parent.address ?? "",
    emergencyContactName: parent.emergencyContactName ?? "",
    emergencyContactPhone: parent.emergencyContactPhone ?? "",
    notes: parent.notes ?? "",
  };
}

export interface EditParentFormProps {
  open: boolean;
  onClose: () => void;
  parent: Parent | null;
}

/**
 * `PATCH /parents/{id}` (`UpdateParentRequest`, contact/profile fields only — never `status`,
 * which stays on the detail drawer's own activate/deactivate footer buttons). Editing here can
 * never touch `student_parents` links or payment history: `updateParent` (`./api.ts`) has no
 * parameter through which either could even be named.
 */
export function EditParentForm({ open, onClose, parent }: EditParentFormProps) {
  const toast = useToast();
  const queryClient = useQueryClient();

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: parent ? toFormValues(parent) : undefined,
  });

  useEffect(() => {
    if (open && parent) {
      reset(toFormValues(parent));
    }
  }, [open, parent, reset]);

  const mutation = useMutation({
    mutationFn: (values: FormValues) => {
      if (!parent) return Promise.reject(new Error("No parent selected."));
      return updateParent(parent.id, {
        fullName: values.fullName,
        phone: values.phone || null,
        alternatePhone: values.alternatePhone || null,
        address: values.address || null,
        emergencyContactName: values.emergencyContactName || null,
        emergencyContactPhone: values.emergencyContactPhone || null,
        notes: values.notes || null,
      });
    },
    onSuccess: (updated) => {
      queryClient.invalidateQueries({ queryKey: ["parents", "list"] });
      queryClient.invalidateQueries({ queryKey: ["parents", "detail", updated.id] });
      toast.success("Parent updated", `${updated.fullName}'s profile has been saved.`);
      onClose();
    },
    onError: (error) => {
      const message = error instanceof ApiError ? error.message : "Could not update the parent.";
      toast.error("Update failed", message);
    },
  });

  function handleClose(): void {
    if (mutation.isPending) return;
    mutation.reset();
    onClose();
  }

  const onValid = handleSubmit((values) => mutation.mutate(values));

  if (!open || !parent) {
    return null;
  }

  return (
    <FormDrawer
      open={open}
      onClose={handleClose}
      icon={<Pencil size={20} />}
      iconTint="var(--color-brand-primary-tint)"
      iconColor="var(--color-brand-primary)"
      title="Edit parent"
      subtitle={parent.fullName}
      footer={
        <div className={styles.footerActions}>
          <Button type="button" variant="secondary" onClick={handleClose} disabled={mutation.isPending}>
            Cancel
          </Button>
          <Button type="button" variant="primary" loading={isSubmitting || mutation.isPending} onClick={onValid}>
            Save changes
          </Button>
        </div>
      }
    >
      <form className={styles.form} onSubmit={onValid} noValidate>
        <FormField label="Full name" error={errors.fullName?.message}>
          <Input placeholder="e.g. Fatima Ali" invalid={!!errors.fullName} {...register("fullName")} />
        </FormField>

        <FormField label="Primary phone" hint="E.164 format, e.g. +252612345678." error={errors.phone?.message}>
          <Input placeholder="+252612345678" invalid={!!errors.phone} {...register("phone")} />
        </FormField>

        <FormField label="Alternative phone" hint="Optional." error={errors.alternatePhone?.message}>
          <Input placeholder="+252611111111" invalid={!!errors.alternatePhone} {...register("alternatePhone")} />
        </FormField>

        <FormField label="Address" hint="Optional." error={errors.address?.message}>
          <Input placeholder="e.g. Hodan District, Mogadishu" invalid={!!errors.address} {...register("address")} />
        </FormField>

        <FormField label="Emergency contact name" hint="Optional." error={errors.emergencyContactName?.message}>
          <Input
            placeholder="e.g. Ahmed Hassan"
            invalid={!!errors.emergencyContactName}
            {...register("emergencyContactName")}
          />
        </FormField>

        <FormField label="Emergency contact phone" hint="Optional." error={errors.emergencyContactPhone?.message}>
          <Input
            placeholder="+252622222222"
            invalid={!!errors.emergencyContactPhone}
            {...register("emergencyContactPhone")}
          />
        </FormField>

        <FormField label="Notes" hint="Optional." error={errors.notes?.message}>
          <Input placeholder="Optional" invalid={!!errors.notes} {...register("notes")} />
        </FormField>
      </form>
    </FormDrawer>
  );
}
