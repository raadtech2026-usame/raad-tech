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
import { Select } from "../../../shared/components/Select/Select";
import { useToast } from "../../../shared/components/Toast/toastStore";
import { ApiError } from "../../../shared/api/types";
import { updateStudent, type Student } from "./api";
import styles from "./CreateStudentForm.module.css";

const FULL_NAME_MAX_LENGTH = 200;
const EXTERNAL_REF_MAX_LENGTH = 64;
const NOTES_MAX_LENGTH = 500;

const schema = z.object({
  fullName: z
    .string()
    .trim()
    .min(1, "Full name is required")
    .max(FULL_NAME_MAX_LENGTH, `Full name must be at most ${FULL_NAME_MAX_LENGTH} characters`),
  externalRef: z
    .string()
    .trim()
    .max(EXTERNAL_REF_MAX_LENGTH, `External reference must be at most ${EXTERNAL_REF_MAX_LENGTH} characters`),
  dateOfBirth: z
    .string()
    .trim()
    .refine(
      (value) => value === "" || new Date(value).getTime() <= Date.now(),
      "Date of birth must not be in the future",
    ),
  gender: z.enum(["", "male", "female", "other"]),
  notes: z.string().trim().max(NOTES_MAX_LENGTH, `Notes must be at most ${NOTES_MAX_LENGTH} characters`),
});

type FormValues = z.infer<typeof schema>;

function toFormValues(student: Student): FormValues {
  return {
    fullName: student.fullName,
    externalRef: student.externalRef ?? "",
    dateOfBirth: student.dateOfBirth ?? "",
    gender: student.gender ?? "",
    notes: student.notes ?? "",
  };
}

export interface EditStudentFormProps {
  open: boolean;
  onClose: () => void;
  student: Student | null;
}

/**
 * `PATCH /students/{id}` (`UpdateStudentRequest`, profile fields only — never `status`, which
 * has its own dedicated `POST /students/{id}/status` route and the drawer's own status buttons).
 * Editing here can never touch `student_parents` links, `student_assignments`, or
 * `erp_student_invoices` rows: `updateStudent` (`./api.ts`) has no parameter through which any
 * of them could even be named.
 */
export function EditStudentForm({ open, onClose, student }: EditStudentFormProps) {
  const toast = useToast();
  const queryClient = useQueryClient();

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: student ? toFormValues(student) : undefined,
  });

  useEffect(() => {
    if (open && student) {
      reset(toFormValues(student));
    }
  }, [open, student, reset]);

  const mutation = useMutation({
    mutationFn: (values: FormValues) => {
      if (!student) return Promise.reject(new Error("No student selected."));
      return updateStudent(student.id, {
        fullName: values.fullName,
        externalRef: values.externalRef || null,
        dateOfBirth: values.dateOfBirth || null,
        gender: values.gender || null,
        notes: values.notes || null,
      });
    },
    onSuccess: (updated) => {
      queryClient.invalidateQueries({ queryKey: ["students", "list"] });
      queryClient.invalidateQueries({ queryKey: ["students", "detail", updated.id] });
      toast.success("Student updated", `${updated.fullName}'s profile has been saved.`);
      onClose();
    },
    onError: (error) => {
      const message = error instanceof ApiError ? error.message : "Could not update the student.";
      toast.error("Update failed", message);
    },
  });

  function handleClose(): void {
    if (mutation.isPending) return;
    mutation.reset();
    onClose();
  }

  const onValid = handleSubmit((values) => mutation.mutate(values));

  if (!open || !student) {
    return null;
  }

  return (
    <FormDrawer
      open={open}
      onClose={handleClose}
      icon={<Pencil size={20} />}
      iconTint="var(--color-brand-primary-tint)"
      iconColor="var(--color-brand-primary)"
      title="Edit student"
      subtitle={student.fullName}
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
          <Input placeholder="e.g. Amina Hassan" invalid={!!errors.fullName} {...register("fullName")} />
        </FormField>

        <FormField
          label="External reference"
          hint="Optional — the school's own student ID/reference number."
          error={errors.externalRef?.message}
        >
          <Input placeholder="e.g. STU-00231" invalid={!!errors.externalRef} {...register("externalRef")} />
        </FormField>

        <FormField label="Date of birth" hint="Optional." error={errors.dateOfBirth?.message}>
          <Input type="date" invalid={!!errors.dateOfBirth} {...register("dateOfBirth")} />
        </FormField>

        <FormField label="Gender" hint="Optional." error={errors.gender?.message}>
          <Select {...register("gender")} aria-label="Gender">
            <option value="">Not specified</option>
            <option value="male">Male</option>
            <option value="female">Female</option>
            <option value="other">Other</option>
          </Select>
        </FormField>

        <FormField label="Notes" hint="Optional." error={errors.notes?.message}>
          <Input placeholder="Optional" invalid={!!errors.notes} {...register("notes")} />
        </FormField>
      </form>
    </FormDrawer>
  );
}
