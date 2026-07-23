import { zodResolver } from "@hookform/resolvers/zod";
import { useMemo } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Navigation } from "lucide-react";
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
import { createRoute, listOrganizationsForPicker } from "./api";
import styles from "./CreateRouteForm.module.css";

// Matches `transport_ops.domain.value_objects`'s own `_ULID_PATTERN`.
const ULID_PATTERN = /^[0-9A-HJKMNP-TV-Z]{26}$/;
// `entities.py`'s `_ROUTE_NAME_MAX_LENGTH` (Database Design §6.5: no explicit VARCHAR length
// documented — the domain layer's own 160-char ceiling, mirrored here rather than inventing a
// different one).
const ROUTE_NAME_MAX_LENGTH = 160;

/** `organizationId` is only a real form field for a signed-in principal with no organization of
 * their own — see `CreateVehicleForm.tsx`'s identical `buildSchema` precedent. */
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
    name: z
      .string()
      .trim()
      .min(1, "Route name is required")
      .max(ROUTE_NAME_MAX_LENGTH, `Route name must be at most ${ROUTE_NAME_MAX_LENGTH} characters`),
  });
}

type FormValues = z.infer<ReturnType<typeof buildSchema>>;

const DEFAULT_VALUES: FormValues = { organizationId: "", name: "" };

export interface CreateRouteFormProps {
  open: boolean;
  onClose: () => void;
}

/**
 * `POST /routes` (`CreateRouteRequest`, `transport_ops.api.schemas`) exactly: `organization_id`,
 * `name`. `organization_id` follows the exact precedent `CreateVehicleForm.tsx`/
 * `CreateStudentForm.tsx` established: an Org Admin's own `principal.organizationId` is used
 * directly; every other role that can reach this form (only `founder` per the seeded RBAC
 * matrix) sees a `GET /organizations` picker instead.
 */
export function CreateRouteForm({ open, onClose }: CreateRouteFormProps) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const principal = useAuthStore((s) => s.principal);
  const ownOrganizationId = principal?.organizationId ?? null;

  const showOrganizationPicker = ownOrganizationId === null;

  const organizationsQuery = useQuery({
    queryKey: ["organizations", "route-create-picker"],
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
      createRoute({
        organizationId: ownOrganizationId ?? values.organizationId,
        name: values.name,
      }),
    onSuccess: (route) => {
      queryClient.invalidateQueries({ queryKey: ["routes", "list"] });
      toast.success("Route created", `${route.name} has been added.`);
      reset(DEFAULT_VALUES);
      onClose();
    },
    onError: (error) => {
      const message = error instanceof ApiError ? error.message : "Could not create the route.";
      toast.error("Create failed", message);
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
      icon={<Navigation size={22} />}
      iconTint="var(--color-brand-primary-tint)"
      iconColor="var(--color-brand-primary)"
      title="New route"
      subtitle="Create a route to add stops to"
      footer={
        <div className={styles.footerActions}>
          <Button type="button" variant="secondary" onClick={handleClose} disabled={mutation.isPending}>
            Cancel
          </Button>
          <Button type="button" variant="primary" loading={isSubmitting || mutation.isPending} onClick={onValid}>
            Create route
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

        <FormField label="Route name" error={errors.name?.message}>
          <Input placeholder="e.g. Morning Route A" invalid={!!errors.name} {...register("name")} />
        </FormField>
      </form>
    </FormDrawer>
  );
}
