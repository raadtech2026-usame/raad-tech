import { zodResolver } from "@hookform/resolvers/zod";
import { useMemo } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Contact } from "lucide-react";
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
import { listOrganizationsForPicker, listParentUsersForPicker, registerParent } from "./api";
import styles from "./CreateParentForm.module.css";

// Matches `transport_ops.domain.value_objects`'s own `_ULID_PATTERN`.
const ULID_PATTERN = /^[0-9A-HJKMNP-TV-Z]{26}$/;
// `value_objects.py`'s `_E164_PATTERN`/`_PHONE_MAX_LENGTH` (Database Design: `phone VARCHAR(32)`).
const E164_PATTERN = /^\+[1-9]\d{1,14}$/;
const PHONE_MAX_LENGTH = 32;
// `entities.py`'s `_PARENT_FULL_NAME_MAX_LENGTH` (Database Design §6.3: `full_name VARCHAR(200)`).
const FULL_NAME_MAX_LENGTH = 200;

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
    fullName: z
      .string()
      .trim()
      .min(1, "Full name is required")
      .max(FULL_NAME_MAX_LENGTH, `Full name must be at most ${FULL_NAME_MAX_LENGTH} characters`),
    phone: z
      .string()
      .trim()
      .refine((value) => value === "" || (E164_PATTERN.test(value) && value.length <= PHONE_MAX_LENGTH), {
        message: "Phone must be E.164 format, e.g. +252612345678",
      }),
  });
}

type FormValues = z.infer<ReturnType<typeof buildSchema>>;

const DEFAULT_VALUES: FormValues = { organizationId: "", userId: "", fullName: "", phone: "" };

export interface CreateParentFormProps {
  open: boolean;
  onClose: () => void;
}

/**
 * `POST /parents` (`RegisterParentRequest`, `transport_ops.api.schemas`) exactly:
 * `organization_id`, `user_id`, `full_name`, `phone`.
 *
 * `organization_id` follows the exact precedent `CreateVehicleForm.tsx`/`CreateStudentForm.tsx`
 * established: an Org Admin's own `principal.organizationId` is used directly; `founder` (the
 * only other role holding `transport_ops.parents.create`) sees a `GET /organizations` picker.
 *
 * **A real RBAC gap this input surfaced, not silently worked around:** `user_id` references an
 * *existing* `iam.User` — the only way to discover a valid one through this API is
 * `GET /users` (`iam.users.read`). Per the seeded RBAC matrix (`migrations/versions/
 * 20260721_0900_5437a5d1651b_iam_create_role_permissions_table.py`), `founder` holds
 * `iam.users.read` (part of `_ALL_PERMISSIONS`) but **`org_admin` — the only non-founder role
 * that can reach this form — holds no `iam.users.*` permission at all** (`_ORG_ADMIN_PERMISSIONS`
 * lists none). `org_admin` therefore has no way to browse users anywhere in this frontend either
 * (`/org/users` is still a `PlaceholderPage`, `app/router.tsx`, for the identical reason). This
 * form resolves that split honestly rather than building a picker that would silently 403 for
 * its primary persona: `founder` gets a real `GET /users` picker (`listParentUsersForPicker`,
 * scoped to the chosen organization and `role: "parent"`); every other role (`org_admin`) gets a
 * plain text field for pasting a user id they already have on hand (e.g. from inviting the user
 * via Users & Roles beforehand), with format validation only — never a picker that cannot
 * actually list anything for that role.
 */
export function CreateParentForm({ open, onClose }: CreateParentFormProps) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const principal = useAuthStore((s) => s.principal);
  const ownOrganizationId = principal?.organizationId ?? null;

  const showOrganizationPicker = ownOrganizationId === null;
  // See this component's own docstring — only `founder` holds `iam.users.read` among the roles
  // that can reach this form at all.
  const canBrowseUsers = principal?.role === "founder";

  const organizationsQuery = useQuery({
    queryKey: ["organizations", "parent-create-picker"],
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
    queryKey: ["users", "parent-create-picker", effectiveOrganizationId],
    queryFn: () => listParentUsersForPicker(effectiveOrganizationId, ""),
    enabled: open && canBrowseUsers && !!effectiveOrganizationId,
    staleTime: 30_000,
  });

  const mutation = useMutation({
    mutationFn: (values: FormValues) =>
      registerParent({
        organizationId: ownOrganizationId ?? values.organizationId,
        userId: values.userId,
        fullName: values.fullName,
        phone: values.phone || null,
      }),
    onSuccess: (parent) => {
      queryClient.invalidateQueries({ queryKey: ["parents", "list"] });
      toast.success("Parent registered", `${parent.fullName} has been registered.`);
      reset(DEFAULT_VALUES);
      onClose();
    },
    onError: (error) => {
      const message = error instanceof ApiError ? error.message : "Could not register the parent.";
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
      icon={<Contact size={22} />}
      iconTint="var(--color-brand-primary-tint)"
      iconColor="var(--color-brand-primary)"
      title="New parent"
      subtitle="Register a parent's transport-facing profile"
      footer={
        <div className={styles.footerActions}>
          <Button type="button" variant="secondary" onClick={handleClose} disabled={mutation.isPending}>
            Cancel
          </Button>
          <Button type="button" variant="primary" loading={isSubmitting || mutation.isPending} onClick={onValid}>
            Register parent
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
            hint="An existing account with the Parent role. Only accounts in the selected organization are shown."
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
            hint="Paste the user ID of an existing account with the Parent role — invite one first via Users & Roles if you don't have one yet."
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

        <FormField label="Full name" error={errors.fullName?.message}>
          <Input placeholder="e.g. Fatima Ali" invalid={!!errors.fullName} {...register("fullName")} />
        </FormField>

        <FormField label="Phone" hint="Optional — E.164 format." error={errors.phone?.message}>
          <Input placeholder="e.g. +252612345678" invalid={!!errors.phone} {...register("phone")} />
        </FormField>
      </form>
    </FormDrawer>
  );
}
