import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { UserPlus } from "lucide-react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { Button } from "../../../shared/components/Button/Button";
import { FormDrawer } from "../../../shared/components/Drawer/FormDrawer";
import { FormField } from "../../../shared/components/FormField/FormField";
import { Input } from "../../../shared/components/Input/Input";
import { Select } from "../../../shared/components/Select/Select";
import { Toggle } from "../../../shared/components/Toggle/Toggle";
import { useToast } from "../../../shared/components/Toast/toastStore";
import { ApiError } from "../../../shared/api/types";
import { linkGuardianToStudent, listParentsForPicker } from "./api";
import styles from "./LinkGuardianForm.module.css";

// Matches `transport_ops.domain.value_objects`'s own `_ULID_PATTERN`.
const ULID_PATTERN = /^[0-9A-HJKMNP-TV-Z]{26}$/;
// `entities.py`'s `_RELATIONSHIP_MAX_LENGTH` (Database Design §6.4: `relationship VARCHAR(40)`).
const RELATIONSHIP_MAX_LENGTH = 40;

const schema = z.object({
  parentId: z
    .string()
    .min(1, "Parent is required")
    .refine((value) => ULID_PATTERN.test(value), { message: "Select a valid parent" }),
  relationship: z
    .string()
    .trim()
    .max(RELATIONSHIP_MAX_LENGTH, `Relationship must be at most ${RELATIONSHIP_MAX_LENGTH} characters`),
  isPrimary: z.boolean(),
});

type FormValues = z.infer<typeof schema>;
const DEFAULT_VALUES: FormValues = { parentId: "", relationship: "", isPrimary: false };

export interface LinkGuardianFormProps {
  open: boolean;
  onClose: () => void;
  studentId: string | null;
  studentName?: string;
}

/**
 * The "Add guardian" action on the student detail drawer — a distinct, explicit UI action, never
 * folded silently into a form field, matching `AssignDeviceForm.tsx`'s precedent for how a
 * distinct backend command (here, `POST /students/{student_id}/parents`,
 * `LinkParentToStudentRequest`) becomes its own dedicated form rather than a hidden field on
 * `CreateStudentForm`.
 *
 * This is the roadmap's own "first genuinely relational UI" (`docs/architecture/
 * frontend-flutter-master-roadmap.md`'s Phase F4 entry) — linking is initiated from the Student
 * side only (this form); the Parent detail drawer shows the mirror-image "Linked students" list
 * read-only plus an unlink action (`ParentsPage.tsx`), so the relationship is genuinely
 * bidirectionally *visible* even though it is only creatable from one side, a deliberate scope
 * choice rather than building two divergent forms for the identical link operation.
 *
 * **The two failure shapes this form surfaces honestly** — see `./api.ts`'s
 * `linkGuardianToStudent` docstring for the full backend citation: a duplicate link
 * (`ConflictError`, 409) and a cross-organization link (a raw `DomainError`, which
 * `core/errors/handlers.py`'s status table maps to a generic 500). Both are shown verbatim via a
 * toast using `error.message`, and the drawer stays open for another attempt — the same
 * safety-adjacent "don't swallow or misreport a real conflict" precedent
 * `AssignDeviceForm.tsx`'s own docstring establishes for the fleet_device module.
 */
export function LinkGuardianForm({ open, onClose, studentId, studentName }: LinkGuardianFormProps) {
  const toast = useToast();
  const queryClient = useQueryClient();

  const parentsQuery = useQuery({
    queryKey: ["parents", "link-picker"],
    queryFn: () => listParentsForPicker(""),
    enabled: open,
    staleTime: 30_000,
  });

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: DEFAULT_VALUES,
  });

  const mutation = useMutation({
    mutationFn: (values: FormValues) => {
      if (!studentId) {
        return Promise.reject(new Error("No student selected."));
      }
      return linkGuardianToStudent(studentId, {
        parentId: values.parentId,
        relationship: values.relationship || null,
        isPrimary: values.isPrimary,
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["students", "guardians", studentId] });
      toast.success("Guardian linked", "The parent has been linked to this student.");
      reset(DEFAULT_VALUES);
      onClose();
    },
    onError: (error) => {
      const message = error instanceof ApiError ? error.message : "Could not link the guardian.";
      toast.error("Link failed", message);
    },
  });

  function handleClose(): void {
    if (mutation.isPending) {
      return;
    }
    reset(DEFAULT_VALUES);
    mutation.reset();
    onClose();
  }

  const onValid = handleSubmit((values) => mutation.mutate(values));

  // Hooks above always run in the same order regardless; the early return only affects what
  // renders, mirroring `AssignDeviceForm.tsx`'s identical `device === null` guard.
  if (!open || !studentId) {
    return null;
  }

  const parentOptions = parentsQuery.data ?? [];
  const parentError = errors.parentId?.message ?? (parentsQuery.isError ? "Could not load parents." : undefined);

  return (
    <FormDrawer
      open={open}
      onClose={handleClose}
      icon={<UserPlus size={22} />}
      iconTint="var(--color-brand-primary-tint)"
      iconColor="var(--color-brand-primary)"
      title="Add guardian"
      subtitle={studentName ? `Link a parent to ${studentName}` : "Link a parent to this student"}
      footer={
        <div className={styles.footerActions}>
          <Button type="button" variant="secondary" onClick={handleClose} disabled={mutation.isPending}>
            Cancel
          </Button>
          <Button type="button" variant="primary" loading={isSubmitting || mutation.isPending} onClick={onValid}>
            Link guardian
          </Button>
        </div>
      }
    >
      <form className={styles.form} onSubmit={onValid} noValidate>
        <FormField label="Parent" error={parentError}>
          <Select {...register("parentId")} disabled={parentsQuery.isLoading} aria-label="Parent">
            <option value="">{parentsQuery.isLoading ? "Loading parents…" : "Select a parent"}</option>
            {parentOptions.map((parent) => (
              <option key={parent.id} value={parent.id}>
                {parent.fullName}
              </option>
            ))}
          </Select>
        </FormField>

        <FormField label="Relationship" hint="Optional — e.g. Mother, Father, Guardian." error={errors.relationship?.message}>
          <Input placeholder="e.g. Mother" invalid={!!errors.relationship} {...register("relationship")} />
        </FormField>

        <Toggle
          label="Primary guardian"
          description="The main point of contact for this student."
          {...register("isPrimary")}
        />
      </form>
    </FormDrawer>
  );
}
