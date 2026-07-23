import { zodResolver } from "@hookform/resolvers/zod";
import { useMemo } from "react";
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
import { useAuthStore } from "../../../shared/stores/authStore";
import { ApiError } from "../../../shared/api/types";
import { listDriverUsersForPicker, listOrganizationsForPicker, registerDriver } from "./api";
import styles from "./CreateDriverForm.module.css";

// Matches `transport_ops.domain.value_objects`'s own `_ULID_PATTERN`.
const ULID_PATTERN = /^[0-9A-HJKMNP-TV-Z]{26}$/;
// `entities.py`'s `_LICENSE_NO_MAX_LENGTH` (Database Design §6.1 gives no explicit VARCHAR
// length for `drivers.license_no` — the domain layer's own 64-char ceiling, flagged there as
// not backend-schema-derived, mirrored here rather than inventing a different one).
const LICENSE_NO_MAX_LENGTH = 64;

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
    userId: z
      .string()
      .trim()
      .min(1, "User is required")
      .refine((value) => ULID_PATTERN.test(value), {
        message: "Must be a valid user ID (26-character ULID)",
      }),
    licenseNo: z
      .string()
      .trim()
      .min(1, "License number is required")
      .max(LICENSE_NO_MAX_LENGTH, `License number must be at most ${LICENSE_NO_MAX_LENGTH} characters`),
  });
}

type FormValues = z.infer<ReturnType<typeof buildSchema>>;

const DEFAULT_VALUES: FormValues = { organizationId: "", userId: "", licenseNo: "" };

export interface CreateDriverFormProps {
  open: boolean;
  onClose: () => void;
}

/**
 * `POST /drivers` (`RegisterDriverRequest`, `transport_ops.api.schemas`) exactly:
 * `organization_id`, `user_id`, `license_no`.
 *
 * `organization_id` follows the exact precedent `CreateVehicleForm.tsx`/`CreateParentForm.tsx`
 * established: an Org Admin's own `principal.organizationId` is used directly; `founder` (the
 * only other role holding `transport_ops.drivers.create`) sees a `GET /organizations` picker.
 *
 * **The identical RBAC gap `CreateParentForm.tsx` already surfaced, reproduced here for
 * `Driver`:** `user_id` references an *existing* `iam.User` — the only way to discover a valid
 * one through this API is `GET /users` (`iam.users.read`), and `org_admin` — the only non-founder
 * role that can reach this form — holds no `iam.users.*` permission at all. `founder` gets a real
 * `GET /users` picker (`listDriverUsersForPicker`, scoped to the chosen organization and
 * `role: "driver"`); `org_admin` gets a plain text field for pasting a user id they already have
 * on hand, with format validation only.
 */
export function CreateDriverForm({ open, onClose }: CreateDriverFormProps) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const principal = useAuthStore((s) => s.principal);
  const ownOrganizationId = principal?.organizationId ?? null;

  const showOrganizationPicker = ownOrganizationId === null;
  // See this component's own docstring — only `founder` holds `iam.users.read` among the roles
  // that can reach this form at all.
  const canBrowseUsers = principal?.role === "founder";

  const organizationsQuery = useQuery({
    queryKey: ["organizations", "driver-create-picker"],
    queryFn: () => listOrganizationsForPicker(""),
    enabled: open && showOrganizationPicker,
    staleTime: 60_000,
  });

  const schema = useMemo(() => buildSchema(showOrganizationPicker), [showOrganizationPicker]);

  const {
    register,
    handleSubmit,
    reset,
    watch,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: DEFAULT_VALUES,
  });

  const watchedOrganizationId = watch("organizationId");
  const effectiveOrganizationId = ownOrganizationId ?? watchedOrganizationId;

  const usersQuery = useQuery({
    queryKey: ["users", "driver-create-picker", effectiveOrganizationId],
    queryFn: () => listDriverUsersForPicker(effectiveOrganizationId, ""),
    enabled: open && canBrowseUsers && !!effectiveOrganizationId,
    staleTime: 30_000,
  });

  const mutation = useMutation({
    mutationFn: (values: FormValues) =>
      registerDriver({
        organizationId: ownOrganizationId ?? values.organizationId,
        userId: values.userId,
        licenseNo: values.licenseNo,
      }),
    onSuccess: (driver) => {
      queryClient.invalidateQueries({ queryKey: ["drivers", "list"] });
      toast.success("Driver registered", `License ${driver.licenseNo} has been registered.`);
      reset(DEFAULT_VALUES);
      onClose();
    },
    onError: (error) => {
      const message = error instanceof ApiError ? error.message : "Could not register the driver.";
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

  const userOptions = usersQuery.data ?? [];
  const userError = errors.userId?.message ?? (usersQuery.isError ? "Could not load users." : undefined);

  return (
    <FormDrawer
      open={open}
      onClose={handleClose}
      icon={<UserRound size={22} />}
      iconTint="var(--color-brand-primary-tint)"
      iconColor="var(--color-brand-primary)"
      title="New driver"
      subtitle="Register a driver's transport-facing profile"
      footer={
        <div className={styles.footerActions}>
          <Button type="button" variant="secondary" onClick={handleClose} disabled={mutation.isPending}>
            Cancel
          </Button>
          <Button type="button" variant="primary" loading={isSubmitting || mutation.isPending} onClick={onValid}>
            Register driver
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

        {canBrowseUsers ? (
          <FormField
            label="Linked user"
            hint="An existing account with the Driver role. Only accounts in the selected organization are shown."
            error={userError}
          >
            <Select
              {...register("userId")}
              disabled={!effectiveOrganizationId || usersQuery.isLoading}
              aria-label="Linked user"
            >
              <option value="">
                {!effectiveOrganizationId
                  ? "Select an organization first"
                  : usersQuery.isLoading
                    ? "Loading users…"
                    : "Select a user"}
              </option>
              {userOptions.map((user) => (
                <option key={user.id} value={user.id}>
                  {user.fullName}
                  {user.email ? ` — ${user.email}` : user.phone ? ` — ${user.phone}` : ""}
                </option>
              ))}
            </Select>
          </FormField>
        ) : (
          <FormField
            label="Linked user ID"
            hint="Paste the user ID of an existing account with the Driver role — invite one first via Users & Roles if you don't have one yet."
            error={userError}
          >
            <Input
              placeholder="e.g. 01ARZ3NDEKTSV4RRFFQ69G5FAV"
              invalid={!!errors.userId}
              aria-label="Linked user ID"
              {...register("userId")}
            />
          </FormField>
        )}

        <FormField label="License number" error={errors.licenseNo?.message}>
          <Input placeholder="e.g. DL-00231" invalid={!!errors.licenseNo} {...register("licenseNo")} />
        </FormField>
      </form>
    </FormDrawer>
  );
}
