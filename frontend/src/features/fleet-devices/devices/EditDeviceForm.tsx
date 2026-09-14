import { useState } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Pencil } from "lucide-react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { Button } from "../../../shared/components/Button/Button";
import { ConfirmDialog } from "../../../shared/components/ConfirmDialog/ConfirmDialog";
import { FormDrawer } from "../../../shared/components/Drawer/FormDrawer";
import { FormField } from "../../../shared/components/FormField/FormField";
import { Input } from "../../../shared/components/Input/Input";
import { useToast } from "../../../shared/components/Toast/toastStore";
import { ApiError } from "../../../shared/api/types";
import { updateDeviceDetails, type Device, type UpdateDeviceDetailsInput } from "./api";
import styles from "./AssignDeviceForm.module.css";

const TERMINAL_ID_MAX_LENGTH = 64; // fleet_device.domain.value_objects.TerminalId
const MSISDN_MAX_LENGTH = 32;
const ICCID_MAX_LENGTH = 32;
const IMEI_PATTERN = /^\d{15}$/; // GSMA TS.06 — always exactly 15 digits

const schema = z.object({
  terminalId: z
    .string()
    .trim()
    .min(1, "Terminal ID is required")
    .max(TERMINAL_ID_MAX_LENGTH, `Terminal ID must be at most ${TERMINAL_ID_MAX_LENGTH} characters`),
  model: z.string().trim(),
  vendor: z.string().trim(),
  simMsisdn: z.string().trim().max(MSISDN_MAX_LENGTH, `Must be at most ${MSISDN_MAX_LENGTH} characters`),
  imei: z
    .string()
    .trim()
    .refine((value) => value === "" || IMEI_PATTERN.test(value), { message: "IMEI must be exactly 15 digits" }),
  iccid: z.string().trim().max(ICCID_MAX_LENGTH, `Must be at most ${ICCID_MAX_LENGTH} characters`),
});

type FormValues = z.infer<typeof schema>;

function defaultValuesFor(device: Device): FormValues {
  return {
    terminalId: device.terminalId,
    model: device.model ?? "",
    vendor: device.vendor ?? "",
    simMsisdn: device.simMsisdn ?? "",
    imei: device.imei ?? "",
    iccid: device.iccid ?? "",
  };
}

export interface EditDeviceFormProps {
  open: boolean;
  onClose: () => void;
  device: Device | null;
}

/**
 * Edits a device's identity/metadata fields — the capability this frontend was missing
 * entirely before this change (`PATCH /devices/{id}` previously supported only
 * `lifecycle_state`; see `UpdateDeviceRequest`'s own docstring on the backend).
 *
 * **Terminal ID gets a dedicated confirm step, everything else doesn't.** Changing it is the
 * one edit here with a real device-plane consequence: it must correctly propagate to
 * `device-gateway`'s live registry projection (`Device.update_terminal_id` ->
 * `DeviceTerminalIdChanged`, consumed by `DeviceRegistryProjection._apply_terminal_id_changed`)
 * — the whole reason this form exists rather than a raw database edit being the only way to
 * fix a mis-entered terminal ID. `model`/`vendor`/`simMsisdn`/`imei`/`iccid` are plain metadata
 * no device-plane consumer reads, so they submit directly like any other form.
 *
 * A `terminal_id` already claimed by another device surfaces as the backend's real
 * `ConflictError` (HTTP 409) — shown verbatim via toast, the same "never swallow a real
 * conflict" discipline `AssignDeviceForm`'s docstring already establishes for the device/vehicle
 * binding invariant.
 */
export function EditDeviceForm({ open, onClose, device }: EditDeviceFormProps) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [pendingTerminalId, setPendingTerminalId] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    reset,
    getValues,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    values: device ? defaultValuesFor(device) : undefined,
  });

  const mutation = useMutation({
    mutationFn: (values: FormValues) => {
      if (!device) {
        return Promise.reject(new Error("No device selected."));
      }
      const input: UpdateDeviceDetailsInput = {
        terminalId: values.terminalId,
        model: values.model,
        vendor: values.vendor,
        simMsisdn: values.simMsisdn || undefined,
        imei: values.imei || undefined,
        iccid: values.iccid || undefined,
      };
      return updateDeviceDetails(device.id, input);
    },
    onSuccess: (updated) => {
      queryClient.invalidateQueries({ queryKey: ["devices", "list"] });
      toast.success("Device updated", `${updated.terminalId} has been updated.`);
      setPendingTerminalId(null);
      onClose();
    },
    onError: (error) => {
      const message = error instanceof ApiError ? error.message : "Could not update the device.";
      toast.error("Update failed", message);
      setPendingTerminalId(null);
    },
  });

  function handleClose(): void {
    if (mutation.isPending) {
      return;
    }
    reset();
    mutation.reset();
    setPendingTerminalId(null);
    onClose();
  }

  const onValid = handleSubmit((values) => {
    if (device && values.terminalId !== device.terminalId) {
      setPendingTerminalId(values.terminalId);
      return;
    }
    mutation.mutate(values);
  });

  if (!open || !device) {
    return null;
  }

  return (
    <>
      <FormDrawer
        open={open}
        onClose={handleClose}
        icon={<Pencil size={22} />}
        iconTint="var(--color-brand-primary-tint)"
        iconColor="var(--color-brand-primary)"
        title="Edit device"
        subtitle={`Terminal ${device.terminalId}`}
        footer={
          <div className={styles.footerActions}>
            <Button type="button" variant="secondary" onClick={handleClose} disabled={mutation.isPending}>
              Cancel
            </Button>
            <Button type="button" variant="primary" loading={isSubmitting || mutation.isPending} onClick={onValid}>
              Save
            </Button>
          </div>
        }
      >
        <form className={styles.form} onSubmit={onValid} noValidate>
          <FormField
            label="Terminal ID"
            hint="The JT808 terminal/SIM identifier the device presents on the wire — read it off the unit."
            error={errors.terminalId?.message}
          >
            <Input invalid={!!errors.terminalId} {...register("terminalId")} />
          </FormField>
          <FormField label="Model" error={errors.model?.message}>
            <Input {...register("model")} />
          </FormField>
          <FormField label="Vendor" error={errors.vendor?.message}>
            <Input {...register("vendor")} />
          </FormField>
          <FormField label="SIM MSISDN" error={errors.simMsisdn?.message}>
            <Input {...register("simMsisdn")} />
          </FormField>
          <FormField label="IMEI" error={errors.imei?.message}>
            <Input {...register("imei")} />
          </FormField>
          <FormField label="ICCID" error={errors.iccid?.message}>
            <Input {...register("iccid")} />
          </FormField>
        </form>
      </FormDrawer>

      <ConfirmDialog
        open={pendingTerminalId !== null}
        title="Change this device's terminal ID?"
        description={
          <>
            Changing the terminal ID from <strong>{device.terminalId}</strong> to{" "}
            <strong>{pendingTerminalId}</strong> updates the live device-gateway registry
            immediately — the physical unit must present this exact value on JT/T 808 registration
            to be recognized.
          </>
        }
        tone="danger"
        confirmLabel="Change terminal ID"
        loading={mutation.isPending}
        onConfirm={() => mutation.mutate(getValues())}
        onCancel={() => setPendingTerminalId(null)}
      />
    </>
  );
}
