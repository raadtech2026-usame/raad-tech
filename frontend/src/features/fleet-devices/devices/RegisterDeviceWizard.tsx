import { zodResolver } from "@hookform/resolvers/zod";
import { Fragment, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Circle, Cpu, Loader2, X } from "lucide-react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { Button } from "../../../shared/components/Button/Button";
import { FormDrawer } from "../../../shared/components/Drawer/FormDrawer";
import { FormField } from "../../../shared/components/FormField/FormField";
import { Input } from "../../../shared/components/Input/Input";
import { Select } from "../../../shared/components/Select/Select";
import { useToast } from "../../../shared/components/Toast/toastStore";
import { ApiError } from "../../../shared/api/types";
import {
  activateDevice,
  assignDeviceToVehicle,
  getDevice,
  listOrganizationsForPicker,
  listVehiclesForPicker,
  registerDevice,
  type Device,
  type OrganizationOption,
  type VehicleOption,
} from "./api";
import styles from "./RegisterDeviceWizard.module.css";

// Matches `fleet_device.domain.value_objects`'s own `_ULID_PATTERN` (Crockford Base32, 26 chars).
const ULID_PATTERN = /^[0-9A-HJKMNP-TV-Z]{26}$/;
const TERMINAL_ID_MAX_LENGTH = 64; // Database Design §5.2: VARCHAR(64)
const MSISDN_MAX_LENGTH = 32;
const ICCID_MAX_LENGTH = 32;
const SERIAL_NUMBER_MAX_LENGTH = 64;
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
  serialNumber: z
    .string()
    .trim()
    .max(SERIAL_NUMBER_MAX_LENGTH, `Must be at most ${SERIAL_NUMBER_MAX_LENGTH} characters`),
  organizationId: z
    .string()
    .min(1, "Organization is required")
    .refine((value) => ULID_PATTERN.test(value), { message: "Select a valid organization" }),
  vehicleId: z
    .string()
    .min(1, "Vehicle is required")
    .refine((value) => ULID_PATTERN.test(value), { message: "Select a valid vehicle" }),
});

type FormValues = z.infer<typeof schema>;

const DEFAULT_VALUES: FormValues = {
  terminalId: "",
  model: "",
  vendor: "",
  simMsisdn: "",
  imei: "",
  iccid: "",
  serialNumber: "",
  organizationId: "",
  vehicleId: "",
};

type WizardStep = "hardware" | "organization" | "vehicle" | "register" | "verify";
type StepState = "idle" | "pending" | "done" | "error";

const STEP_ORDER: WizardStep[] = ["hardware", "organization", "vehicle", "register", "verify"];
const STEP_LABELS: Record<WizardStep, string> = {
  hardware: "Hardware",
  organization: "Organization",
  vehicle: "Vehicle",
  register: "Register",
  verify: "Verify",
};

export interface RegisterDeviceWizardProps {
  open: boolean;
  onClose: () => void;
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback;
}

/**
 * The RAAD technician's guided device-onboarding flow (Device Domain Overhaul architecture
 * review) — replaces `CreateDeviceForm`'s role in the creation path. Reachable only from
 * `/platform/devices` (RAAD-staff-only; `org_admin` holds no `fleet_device.devices.*`
 * permission at all as of migration `22e94bc4e924`).
 *
 * **Step order reconciles a real mismatch between the requested UX and the backend's actual
 * state machine.** The requested flow collects information in the order hardware → organization
 * → vehicle → activate → verify, but `entities.Device`'s lifecycle requires
 * `registered → activated → assigned` — a device cannot be assigned to a vehicle while still
 * `registered` (`mark_assigned` raises `RuleViolationError` outside `activated`). This wizard
 * resolves that by *collecting* the target vehicle in step 3 (before anything is submitted) but
 * only *executing* the assignment call after activation, in the "Register" step's sequence
 * (register → activate → assign) — the UI order the technician experiences matches the request;
 * the network call order matches the domain model. Neither was silently changed to fit the
 * other.
 *
 * **The "Register" step is resumable, not all-or-nothing.** `register`/`activate`/`assign` are
 * three separate HTTP calls with no shared transaction — a failure partway through (e.g.
 * activation succeeds, assignment 409s because the vehicle already has a device) must not force
 * re-registering the same terminal_id (which would itself 409). `runSequence` below only
 * (re)attempts whichever of the three sub-steps hasn't already reached `"done"`, tracked by
 * `deviceId` once registration succeeds — the visible checklist and the "Retry" button both key
 * off that same resumable state.
 *
 * **Verify is an honest pending state, not a fabricated live check** (confirmed with the user
 * before implementing) — no real JT808 device-plane bridge exists in this environment yet
 * (B1/B2, tracked separately), so there is no live connectivity signal to check. This step
 * re-fetches the device and shows its real `lifecycle_state`/`last_seen_at`, stating plainly
 * that live connectivity confirmation isn't available yet rather than showing a fake "online"
 * indicator — the same "fail loudly, don't fake it" posture this codebase applies everywhere
 * else (`CLAUDE.md`'s own repeated framing).
 */
export function RegisterDeviceWizard({ open, onClose }: RegisterDeviceWizardProps) {
  const toast = useToast();
  const queryClient = useQueryClient();

  const [step, setStep] = useState<WizardStep>("hardware");
  const [deviceId, setDeviceId] = useState<string | null>(null);
  const [registerState, setRegisterState] = useState<StepState>("idle");
  const [activateState, setActivateState] = useState<StepState>("idle");
  const [assignState, setAssignState] = useState<StepState>("idle");
  const [stepError, setStepError] = useState<string | null>(null);
  const [verifiedDevice, setVerifiedDevice] = useState<Device | null>(null);

  const executionStarted = registerState !== "idle";

  const {
    register,
    handleSubmit,
    reset,
    trigger,
    watch,
    formState: { errors },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: DEFAULT_VALUES,
  });

  const values = watch();

  const organizationsQuery = useQuery({
    queryKey: ["organizations", "device-wizard-picker"],
    queryFn: () => listOrganizationsForPicker(""),
    enabled: open && (step === "organization" || step === "hardware"),
    staleTime: 60_000,
  });

  const vehiclesQuery = useQuery({
    queryKey: ["vehicles", "device-wizard-picker", values.organizationId],
    queryFn: () => listVehiclesForPicker(values.organizationId, ""),
    enabled: open && step === "vehicle" && !!values.organizationId,
    staleTime: 30_000,
  });

  const selectedOrganization = (organizationsQuery.data ?? []).find(
    (org: OrganizationOption) => org.id === values.organizationId,
  );
  const selectedVehicle = (vehiclesQuery.data ?? []).find(
    (vehicle: VehicleOption) => vehicle.id === values.vehicleId,
  );

  function resetWizard(): void {
    reset(DEFAULT_VALUES);
    setStep("hardware");
    setDeviceId(null);
    setRegisterState("idle");
    setActivateState("idle");
    setAssignState("idle");
    setStepError(null);
    setVerifiedDevice(null);
  }

  function handleClose(): void {
    if (registerState === "pending" || activateState === "pending" || assignState === "pending") {
      return;
    }
    resetWizard();
    onClose();
  }

  async function goToStep(target: WizardStep): Promise<void> {
    const currentIndex = STEP_ORDER.indexOf(step);
    const targetIndex = STEP_ORDER.indexOf(target);
    if (targetIndex < currentIndex) {
      setStep(target);
      return;
    }
    const fieldsForStep: Record<WizardStep, (keyof FormValues)[]> = {
      hardware: ["terminalId", "model", "vendor", "simMsisdn", "imei", "iccid", "serialNumber"],
      organization: ["organizationId"],
      vehicle: ["vehicleId"],
      register: [],
      verify: [],
    };
    const valid = await trigger(fieldsForStep[step]);
    if (valid) {
      setStep(target);
    }
  }

  async function runSequence(values: FormValues): Promise<void> {
    setStepError(null);
    let currentDeviceId = deviceId;

    if (registerState !== "done") {
      setRegisterState("pending");
      try {
        const device = await registerDevice({
          organizationId: values.organizationId,
          terminalId: values.terminalId,
          model: values.model || null,
          vendor: values.vendor || null,
          simMsisdn: values.simMsisdn || null,
          imei: values.imei || null,
          iccid: values.iccid || null,
          serialNumber: values.serialNumber || null,
        });
        currentDeviceId = device.id;
        setDeviceId(device.id);
        setRegisterState("done");
      } catch (error) {
        setRegisterState("error");
        setStepError(errorMessage(error, "Could not register the device."));
        return;
      }
    }

    if (activateState !== "done" && currentDeviceId) {
      setActivateState("pending");
      try {
        await activateDevice(currentDeviceId);
        setActivateState("done");
      } catch (error) {
        setActivateState("error");
        setStepError(errorMessage(error, "Could not activate the device."));
        return;
      }
    }

    if (assignState !== "done" && currentDeviceId) {
      setAssignState("pending");
      try {
        await assignDeviceToVehicle(currentDeviceId, values.vehicleId);
        setAssignState("done");
      } catch (error) {
        setAssignState("error");
        setStepError(errorMessage(error, "Could not assign the device to the vehicle."));
        return;
      }
    }

    queryClient.invalidateQueries({ queryKey: ["devices", "list"] });
    toast.success("Device onboarded", `${values.terminalId} is registered, activated, and assigned.`);

    if (currentDeviceId) {
      const finalDevice = await getDevice(currentDeviceId);
      setVerifiedDevice(finalDevice);
    }
    setStep("verify");
  }

  const onSubmitRegistration = handleSubmit(runSequence);

  function stepIcon(state: StepState) {
    if (state === "done") return <Check size={16} color="var(--color-success)" />;
    if (state === "pending") return <Loader2 size={16} className={styles.spin} />;
    if (state === "error") return <X size={16} color="var(--color-danger)" />;
    return <Circle size={16} color="var(--color-text-faint)" />;
  }

  const stepIndicator = (
    <div className={styles.steps}>
      {STEP_ORDER.map((item, index) => (
        <Fragment key={item}>
          {index > 0 && <div className={styles.stepDivider} />}
          <span
            className={styles.stepDot}
            data-active={step === item}
            data-done={STEP_ORDER.indexOf(step) > index}
          >
            {STEP_LABELS[item]}
          </span>
        </Fragment>
      ))}
    </div>
  );

  return (
    <FormDrawer
      open={open}
      onClose={handleClose}
      icon={<Cpu size={22} />}
      iconTint="var(--color-brand-primary-tint)"
      iconColor="var(--color-brand-primary)"
      title="Register device"
      subtitle="RAAD technician device onboarding"
      footer={
        <div className={styles.footerActions}>
          {step !== "verify" && (
            <Button
              type="button"
              variant="secondary"
              onClick={handleClose}
              disabled={registerState === "pending" || activateState === "pending" || assignState === "pending"}
            >
              Cancel
            </Button>
          )}
          {step !== "hardware" && step !== "verify" && !executionStarted && (
            <Button type="button" variant="secondary" onClick={() => goToStep(STEP_ORDER[STEP_ORDER.indexOf(step) - 1])}>
              Back
            </Button>
          )}
          {step === "hardware" && (
            <Button type="button" variant="primary" onClick={() => goToStep("organization")}>
              Next: Organization
            </Button>
          )}
          {step === "organization" && (
            <Button type="button" variant="primary" onClick={() => goToStep("vehicle")}>
              Next: Vehicle
            </Button>
          )}
          {step === "vehicle" && (
            <Button type="button" variant="primary" onClick={() => goToStep("register")}>
              Next: Review
            </Button>
          )}
          {step === "register" && (
            <Button
              type="button"
              variant="primary"
              loading={registerState === "pending" || activateState === "pending" || assignState === "pending"}
              onClick={onSubmitRegistration}
            >
              {registerState === "error" || activateState === "error" || assignState === "error"
                ? "Retry"
                : "Register & activate device"}
            </Button>
          )}
          {step === "verify" && (
            <Button type="button" variant="primary" onClick={handleClose}>
              Done
            </Button>
          )}
        </div>
      }
    >
      {stepIndicator}

      <form className={styles.form} onSubmit={(event) => event.preventDefault()} noValidate>
        {step === "hardware" && (
          <>
            <FormField
              label="Terminal ID"
              hint="The JT808 terminal/SIM identifier the device presents on the wire — read it off the unit, don't invent one."
              error={errors.terminalId?.message}
            >
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

            <FormField label="IMEI" hint="Optional — exactly 15 digits." error={errors.imei?.message}>
              <Input placeholder="e.g. 352389088459231" invalid={!!errors.imei} {...register("imei")} />
            </FormField>

            <FormField label="ICCID" hint="Optional — the SIM card's own identity." error={errors.iccid?.message}>
              <Input placeholder="e.g. 8944500XXXXXXXXXXXX" invalid={!!errors.iccid} {...register("iccid")} />
            </FormField>

            <FormField label="Serial number" hint="Optional — vendor-assigned hardware serial." error={errors.serialNumber?.message}>
              <Input placeholder="e.g. SN-0042" invalid={!!errors.serialNumber} {...register("serialNumber")} />
            </FormField>
          </>
        )}

        {step === "organization" && (
          <FormField label="Organization" hint="The school this device is being installed for." error={errors.organizationId?.message}>
            <Select {...register("organizationId")} disabled={organizationsQuery.isLoading} aria-label="Organization">
              <option value="">{organizationsQuery.isLoading ? "Loading organizations…" : "Select an organization"}</option>
              {(organizationsQuery.data ?? []).map((org) => (
                <option key={org.id} value={org.id}>
                  {org.name}
                </option>
              ))}
            </Select>
          </FormField>
        )}

        {step === "vehicle" && (
          <FormField label="Vehicle" hint="The bus this device will be mounted on." error={errors.vehicleId?.message}>
            <Select {...register("vehicleId")} disabled={vehiclesQuery.isLoading} aria-label="Vehicle">
              <option value="">{vehiclesQuery.isLoading ? "Loading vehicles…" : "Select a vehicle"}</option>
              {(vehiclesQuery.data ?? []).map((vehicle) => (
                <option key={vehicle.id} value={vehicle.id}>
                  {vehicle.plateNo}
                  {vehicle.label ? ` — ${vehicle.label}` : ""}
                </option>
              ))}
            </Select>
          </FormField>
        )}

        {step === "register" && (
          <>
            <div className={styles.summaryCard}>
              <div className={styles.summaryRow}>
                <span className={styles.summaryLabel}>Terminal ID</span>
                <span>{values.terminalId}</span>
              </div>
              <div className={styles.summaryRow}>
                <span className={styles.summaryLabel}>Organization</span>
                <span>{selectedOrganization?.name ?? values.organizationId}</span>
              </div>
              <div className={styles.summaryRow}>
                <span className={styles.summaryLabel}>Vehicle</span>
                <span>{selectedVehicle?.plateNo ?? values.vehicleId}</span>
              </div>
            </div>

            <div className={styles.checklist}>
              <div>
                <div className={styles.checklistRow}>
                  {stepIcon(registerState)}
                  <span>Register device</span>
                </div>
                {registerState === "error" && <div className={styles.checklistError}>{stepError}</div>}
              </div>
              <div>
                <div className={styles.checklistRow}>
                  {stepIcon(activateState)}
                  <span>Activate device</span>
                </div>
                {activateState === "error" && <div className={styles.checklistError}>{stepError}</div>}
              </div>
              <div>
                <div className={styles.checklistRow}>
                  {stepIcon(assignState)}
                  <span>Assign to vehicle</span>
                </div>
                {assignState === "error" && <div className={styles.checklistError}>{stepError}</div>}
              </div>
            </div>
          </>
        )}

        {step === "verify" && (
          <div className={styles.verifyPanel}>
            {verifiedDevice?.lastSeenAt ? (
              <>
                <div>Last reported: {new Date(verifiedDevice.lastSeenAt).toLocaleString()}</div>
              </>
            ) : (
              <div className={styles.verifyPending}>
                Not yet connected — this device hasn't completed a JT808 handshake with the
                platform yet. Live connectivity confirmation requires the device-plane bridge
                (tracked separately); the device is fully registered, activated, and assigned in
                the meantime.
              </div>
            )}
          </div>
        )}
      </form>
    </FormDrawer>
  );
}
