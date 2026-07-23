import { zodResolver } from "@hookform/resolvers/zod";
import { useMemo } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Truck } from "lucide-react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { Button } from "../../../shared/components/Button/Button";
import { FormDrawer } from "../../../shared/components/Drawer/FormDrawer";
import { FormField } from "../../../shared/components/FormField/FormField";
import { Input } from "../../../shared/components/Input/Input";
import { Select } from "../../../shared/components/Select/Select";
import { useToast } from "../../../shared/components/Toast/toastStore";
import { useAuthStore } from "../../../shared/stores/authStore";
import { ApiError } from "../../../shared/api/types";
import { listOrganizationsForPicker, registerVehicle } from "./api";
import styles from "./CreateVehicleForm.module.css";

// Matches `fleet_device.domain.value_objects`'s own `_ULID_PATTERN` (Crockford Base32, 26 chars)
// — client-side format validation of the same real domain invariant, not a new business rule
// (mirrors `CreateOrganizationForm.tsx`'s identical precedent).
const ULID_PATTERN = /^[0-9A-HJKMNP-TV-Z]{26}$/;

/** `organizationId` is only a real form field for a signed-in principal with no organization of
 * their own (see this component's own docstring) — built as a function of that, rather than one
 * static schema, so the picker is properly required/validated only when it's actually rendered. */
function buildSchema(requiresOrganizationPicker: boolean) {
  return z.object({
    organizationId: requiresOrganizationPicker
      ? z
          .string()
          .trim()
          .min(1, "Organization is required")
          .refine((value) => ULID_PATTERN.test(value), {
            message: "Must be a valid organization ID (26-character ULID)",
          })
      : z.string(),
    plateNo: z.string().trim().min(1, "Plate number is required"),
    label: z.string().trim(),
    capacity: z
      .string()
      .trim()
      .refine((value) => value === "" || /^[1-9]\d*$/.test(value), {
        message: "Capacity must be a positive whole number",
      }),
  });
}

type FormValues = z.infer<ReturnType<typeof buildSchema>>;

const DEFAULT_VALUES: FormValues = { organizationId: "", plateNo: "", label: "", capacity: "" };

export interface CreateVehicleFormProps {
  open: boolean;
  onClose: () => void;
}

/**
 * `POST /vehicles` (`RegisterVehicleRequest`, `fleet_device.api.schemas`) exactly:
 * `organization_id`, `plate_no`, `label`, `capacity`.
 *
 * `organization_id` follows the exact precedent `InviteUserForm.tsx` established for
 * `CreateUserRequest`: the schema requires it unconditionally (`api/schemas.py`'s own docstring
 * — "constraining an Org Admin to their own organization is the pending tenant/scope
 * authorization layer's job, not a schema rule"), so this form supplies it two ways depending on
 * who is signed in — an Org Admin's `principal.organizationId` is always set (it's one of the
 * three `_ORG_SCOPED_ROLES`, `iam.domain.entities`) and is used directly, with no picker shown at
 * all; every other role that can reach this form (only `founder` per the seeded RBAC matrix)
 * has no organization of their own, so a `GET /organizations` picker (this module's own
 * self-contained `listOrganizationsForPicker`) is shown instead.
 */
export function CreateVehicleForm({ open, onClose }: CreateVehicleFormProps) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const principal = useAuthStore((s) => s.principal);
  const ownOrganizationId = principal?.organizationId ?? null;

  const showOrganizationPicker = ownOrganizationId === null;

  const organizationsQuery = useQuery({
    queryKey: ["organizations", "vehicle-create-picker"],
    queryFn: () => listOrganizationsForPicker(""),
    enabled: open && showOrganizationPicker,
    staleTime: 60_000,
  });

  const schema = useMemo(() => buildSchema(showOrganizationPicker), [showOrganizationPicker]);

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
    mutationFn: (values: FormValues) =>
      registerVehicle({
        organizationId: ownOrganizationId ?? values.organizationId,
        plateNo: values.plateNo,
        label: values.label || null,
        capacity: values.capacity ? Number(values.capacity) : null,
      }),
    onSuccess: (vehicle) => {
      queryClient.invalidateQueries({ queryKey: ["vehicles", "list"] });
      toast.success("Vehicle registered", `${vehicle.plateNo} has been added.`);
      reset(DEFAULT_VALUES);
      onClose();
    },
    onError: (error) => {
      const message = error instanceof ApiError ? error.message : "Could not register the vehicle.";
      toast.error("Registration failed", message);
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

  const organizationOptions = organizationsQuery.data ?? [];
  const organizationError =
    errors.organizationId?.message ?? (organizationsQuery.isError ? "Could not load organizations." : undefined);

  return (
    <FormDrawer
      open={open}
      onClose={handleClose}
      icon={<Truck size={22} />}
      iconTint="var(--color-brand-primary-tint)"
      iconColor="var(--color-brand-primary)"
      title="New vehicle"
      subtitle="Register a bus as a fleet asset"
      footer={
        <div className={styles.footerActions}>
          <Button type="button" variant="secondary" onClick={handleClose} disabled={mutation.isPending}>
            Cancel
          </Button>
          <Button type="button" variant="primary" loading={isSubmitting || mutation.isPending} onClick={onValid}>
            Register vehicle
          </Button>
        </div>
      }
    >
      <form className={styles.form} onSubmit={onValid} noValidate>
        {showOrganizationPicker && (
          <FormField label="Organization" error={organizationError}>
            <Select {...register("organizationId")} disabled={organizationsQuery.isLoading} aria-label="Organization">
              <option value="">
                {organizationsQuery.isLoading ? "Loading organizations…" : "Select an organization"}
              </option>
              {organizationOptions.map((org) => (
                <option key={org.id} value={org.id}>
                  {org.name}
                </option>
              ))}
            </Select>
          </FormField>
        )}

        <FormField label="Plate number" error={errors.plateNo?.message}>
          <Input placeholder="e.g. ABC-1234" invalid={!!errors.plateNo} {...register("plateNo")} />
        </FormField>

        <FormField label="Label" hint="Optional — a friendly name, e.g. route or unit number.">
          <Input placeholder="e.g. Bus 12" {...register("label")} />
        </FormField>

        <FormField label="Capacity" hint="Optional — number of seats." error={errors.capacity?.message}>
          <Input placeholder="e.g. 32" invalid={!!errors.capacity} {...register("capacity")} />
        </FormField>
      </form>
    </FormDrawer>
  );
}
