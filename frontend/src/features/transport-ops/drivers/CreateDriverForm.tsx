import { zodResolver } from "@hookform/resolvers/zod";
import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Copy, UserRound } from "lucide-react";
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
import { listOrganizationsForPicker, registerDriver, type RegisterDriverResult } from "./api";
import styles from "./CreateDriverForm.module.css";

// Matches `transport_ops.domain.value_objects`'s own `_ULID_PATTERN`.
const ULID_PATTERN = /^[0-9A-HJKMNP-TV-Z]{26}$/;
// `iam.infra.models`'s `users.full_name` (`VARCHAR(200)`) — the linked login this form
// provisions, not a `transport_ops`-owned column (`Driver` has none of its own).
const FULL_NAME_MAX_LENGTH = 200;
// `iam.infra.models`'s `users.phone` (`VARCHAR(32)`), same E.164 convention `CreateParentForm.tsx`
// already applies for the identical `iam.User` provisioning call.
const E164_PATTERN = /^\+[1-9]\d{1,14}$/;
const PHONE_MAX_LENGTH = 32;
const PHONE_MESSAGE = "Phone must be E.164 format, e.g. +252612345678";
// `entities.py`'s `_LICENSE_NO_MAX_LENGTH` (Database Design §6.1 gives no explicit VARCHAR
// length for `drivers.license_no` — the domain layer's own 64-char ceiling, flagged there as
// not backend-schema-derived, mirrored here rather than inventing a different one).
const LICENSE_NO_MAX_LENGTH = 64;

function buildSchema(requiresOrganizationPicker: boolean) {
  return z
    .object({
      organizationId: requiresOrganizationPicker
        ? z
            .string()
            .trim()
            .min(1, "Organization is required")
            .refine((value) => ULID_PATTERN.test(value), {
              message: "Must be a valid organization ID (26-character ULID)",
            })
        : z.string(),
      fullName: z
        .string()
        .trim()
        .min(1, "Full name is required")
        .max(FULL_NAME_MAX_LENGTH, `Full name must be at most ${FULL_NAME_MAX_LENGTH} characters`),
      email: z.string().trim().refine((value) => value === "" || z.string().email().safeParse(value).success, {
        message: "Must be a valid email address",
      }),
      phone: z
        .string()
        .trim()
        .refine((value) => value === "" || (E164_PATTERN.test(value) && value.length <= PHONE_MAX_LENGTH), {
          message: PHONE_MESSAGE,
        }),
      licenseNo: z
        .string()
        .trim()
        .min(1, "License number is required")
        .max(LICENSE_NO_MAX_LENGTH, `License number must be at most ${LICENSE_NO_MAX_LENGTH} characters`),
    })
    .refine((values) => values.email !== "" || values.phone !== "", {
      message: "At least one of email or phone is required, to create the driver's login.",
      path: ["phone"],
    });
}

type FormValues = z.infer<ReturnType<typeof buildSchema>>;

const DEFAULT_VALUES: FormValues = { organizationId: "", fullName: "", email: "", phone: "", licenseNo: "" };

export interface CreateDriverFormProps {
  open: boolean;
  onClose: () => void;
}

/**
 * `POST /drivers` (`RegisterDriverRequest`, `transport_ops.api.schemas`) — ADR-0003: this form
 * no longer collects a `user_id`. The backend provisions the driver's login itself from
 * `full_name`/`email`/`phone` and returns a one-time temporary password
 * (`DriverCreatedResponse`), shown here exactly once (with a copy button) — mirroring
 * `CreateParentForm.tsx`'s identical two-phase (form, then success panel) shape for the same
 * underlying `iam.User` provisioning call. Neither `founder` nor `org_admin` needs `iam.users.read`
 * for this form anymore — there is no existing account to browse or paste an id for; the previous
 * "linked user" picker (and its `org_admin`-can't-browse-`iam.users` gap) no longer applies.
 *
 * `organization_id` follows `CreateVehicleForm.tsx`/`CreateParentForm.tsx`'s exact precedent: an
 * Org Admin's own `principal.organizationId` is used directly; `founder` (the only other role
 * holding `transport_ops.drivers.create`) sees a `GET /organizations` picker.
 */
export function CreateDriverForm({ open, onClose }: CreateDriverFormProps) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const principal = useAuthStore((s) => s.principal);
  const ownOrganizationId = principal?.organizationId ?? null;

  const showOrganizationPicker = ownOrganizationId === null;
  const [result, setResult] = useState<RegisterDriverResult | null>(null);
  const [registeredName, setRegisteredName] = useState("");
  const [copied, setCopied] = useState(false);

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
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: DEFAULT_VALUES,
  });

  const mutation = useMutation({
    mutationFn: (values: FormValues) =>
      registerDriver({
        organizationId: ownOrganizationId ?? values.organizationId,
        fullName: values.fullName,
        email: values.email || null,
        phone: values.phone || null,
        licenseNo: values.licenseNo,
      }),
    onSuccess: (registered, values) => {
      queryClient.invalidateQueries({ queryKey: ["drivers", "list"] });
      setResult(registered);
      setRegisteredName(values.fullName);
    },
    onError: (error) => {
      const message = error instanceof ApiError ? error.message : "Could not register the driver.";
      toast.error("Registration failed", message);
    },
  });

  function resetAll(): void {
    reset(DEFAULT_VALUES);
    mutation.reset();
    setResult(null);
    setRegisteredName("");
    setCopied(false);
  }

  function handleClose(): void {
    if (mutation.isPending) {
      return;
    }
    resetAll();
    onClose();
  }

  async function handleCopyPassword(): Promise<void> {
    if (!result) return;
    try {
      await navigator.clipboard.writeText(result.temporaryPassword);
      setCopied(true);
    } catch {
      toast.error("Could not copy", "Select and copy the password manually.");
    }
  }

  const onValid = handleSubmit((values) => mutation.mutate(values));

  const organizationOptions = organizationsQuery.data ?? [];
  const organizationError =
    errors.organizationId?.message ?? (organizationsQuery.isError ? "Could not load organizations." : undefined);

  if (result) {
    return (
      <FormDrawer
        open={open}
        onClose={handleClose}
        icon={<CheckCircle2 size={22} />}
        iconTint="var(--color-success-tint)"
        iconColor="var(--color-success)"
        title="Driver registered"
        subtitle={`${registeredName}'s login has been created`}
        footer={
          <div className={styles.footerActions}>
            <Button type="button" variant="primary" onClick={handleClose}>
              Done
            </Button>
          </div>
        }
      >
        <div className={styles.successPanel}>
          <p>
            Share this one-time password with <strong>{registeredName}</strong> — it will not be shown again.
          </p>
          <div className={styles.passwordRow}>
            <code className={styles.password}>{result.temporaryPassword}</code>
            <Button
              type="button"
              variant="secondary"
              size="sm"
              leadingIcon={<Copy size={13} />}
              onClick={() => void handleCopyPassword()}
            >
              {copied ? "Copied" : "Copy"}
            </Button>
          </div>
        </div>
      </FormDrawer>
    );
  }

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

        <FormField label="Full name" error={errors.fullName?.message}>
          <Input placeholder="e.g. Hassan Warsame" invalid={!!errors.fullName} {...register("fullName")} />
        </FormField>

        <FormField
          label="Email"
          hint="Optional if a phone is given — required for the login otherwise."
          error={errors.email?.message}
        >
          <Input type="email" placeholder="e.g. hassan@example.com" invalid={!!errors.email} {...register("email")} />
        </FormField>

        <FormField label="Phone" hint="E.164 format, e.g. +252612345678." error={errors.phone?.message}>
          <Input placeholder="+252612345678" invalid={!!errors.phone} {...register("phone")} />
        </FormField>

        <FormField label="License number" error={errors.licenseNo?.message}>
          <Input placeholder="e.g. DL-00231" invalid={!!errors.licenseNo} {...register("licenseNo")} />
        </FormField>
      </form>
    </FormDrawer>
  );
}
