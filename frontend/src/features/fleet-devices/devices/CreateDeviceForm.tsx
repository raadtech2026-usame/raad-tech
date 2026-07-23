import { zodResolver } from "@hookform/resolvers/zod";
import { useMemo } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Cpu } from "lucide-react";
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
import { listOrganizationsForPicker, registerDevice } from "./api";
import styles from "./CreateDeviceForm.module.css";

// Matches `fleet_device.domain.value_objects`'s own `_ULID_PATTERN` (Crockford Base32, 26 chars).
const ULID_PATTERN = /^[0-9A-HJKMNP-TV-Z]{26}$/;
// `TerminalId`/`Msisdn` value objects (Database Design §5.2: `VARCHAR(64)`/`VARCHAR(32)`).
const TERMINAL_ID_MAX_LENGTH = 64;
const MSISDN_MAX_LENGTH = 32;

/** `organizationId` is only a real field for a principal with no organization of their own — see
 * `CreateVehicleForm.tsx`'s identical `buildSchema` precedent for the full reasoning. */
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
    terminalId: z
      .string()
      .trim()
      .min(1, "Terminal ID is required")
      .max(TERMINAL_ID_MAX_LENGTH, `Terminal ID must be at most ${TERMINAL_ID_MAX_LENGTH} characters`),
    model: z.string().trim(),
    vendor: z.string().trim(),
    simMsisdn: z
      .string()
      .trim()
      .max(MSISDN_MAX_LENGTH, `SIM number must be at most ${MSISDN_MAX_LENGTH} characters`),
  });
}

type FormValues = z.infer<ReturnType<typeof buildSchema>>;

const DEFAULT_VALUES: FormValues = {
  organizationId: "",
  terminalId: "",
  model: "",
  vendor: "",
  simMsisdn: "",
};

export interface CreateDeviceFormProps {
  open: boolean;
  onClose: () => void;
}

/**
 * `POST /devices` (`RegisterDeviceRequest`, `fleet_device.api.schemas`) exactly:
 * `organization_id`, `terminal_id`, `model`, `vendor`, `sim_msisdn`. The `organization_id`
 * picker-vs-auto-fill treatment mirrors `CreateVehicleForm.tsx`'s identical precedent exactly —
 * an Org Admin's own `principal.organizationId` is used directly; every other role that can
 * reach this form (`founder`/`support_staff` per the seeded RBAC matrix) sees a `GET
 * /organizations` picker instead.
 */
export function CreateDeviceForm({ open, onClose }: CreateDeviceFormProps) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const principal = useAuthStore((s) => s.principal);
  const ownOrganizationId = principal?.organizationId ?? null;
  const showOrganizationPicker = ownOrganizationId === null;

  const organizationsQuery = useQuery({
    queryKey: ["organizations", "device-create-picker"],
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
      registerDevice({
        organizationId: ownOrganizationId ?? values.organizationId,
        terminalId: values.terminalId,
        model: values.model || null,
        vendor: values.vendor || null,
        simMsisdn: values.simMsisdn || null,
      }),
    onSuccess: (device) => {
      queryClient.invalidateQueries({ queryKey: ["devices", "list"] });
      toast.success("Device registered", `Terminal ${device.terminalId} has been added.`);
      reset(DEFAULT_VALUES);
      onClose();
    },
    onError: (error) => {
      const message = error instanceof ApiError ? error.message : "Could not register the device.";
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
      icon={<Cpu size={22} />}
      iconTint="var(--color-brand-primary-tint)"
      iconColor="var(--color-brand-primary)"
      title="New device"
      subtitle="Register a GPS/MDVR terminal"
      footer={
        <div className={styles.footerActions}>
          <Button type="button" variant="secondary" onClick={handleClose} disabled={mutation.isPending}>
            Cancel
          </Button>
          <Button type="button" variant="primary" loading={isSubmitting || mutation.isPending} onClick={onValid}>
            Register device
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

        <FormField label="Terminal ID" hint="The JT808 terminal/SIM identifier the device presents on the wire." error={errors.terminalId?.message}>
          <Input placeholder="e.g. 013800000001" invalid={!!errors.terminalId} {...register("terminalId")} />
        </FormField>

        <FormField label="Model" hint="Optional.">
          <Input placeholder="e.g. JT808-X200" {...register("model")} />
        </FormField>

        <FormField label="Vendor" hint="Optional.">
          <Input placeholder="e.g. Concox" {...register("vendor")} />
        </FormField>

        <FormField label="SIM number" hint="Optional — masked in logs." error={errors.simMsisdn?.message}>
          <Input placeholder="e.g. +252612345678" invalid={!!errors.simMsisdn} {...register("simMsisdn")} />
        </FormField>
      </form>
    </FormDrawer>
  );
}
