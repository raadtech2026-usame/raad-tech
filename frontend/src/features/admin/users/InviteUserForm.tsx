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
import { useToast } from "../../../shared/components/Toast/toastStore";
import { ApiError, type Role } from "../../../shared/api/types";
import { getRoleDisplay } from "../../../shared/auth/roleDisplay";
import { ASSIGNABLE_ROLES, inviteUser, isOrgScopedRole, listOrganizationsForPicker } from "./api";
import styles from "./InviteUserForm.module.css";

// Matches `iam.domain.value_objects`'s own `_EMAIL_PATTERN`/`_E164_PATTERN`/`_ULID_PATTERN` —
// client-side format validation of the same real domain invariants, not a new business rule
// (mirrors `CreateOrganizationForm.tsx`'s identical ULID-regex precedent).
const EMAIL_PATTERN = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
const E164_PATTERN = /^\+[1-9]\d{1,14}$/;
const ULID_PATTERN = /^[0-9A-HJKMNP-TV-Z]{26}$/;

const schema = z
  .object({
    fullName: z.string().trim().min(1, "Full name is required"),
    role: z
      .string()
      .min(1, "Role is required")
      .refine((value) => (ASSIGNABLE_ROLES as readonly string[]).includes(value), {
        message: "Select a valid role",
      }),
    email: z
      .string()
      .trim()
      .refine((value) => value === "" || EMAIL_PATTERN.test(value), {
        message: "Enter a valid email address",
      }),
    phone: z
      .string()
      .trim()
      .refine((value) => value === "" || E164_PATTERN.test(value), {
        message: "Phone must be E.164 format, e.g. +252612345678",
      }),
    organizationId: z
      .string()
      .trim()
      .refine((value) => value === "" || ULID_PATTERN.test(value), {
        message: "Must be a valid organization ID (26-character ULID)",
      }),
  })
  .superRefine((values, ctx) => {
    // `User._validate_identity_and_scope` (`iam.domain.entities.py`): "at least one of email or
    // phone must be present" — a real `DomainError` this form validates ahead of the request,
    // not an invented client-only rule.
    if (!values.email && !values.phone) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["email"],
        message: "Provide an email or a phone number",
      });
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["phone"],
        message: "Provide an email or a phone number",
      });
    }
    // Same aggregate invariant's other half: org-scoped roles require `organization_id`, staff
    // roles must not have one — enforced client-side only for the "required" direction, since
    // `orgScoped` roles are the only ones this form even shows the organization field for.
    if (isOrgScopedRole(values.role as Role) && !values.organizationId) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["organizationId"],
        message: "Organization is required for this role",
      });
    }
  });

type FormValues = z.infer<typeof schema>;

const DEFAULT_VALUES: FormValues = { fullName: "", role: "", email: "", phone: "", organizationId: "" };

export interface InviteUserFormProps {
  open: boolean;
  onClose: () => void;
}

/**
 * `POST /users` (`CreateUserRequest`, named "Invite a new user" in the backend's own route
 * summary — `modules/iam/api/routers.py`) exactly: `full_name`, `role`, `email`, `phone`,
 * `organization_id`. No "resend invite"/"set password" affordance is offered: `User.invite()`
 * creates a passwordless, `status=invited` account (Database Design §4.3's nullable
 * `password_hash`) and this backend has no documented invite-resend/email-delivery use-case at
 * all — inventing one would be exactly the kind of ungrounded capability
 * `.claude/rules/workflow.md` #8 forbids.
 *
 * The role picker offers all seven `Role` values (`api.ts`'s `ASSIGNABLE_ROLES`) — confirmed
 * from `InviteUserCommand`/`User.invite`/`User._validate_identity_and_scope`
 * (`modules/iam/domain/entities.py`) that there is **no** role-to-role assignment restriction at
 * the schema/domain layer (nothing stops a request from assigning `founder` to someone else);
 * the only real gate is the flat `require_permission(Permission("iam.users.create"))` check,
 * which today only `founder` holds (`api.ts`'s own module docstring has the full RBAC-matrix
 * citation) — `UsersPage` only renders this drawer's trigger for that role, but this form itself
 * doesn't re-narrow the role list, since the backend doesn't either.
 */
export function InviteUserForm({ open, onClose }: InviteUserFormProps) {
  const toast = useToast();
  const queryClient = useQueryClient();

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

  const role = watch("role");
  const orgScoped = role !== "" && isOrgScopedRole(role as Role);

  const organizationsQuery = useQuery({
    queryKey: ["organizations", "invite-picker"],
    queryFn: () => listOrganizationsForPicker(""),
    enabled: open && orgScoped,
    staleTime: 60_000,
  });

  const mutation = useMutation({
    mutationFn: (values: FormValues) =>
      inviteUser({
        fullName: values.fullName,
        role: values.role as Role,
        email: values.email || null,
        phone: values.phone || null,
        organizationId: isOrgScopedRole(values.role as Role) ? values.organizationId : null,
      }),
    onSuccess: (user) => {
      // Matches every other feature's mutation convention (roadmap §3.2): invalidate the exact
      // query key affected, not a blanket `invalidateQueries()`.
      queryClient.invalidateQueries({ queryKey: ["users", "list"] });
      toast.success("User invited", `${user.fullName} has been added.`);
      reset(DEFAULT_VALUES);
      onClose();
    },
    onError: (error) => {
      const message = error instanceof ApiError ? error.message : "Could not invite the user.";
      toast.error("Invite failed", message);
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
      icon={<UserPlus size={22} />}
      iconTint="var(--color-brand-primary-tint)"
      iconColor="var(--color-brand-primary)"
      title="Invite user"
      subtitle="Add a new account and assign its role"
      footer={
        <div className={styles.footerActions}>
          <Button type="button" variant="secondary" onClick={handleClose} disabled={mutation.isPending}>
            Cancel
          </Button>
          <Button type="button" variant="primary" loading={isSubmitting || mutation.isPending} onClick={onValid}>
            Invite user
          </Button>
        </div>
      }
    >
      <form className={styles.form} onSubmit={onValid} noValidate>
        <FormField label="Full name" error={errors.fullName?.message}>
          <Input placeholder="e.g. Amina Hassan" invalid={!!errors.fullName} {...register("fullName")} />
        </FormField>

        <FormField label="Role" error={errors.role?.message}>
          <Select {...register("role")} aria-label="Role">
            <option value="">Select a role</option>
            {ASSIGNABLE_ROLES.map((value) => (
              <option key={value} value={value}>
                {getRoleDisplay(value).label}
              </option>
            ))}
          </Select>
        </FormField>

        {orgScoped && (
          <FormField label="Organization" error={organizationError}>
            <Select
              {...register("organizationId")}
              disabled={organizationsQuery.isLoading || organizationsQuery.isError}
              aria-label="Organization"
            >
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

        <FormField
          label="Email"
          hint="Provide an email or a phone number (at least one)."
          error={errors.email?.message}
        >
          <Input type="email" placeholder="name@example.com" invalid={!!errors.email} {...register("email")} />
        </FormField>

        <FormField label="Phone" hint="E.164 format, e.g. +252612345678." error={errors.phone?.message}>
          <Input placeholder="+252612345678" invalid={!!errors.phone} {...register("phone")} />
        </FormField>
      </form>
    </FormDrawer>
  );
}
