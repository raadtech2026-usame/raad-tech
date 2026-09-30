import { zodResolver } from "@hookform/resolvers/zod";
import { useEffect } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { UserRound } from "lucide-react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { Button } from "../../../shared/components/Button/Button";
import { FormDrawer } from "../../../shared/components/Drawer/FormDrawer";
import { FormField } from "../../../shared/components/FormField/FormField";
import { Input } from "../../../shared/components/Input/Input";
import { Select } from "../../../shared/components/Select/Select";
import { useToast } from "../../../shared/components/Toast/toastStore";
import { ApiError } from "../../../shared/api/types";
import { listStaffRoles, registerStaff, updateStaff, type Staff, type StaffProfileInput } from "./api";
import styles from "./Staff.module.css";

const E164_PATTERN = /^\+[1-9]\d{1,14}$/;
const PHONE_MESSAGE = "Phone must be E.164 format, e.g. +252612345678";

const optionalPhone = z
  .string()
  .trim()
  .refine((value) => value === "" || E164_PATTERN.test(value), { message: PHONE_MESSAGE });

const schema = z.object({
  fullName: z.string().trim().min(1, "Full name is required").max(200, "At most 200 characters"),
  roleId: z.string(),
  phone: optionalPhone,
  alternatePhone: optionalPhone,
  employeeRef: z.string().trim().max(64, "At most 64 characters"),
  startDate: z.string(),
  emergencyContactName: z.string().trim().max(200, "At most 200 characters"),
  emergencyContactPhone: optionalPhone,
  notes: z.string().trim().max(500, "At most 500 characters"),
});

type FormValues = z.infer<typeof schema>;

const EMPTY: FormValues = {
  fullName: "",
  roleId: "",
  phone: "",
  alternatePhone: "",
  employeeRef: "",
  startDate: "",
  emergencyContactName: "",
  emergencyContactPhone: "",
  notes: "",
};

function toValues(staff: Staff): FormValues {
  return {
    fullName: staff.fullName,
    roleId: staff.roleId ?? "",
    phone: staff.phone ?? "",
    alternatePhone: staff.alternatePhone ?? "",
    employeeRef: staff.employeeRef ?? "",
    startDate: staff.startDate ?? "",
    emergencyContactName: staff.emergencyContactName ?? "",
    emergencyContactPhone: staff.emergencyContactPhone ?? "",
    notes: staff.notes ?? "",
  };
}

function toInput(values: FormValues): StaffProfileInput {
  const orNull = (value: string) => (value.trim() === "" ? null : value.trim());
  return {
    fullName: values.fullName.trim(),
    roleId: orNull(values.roleId),
    phone: orNull(values.phone),
    alternatePhone: orNull(values.alternatePhone),
    employeeRef: orNull(values.employeeRef),
    startDate: orNull(values.startDate),
    emergencyContactName: orNull(values.emergencyContactName),
    emergencyContactPhone: orNull(values.emergencyContactPhone),
    notes: orNull(values.notes),
  };
}

export interface StaffFormProps {
  open: boolean;
  onClose: () => void;
  /** Present when editing; absent when adding a new staff member. */
  staff?: Staff | null;
  onSaved?: (staff: Staff) => void;
}

/**
 * Adds or edits a staff member (ADR-0049). Org Admin only — the only role holding
 * `transport_ops.staff.manage`. No login is created here: only drivers log in, through
 * "Give driver access" on the profile. A job title is a label; choosing "Driver" does not make
 * someone a driver.
 */
export function StaffForm({ open, onClose, staff, onSaved }: StaffFormProps) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const editing = Boolean(staff);

  const rolesQuery = useQuery({
    queryKey: ["transport-staff", "roles"],
    queryFn: () => listStaffRoles(),
    enabled: open,
    staleTime: 60_000,
  });

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<FormValues>({ resolver: zodResolver(schema), defaultValues: EMPTY });

  useEffect(() => {
    if (open) reset(staff ? toValues(staff) : EMPTY);
  }, [open, staff, reset]);

  const mutation = useMutation({
    mutationFn: (values: FormValues) =>
      staff ? updateStaff(staff.id, toInput(values)) : registerStaff(toInput(values)),
    onSuccess: (saved) => {
      queryClient.invalidateQueries({ queryKey: ["transport-staff"] });
      toast.success(editing ? "Staff member updated" : "Staff member added", saved.fullName);
      onSaved?.(saved);
      onClose();
    },
    onError: (error) => {
      toast.error("Could not save", error instanceof ApiError ? error.message : "Please try again.");
    },
  });

  const onValid = handleSubmit((values) => mutation.mutate(values));
  // An archived title stays selectable only for someone who already holds it.
  const roles = (rolesQuery.data ?? []).filter((role) => !role.isArchived || role.id === staff?.roleId);

  return (
    <FormDrawer
      open={open}
      onClose={() => !mutation.isPending && onClose()}
      icon={<UserRound size={22} />}
      iconTint="var(--color-brand-primary-tint)"
      iconColor="var(--color-brand-primary)"
      title={editing ? "Edit staff member" : "New staff member"}
      subtitle="Someone who works on your buses"
      footer={
        <div className={styles.footerActions}>
          <Button type="button" variant="secondary" onClick={onClose} disabled={mutation.isPending}>
            Cancel
          </Button>
          <Button type="button" variant="primary" loading={mutation.isPending} onClick={onValid}>
            {editing ? "Save changes" : "Add staff member"}
          </Button>
        </div>
      }
    >
      <form className={styles.form} onSubmit={onValid} noValidate>
        <FormField label="Full name" error={errors.fullName?.message}>
          <Input {...register("fullName")} aria-label="Full name" autoComplete="off" />
        </FormField>
        <div className={styles.formRow}>
          <FormField
            label="Job title"
            hint={roles.length === 0 && !rolesQuery.isLoading ? "No job titles yet — add them under Setup." : undefined}
          >
            <Select {...register("roleId")} aria-label="Job title" disabled={rolesQuery.isLoading}>
              <option value="">No title</option>
              {roles.map((role) => (
                <option key={role.id} value={role.id}>
                  {role.name}
                  {role.isArchived ? " (archived)" : ""}
                </option>
              ))}
            </Select>
          </FormField>
          <FormField label="Employee reference" hint="Optional, unique in your organization" error={errors.employeeRef?.message}>
            <Input {...register("employeeRef")} aria-label="Employee reference" />
          </FormField>
        </div>
        <div className={styles.formRow}>
          <FormField label="Phone" error={errors.phone?.message}>
            <Input {...register("phone")} aria-label="Phone" placeholder="+252…" />
          </FormField>
          <FormField label="Alternate phone" error={errors.alternatePhone?.message}>
            <Input {...register("alternatePhone")} aria-label="Alternate phone" placeholder="+252…" />
          </FormField>
        </div>
        <FormField label="Start date">
          <Input type="date" {...register("startDate")} aria-label="Start date" />
        </FormField>
        <div className={styles.formRow}>
          <FormField label="Emergency contact" hint="Visible to Org Admins only" error={errors.emergencyContactName?.message}>
            <Input {...register("emergencyContactName")} aria-label="Emergency contact name" />
          </FormField>
          <FormField label="Emergency contact phone" error={errors.emergencyContactPhone?.message}>
            <Input {...register("emergencyContactPhone")} aria-label="Emergency contact phone" placeholder="+252…" />
          </FormField>
        </div>
        <FormField label="Notes" error={errors.notes?.message}>
          <Input {...register("notes")} aria-label="Notes" />
        </FormField>
      </form>
    </FormDrawer>
  );
}
