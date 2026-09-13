import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { UserPlus } from "lucide-react";
import { Button } from "../../../shared/components/Button/Button";
import { FormDrawer } from "../../../shared/components/Drawer/FormDrawer";
import { FormField } from "../../../shared/components/FormField/FormField";
import { Input } from "../../../shared/components/Input/Input";
import { Toggle } from "../../../shared/components/Toggle/Toggle";
import { useToast } from "../../../shared/components/Toast/toastStore";
import { ApiError } from "../../../shared/api/types";
import { ParentSearchSelect, type SelectedParent } from "../parents/ParentSearchSelect";
import { linkGuardianToStudent } from "./api";
import styles from "./LinkGuardianForm.module.css";

// `entities.py`'s `_RELATIONSHIP_MAX_LENGTH` (Database Design §6.4: `relationship VARCHAR(40)`).
const RELATIONSHIP_MAX_LENGTH = 40;

export interface LinkGuardianFormProps {
  open: boolean;
  onClose: () => void;
  studentId: string | null;
  studentName?: string;
}

/**
 * The "Add guardian" action on the student detail drawer — also auto-opened once, right after
 * enrollment (`StudentsPage.tsx`'s `onCreated` chain, alongside `AssignStudentForm`/
 * `IssueInvoiceForm`), matching the task's own "search existing parent → select → student
 * appears under parent" flow without folding a second aggregate's worth of fields into
 * `CreateStudentForm` itself.
 *
 * **2026-09-10: the parent picker is now `ParentSearchSelect`** (search by name or phone, shows
 * the selected parent's phone and existing children count before submitting) — previously a
 * plain `<Select>` of up to 100 loaded parents with no search and no context. The backend
 * operation this form calls (`POST /students/{student_id}/parents`, `LinkParentToStudentRequest`)
 * is unchanged.
 *
 * This is the roadmap's own "first genuinely relational UI" (`docs/architecture/
 * frontend-flutter-master-roadmap.md`'s Phase F4 entry) — linking is initiated from the Student
 * side only; the Parent detail drawer shows the mirror-image "Linked students" list read-only
 * plus an unlink action (`ParentsPage.tsx`), so the relationship is genuinely bidirectionally
 * *visible* even though it is only creatable from one side.
 *
 * **The two failure shapes this form surfaces honestly** — see `./api.ts`'s
 * `linkGuardianToStudent` docstring for the full backend citation: a duplicate link
 * (`ConflictError`, 409) and a cross-organization link (a raw `DomainError`, mapped to a generic
 * 500 by `core/errors/handlers.py`'s status table). Both are shown verbatim via a toast using
 * `error.message`, and the drawer stays open for another attempt.
 */
export function LinkGuardianForm({ open, onClose, studentId, studentName }: LinkGuardianFormProps) {
  const toast = useToast();
  const queryClient = useQueryClient();

  const [parent, setParent] = useState<SelectedParent | null>(null);
  const [relationship, setRelationship] = useState("");
  const [isPrimary, setIsPrimary] = useState(false);
  const [relationshipError, setRelationshipError] = useState<string | undefined>(undefined);

  const mutation = useMutation({
    mutationFn: () => {
      if (!studentId || !parent) {
        return Promise.reject(new Error("Select a parent first."));
      }
      return linkGuardianToStudent(studentId, {
        parentId: parent.id,
        relationship: relationship || null,
        isPrimary,
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["students", "guardians", studentId] });
      toast.success("Guardian linked", "The parent has been linked to this student.");
      resetAll();
      onClose();
    },
    onError: (error) => {
      const message = error instanceof ApiError ? error.message : "Could not link the guardian.";
      toast.error("Link failed", message);
    },
  });

  function resetAll(): void {
    setParent(null);
    setRelationship("");
    setIsPrimary(false);
    setRelationshipError(undefined);
  }

  function handleClose(): void {
    if (mutation.isPending) {
      return;
    }
    resetAll();
    mutation.reset();
    onClose();
  }

  function handleSubmit(): void {
    if (!parent) {
      return;
    }
    if (relationship.length > RELATIONSHIP_MAX_LENGTH) {
      setRelationshipError(`Relationship must be at most ${RELATIONSHIP_MAX_LENGTH} characters`);
      return;
    }
    setRelationshipError(undefined);
    mutation.mutate();
  }

  // Hooks above always run in the same order regardless; the early return only affects what
  // renders, mirroring `AssignStudentForm.tsx`'s identical `studentId === null` guard.
  if (!open || !studentId) {
    return null;
  }

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
          <Button type="button" variant="primary" loading={mutation.isPending} disabled={!parent} onClick={handleSubmit}>
            Link guardian
          </Button>
        </div>
      }
    >
      <form className={styles.form} onSubmit={(event) => event.preventDefault()} noValidate>
        <FormField label="Parent">
          <ParentSearchSelect value={parent} onChange={setParent} aria-label="Parent" />
        </FormField>

        <FormField label="Relationship" hint="Optional — e.g. Mother, Father, Guardian." error={relationshipError}>
          <Input
            placeholder="e.g. Mother"
            invalid={!!relationshipError}
            value={relationship}
            onChange={(event) => setRelationship(event.target.value)}
          />
        </FormField>

        <Toggle
          label="Primary guardian"
          description="The main point of contact for this student."
          checked={isPrimary}
          onChange={(event) => setIsPrimary(event.target.checked)}
        />
      </form>
    </FormDrawer>
  );
}
