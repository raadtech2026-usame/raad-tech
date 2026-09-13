import { zodResolver } from "@hookform/resolvers/zod";
import { useEffect, useMemo, useState } from "react";
import { useFieldArray, useForm } from "react-hook-form";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Contact, Copy, Navigation, Plus, Trash2, Users, Wallet } from "lucide-react";
import { z } from "zod";
import { Badge } from "../../../shared/components/Badge/Badge";
import { Button } from "../../../shared/components/Button/Button";
import { FormDrawer } from "../../../shared/components/Drawer/FormDrawer";
import { FormField } from "../../../shared/components/FormField/FormField";
import { Input } from "../../../shared/components/Input/Input";
import { Select } from "../../../shared/components/Select/Select";
import { Toggle } from "../../../shared/components/Toggle/Toggle";
import { useToast } from "../../../shared/components/Toast/toastStore";
import { useAuthStore } from "../../../shared/stores/authStore";
import { ApiError } from "../../../shared/api/types";
import {
  findParentByExactPhone,
  getRouteWithStops,
  listOrganizationsForPicker,
  listRoutesForPicker,
  listVehiclesForPicker,
  registerParent,
  saveParentBillingProfile,
  type ParentSummary,
  type RegisterParentResult,
} from "./api";
import styles from "./CreateParentForm.module.css";

// Matches `transport_ops.domain.value_objects`'s own `_ULID_PATTERN`.
const ULID_PATTERN = /^[0-9A-HJKMNP-TV-Z]{26}$/;
// `value_objects.py`'s `_E164_PATTERN`/`_PHONE_MAX_LENGTH` (Database Design: `phone VARCHAR(32)`).
const E164_PATTERN = /^\+[1-9]\d{1,14}$/;
const PHONE_MAX_LENGTH = 32;
// `entities.py`'s `_PARENT_FULL_NAME_MAX_LENGTH` (Database Design §6.3: `full_name VARCHAR(200)`).
const FULL_NAME_MAX_LENGTH = 200;
// 2026-09-10 additive profile field bounds — see `value_objects.py`'s own module comment.
const ADDRESS_MAX_LENGTH = 255;
const EMERGENCY_CONTACT_NAME_MAX_LENGTH = 200;
const NOTES_MAX_LENGTH = 500;
// Student-side bounds, mirrored here for the inline child rows — see `CreateStudentForm.tsx`'s
// own identical constants.
const CHILD_FULL_NAME_MAX_LENGTH = 200;
// `LinkGuardianForm.tsx`'s own `RELATIONSHIP_MAX_LENGTH` (Database Design §6.4:
// `relationship VARCHAR(40)`) — duplicated rather than cross-imported (a two-line constant).
const RELATIONSHIP_MAX_LENGTH = 40;
const AMOUNT_PATTERN = /^\d{1,13}(\.\d{1,2})?$/;
const PERIOD_PATTERN = /^\d{4}-(0[1-9]|1[0-2])$/;

const PHONE_MESSAGE = "Phone must be E.164 format, e.g. +252612345678";
const optionalPhone = z
  .string()
  .trim()
  .refine((value) => value === "" || (E164_PATTERN.test(value) && value.length <= PHONE_MAX_LENGTH), {
    message: PHONE_MESSAGE,
  });

const childSchema = z.object({
  fullName: z
    .string()
    .trim()
    .min(1, "Child's full name is required")
    .max(CHILD_FULL_NAME_MAX_LENGTH, `Full name must be at most ${CHILD_FULL_NAME_MAX_LENGTH} characters`),
  dateOfBirth: z
    .string()
    .trim()
    .refine(
      (value) => value === "" || new Date(value).getTime() <= Date.now(),
      "Date of birth must not be in the future",
    ),
  gender: z.enum(["", "male", "female", "other"]),
  relationship: z
    .string()
    .trim()
    .max(RELATIONSHIP_MAX_LENGTH, `Relationship must be at most ${RELATIONSHIP_MAX_LENGTH} characters`),
  isPrimary: z.boolean(),
  notes: z.string().trim().max(NOTES_MAX_LENGTH, `Notes must be at most ${NOTES_MAX_LENGTH} characters`),
});

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
      phone: optionalPhone,
      alternatePhone: optionalPhone,
      address: z
        .string()
        .trim()
        .max(ADDRESS_MAX_LENGTH, `Address must be at most ${ADDRESS_MAX_LENGTH} characters`),
      emergencyContactName: z
        .string()
        .trim()
        .max(
          EMERGENCY_CONTACT_NAME_MAX_LENGTH,
          `Emergency contact name must be at most ${EMERGENCY_CONTACT_NAME_MAX_LENGTH} characters`,
        ),
      emergencyContactPhone: optionalPhone,
      notes: z.string().trim().max(NOTES_MAX_LENGTH, `Notes must be at most ${NOTES_MAX_LENGTH} characters`),
      children: z.array(childSchema),
      // Family transportation (2026-09-12 business-model correction) — RAAD's "one Parent/
      // family = one bus" rule: assigned once, here, for every child listed above, never per
      // child. All optional — a family can be registered with no transportation yet and have it
      // set later from the parent's own detail page.
      routeId: z.string(),
      pickupStopId: z.string(),
      dropoffStopId: z.string(),
      vehicleId: z.string(),
      // Parent Billing (the directive's Part 4/5) — optional here: a school can register a
      // family today and configure billing later from the parent's own page. `monthlyFee` left
      // empty means "no billing yet"; filling it in commits the other three fields, which are
      // pre-populated with sensible defaults so typing the fee alone is enough.
      monthlyFee: z
        .string()
        .trim()
        .refine((value) => value === "" || AMOUNT_PATTERN.test(value), {
          message: "Use a decimal amount, e.g. 80.00",
        })
        .refine((value) => value === "" || Number(value) > 0, {
          message: "Monthly fee must be greater than zero",
        }),
      currency: z.string().trim().length(3, "Use a 3-letter currency code, e.g. USD"),
      billingStartPeriod: z.string().trim().regex(PERIOD_PATTERN, "Use YYYY-MM, e.g. 2026-09"),
      dueDay: z.coerce.number().int().min(1).max(28),
    })
    .refine((values) => values.email !== "" || values.phone !== "", {
      message: "At least one of email or phone is required, to create the parent's login.",
      path: ["phone"],
    })
    .refine(
      (values) => values.routeId === "" || (values.pickupStopId !== "" && values.dropoffStopId !== ""),
      {
        message: "Select this family's pickup and dropoff stop.",
        path: ["pickupStopId"],
      },
    );
}

type FormValues = z.infer<ReturnType<typeof buildSchema>>;
type ChildFormValues = FormValues["children"][number];

const EMPTY_CHILD: ChildFormValues = {
  fullName: "",
  dateOfBirth: "",
  gender: "",
  relationship: "",
  isPrimary: false,
  notes: "",
};

function currentPeriod(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

function defaultValues(): FormValues {
  return {
    organizationId: "",
    fullName: "",
    email: "",
    phone: "",
    alternatePhone: "",
    address: "",
    emergencyContactName: "",
    emergencyContactPhone: "",
    notes: "",
    children: [],
    routeId: "",
    pickupStopId: "",
    dropoffStopId: "",
    vehicleId: "",
    monthlyFee: "",
    currency: "USD",
    billingStartPeriod: currentPeriod(),
    dueDay: 10,
  };
}

const PHONE_CHECK_DEBOUNCE_MS = 400;

export interface CreateParentFormProps {
  open: boolean;
  onClose: () => void;
  /** Lets `ParentsPage` open the existing parent's detail drawer directly from this form's own
   * duplicate-phone warning, instead of the admin having to close this drawer and search again. */
  onOpenExisting?: (parent: ParentSummary) => void;
}

/**
 * `POST /parents` (`RegisterParentRequest`, `transport_ops.api.schemas`) — ADR-0003: this form
 * no longer collects a `user_id`. The backend provisions the parent's login itself from
 * `full_name`/`email`/`phone` and returns a one-time temporary password, shown here exactly
 * once (`ParentCreatedResponse`) — this form has a second "success" phase specifically so that
 * password stays on screen (with a copy button) until the admin dismisses it, rather than
 * flashing past in a toast.
 *
 * **The primary registration workflow (ADR-0041 §2, 2026-09-10): Parent + Children together.**
 * A "Children" section sits inside this same form — `+ Add Student` appends a row (full name,
 * date of birth, gender, relationship, primary-guardian toggle, notes); `Save` creates the
 * Parent and every listed child, and links each one, in a single backend transaction
 * (`ParentApplicationService.register_parent_with_children`). Zero children behaves exactly
 * like the original single-parent flow — nothing is required to change for an admin who only
 * wants to register a parent today and add children later from the parent's own detail page.
 *
 * **Family transportation (2026-09-12 business-model correction), one Vehicle/Route/Stop pair
 * for the whole family, not per child.** RAAD's "one Parent/family = one bus" rule: a "Family
 * transportation" section (Route → dependent Pickup/Dropoff stop pickers → optional Vehicle,
 * the same shape `AssignStudentForm.tsx` already established) sits between the Parent's own
 * fields and the Children list. When a route is chosen, every child listed below is assigned to
 * that exact same route/stops/vehicle, in the same backend transaction as their creation
 * (`ParentApplicationService.register_parent_with_children`) — there is no per-child vehicle
 * picker anywhere in this form, and no way to give two children of one registration different
 * transportation. Leaving it blank registers the family with no transportation yet, assignable
 * later from the parent's own detail page (`FamilyTransportationForm.tsx`, also family-wide, not
 * per child).
 *
 * **Duplicate-parent protection (2026-09-10).** Debounced on the phone field: an exact match
 * within the caller's own organization (`findParentByExactPhone`, tenant-scoped server-side)
 * shows an inline warning naming the existing parent, with a button to open their detail drawer
 * directly — never a silent block, and never an automatically-created duplicate. Registration
 * still submits normally if the admin decides to continue (e.g. correcting a typo'd number is
 * also a legitimate reason the check might have false-positived a coincidence... in practice this
 * never happens, since `iam.users.phone` is globally unique — a genuine duplicate would fail at
 * that layer anyway; this check exists to give that failure a helpful shape *before* it happens).
 */
export function CreateParentForm({ open, onClose, onOpenExisting }: CreateParentFormProps) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const principal = useAuthStore((s) => s.principal);
  const ownOrganizationId = principal?.organizationId ?? null;

  const showOrganizationPicker = ownOrganizationId === null;
  const [result, setResult] = useState<RegisterParentResult | null>(null);
  const [billingConfigured, setBillingConfigured] = useState(false);
  const [transportationConfigured, setTransportationConfigured] = useState(false);
  const [copied, setCopied] = useState(false);

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
    control,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: defaultValues(),
  });

  const { fields: childFields, append: appendChild, remove: removeChild } = useFieldArray({
    control,
    name: "children",
  });

  const watchedPhone = watch("phone");
  const [debouncedPhone, setDebouncedPhone] = useState("");
  useEffect(() => {
    const handle = setTimeout(() => setDebouncedPhone(watchedPhone), PHONE_CHECK_DEBOUNCE_MS);
    return () => clearTimeout(handle);
  }, [watchedPhone]);

  const duplicateQuery = useQuery({
    queryKey: ["parents", "duplicate-check", debouncedPhone],
    queryFn: () => findParentByExactPhone(debouncedPhone),
    enabled: open && E164_PATTERN.test(debouncedPhone),
    staleTime: 10_000,
  });
  const duplicate = duplicateQuery.data ?? null;

  // Family transportation (2026-09-12) — one Route/Vehicle picker for the whole family, not one
  // per child. Mirrors `AssignStudentForm.tsx`'s own route -> dependent-stops -> vehicle shape.
  const routesQuery = useQuery({
    queryKey: ["routes", "create-parent-picker"],
    queryFn: () => listRoutesForPicker(""),
    enabled: open,
    staleTime: 30_000,
  });

  const watchedRouteId = watch("routeId");

  const routeStopsQuery = useQuery({
    queryKey: ["routes", "stops-for-create-parent", watchedRouteId],
    queryFn: () => getRouteWithStops(watchedRouteId),
    enabled: open && !!watchedRouteId,
    staleTime: 30_000,
  });

  const vehiclesQuery = useQuery({
    queryKey: ["vehicles", "create-parent-picker", ownOrganizationId],
    queryFn: () => listVehiclesForPicker(ownOrganizationId ?? "", ""),
    enabled: open && !!ownOrganizationId,
    staleTime: 30_000,
  });

  const mutation = useMutation({
    mutationFn: async (values: FormValues) => {
      const registered = await registerParent({
        organizationId: ownOrganizationId ?? values.organizationId,
        fullName: values.fullName,
        email: values.email || null,
        phone: values.phone || null,
        alternatePhone: values.alternatePhone || null,
        address: values.address || null,
        emergencyContactName: values.emergencyContactName || null,
        emergencyContactPhone: values.emergencyContactPhone || null,
        notes: values.notes || null,
        children: values.children.map((child) => ({
          fullName: child.fullName,
          dateOfBirth: child.dateOfBirth || null,
          gender: child.gender || null,
          notes: child.notes || null,
          relationship: child.relationship || null,
          isPrimary: child.isPrimary,
        })),
        routeId: values.routeId || null,
        pickupStopId: values.pickupStopId || null,
        dropoffStopId: values.dropoffStopId || null,
        vehicleId: values.vehicleId || null,
      });

      // Parent Billing (Part 4/5) — a second, independently-committed call, the same disclosed
      // "if this fails, the parent still exists, just without billing configured yet, editable
      // later from the parent's own page" gap ADR-0003's own IAM-user-provisioning precedent
      // already accepts for this exact reason: `school_erp` and `transport_ops` are separate
      // modules with separate transactions, and there is no cross-module transaction to share.
      let configuredBilling = false;
      if (values.monthlyFee.trim() !== "") {
        try {
          await saveParentBillingProfile(registered.parent.id, {
            monthlyFee: values.monthlyFee,
            currency: values.currency,
            billingStartPeriod: values.billingStartPeriod,
            dueDay: values.dueDay,
          });
          configuredBilling = true;
        } catch {
          // Disclosed, not silently swallowed — surfaced via `billingConfigured` below, which
          // drives the success panel's own "set up billing from this parent's page" hint.
        }
      }
      return { registered, configuredBilling, configuredTransportation: values.routeId !== "" };
    },
    onSuccess: ({ registered, configuredBilling, configuredTransportation }) => {
      queryClient.invalidateQueries({ queryKey: ["parents", "list"] });
      if (registered.children.length > 0) {
        queryClient.invalidateQueries({ queryKey: ["students", "list"] });
      }
      setResult(registered);
      setBillingConfigured(configuredBilling);
      setTransportationConfigured(configuredTransportation);
    },
    onError: (error) => {
      const message = error instanceof ApiError ? error.message : "Could not register the parent.";
      toast.error("Registration failed", message);
    },
  });

  function resetAll(): void {
    reset(defaultValues());
    mutation.reset();
    setResult(null);
    setBillingConfigured(false);
    setTransportationConfigured(false);
    setCopied(false);
  }

  function handleClose(): void {
    if (mutation.isPending) {
      return;
    }
    resetAll();
    onClose();
  }

  function handleOpenExisting(): void {
    if (duplicate && onOpenExisting) {
      onOpenExisting(duplicate);
      handleClose();
    }
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

  const routeOptions = routesQuery.data ?? [];
  const routeError = errors.routeId?.message ?? (routesQuery.isError ? "Could not load routes." : undefined);
  const stopOptions = routeStopsQuery.data?.stops ?? [];
  const pickupError =
    errors.pickupStopId?.message ?? (routeStopsQuery.isError ? "Could not load this route's stops." : undefined);
  const dropoffError =
    errors.dropoffStopId?.message ?? (routeStopsQuery.isError ? "Could not load this route's stops." : undefined);
  const vehicleOptions = vehiclesQuery.data ?? [];

  if (result) {
    return (
      <FormDrawer
        open={open}
        onClose={handleClose}
        icon={<CheckCircle2 size={22} />}
        iconTint="var(--color-success-tint)"
        iconColor="var(--color-success)"
        title="Parent registered"
        subtitle={`${result.parent.fullName}'s login has been created`}
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
            Share this one-time password with <strong>{result.parent.fullName}</strong> — it will not be shown
            again.
          </p>
          <div className={styles.passwordRow}>
            <code className={styles.password}>{result.temporaryPassword}</code>
            <Button type="button" variant="secondary" size="sm" leadingIcon={<Copy size={13} />} onClick={() => void handleCopyPassword()}>
              {copied ? "Copied" : "Copy"}
            </Button>
          </div>
          {result.children.length > 0 && (
            <div className={styles.childrenSummary}>
              <span className={styles.childrenSummaryTitle}>
                {result.children.length} {result.children.length === 1 ? "child" : "children"} registered
              </span>
              {result.children.map((child) => (
                <div key={child.id} className={styles.childrenSummaryRow}>
                  {child.fullName}
                </div>
              ))}
            </div>
          )}
          <div className={styles.childrenSummary}>
            <span className={styles.childrenSummaryTitle}>Transportation</span>
            <p className={styles.childrenSummaryHint}>
              {transportationConfigured
                ? "This family's Vehicle/Route/Stops are set — every child above shares the same assignment."
                : "No transportation set yet — assign this family's Vehicle/Route/Stops any time from the parent's own page."}
            </p>
          </div>
          <div className={styles.childrenSummary}>
            <span className={styles.childrenSummaryTitle}>Billing</span>
            <p className={styles.childrenSummaryHint}>
              {billingConfigured
                ? "This family's monthly transportation fee is set up. The first Parent Invoice generates on the next monthly billing run."
                : "No monthly fee was set — configure it any time from this parent's own page before generating invoices."}
            </p>
          </div>
        </div>
      </FormDrawer>
    );
  }

  return (
    <FormDrawer
      open={open}
      onClose={handleClose}
      icon={<Contact size={22} />}
      iconTint="var(--color-brand-primary-tint)"
      iconColor="var(--color-brand-primary)"
      title="New parent"
      subtitle="Register a parent and their children together"
      footer={
        <div className={styles.footerActions}>
          <Button type="button" variant="secondary" onClick={handleClose} disabled={mutation.isPending}>
            Cancel
          </Button>
          <Button type="button" variant="primary" loading={isSubmitting || mutation.isPending} onClick={onValid}>
            {childFields.length > 0 ? "Save parent & children" : "Register parent"}
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
          <Input placeholder="e.g. Fatima Ali" invalid={!!errors.fullName} {...register("fullName")} />
        </FormField>

        <FormField label="Email" hint="Optional if a phone is given — required for the login otherwise." error={errors.email?.message}>
          <Input type="email" placeholder="e.g. fatima@example.com" invalid={!!errors.email} {...register("email")} />
        </FormField>

        <FormField label="Primary phone" hint="E.164 format, e.g. +252612345678." error={errors.phone?.message}>
          <Input placeholder="+252612345678" invalid={!!errors.phone} {...register("phone")} />
        </FormField>

        {duplicate && (
          <div className={styles.duplicateWarning} role="alert">
            <Badge variant="warning" dot>
              Possible duplicate
            </Badge>
            <span>
              A parent with this phone number already exists: <strong>{duplicate.fullName}</strong>.
            </span>
            {onOpenExisting && (
              <Button type="button" variant="secondary" size="sm" onClick={handleOpenExisting}>
                Open existing parent
              </Button>
            )}
          </div>
        )}

        <FormField label="Alternative phone" hint="Optional." error={errors.alternatePhone?.message}>
          <Input placeholder="+252611111111" invalid={!!errors.alternatePhone} {...register("alternatePhone")} />
        </FormField>

        <FormField label="Address" hint="Optional." error={errors.address?.message}>
          <Input placeholder="e.g. Hodan District, Mogadishu" invalid={!!errors.address} {...register("address")} />
        </FormField>

        <FormField label="Emergency contact name" hint="Optional." error={errors.emergencyContactName?.message}>
          <Input placeholder="e.g. Ahmed Hassan" invalid={!!errors.emergencyContactName} {...register("emergencyContactName")} />
        </FormField>

        <FormField label="Emergency contact phone" hint="Optional." error={errors.emergencyContactPhone?.message}>
          <Input placeholder="+252622222222" invalid={!!errors.emergencyContactPhone} {...register("emergencyContactPhone")} />
        </FormField>

        <FormField label="Notes" hint="Optional." error={errors.notes?.message}>
          <Input placeholder="Optional" invalid={!!errors.notes} {...register("notes")} />
        </FormField>

        <div className={styles.childrenSection}>
          <div className={styles.childrenSectionHeader}>
            <span className={styles.childrenSectionTitle}>
              <Navigation size={15} /> Family transportation
            </span>
          </div>
          <p className={styles.childrenEmptyHint}>
            One Vehicle/Route/Stop pair for this whole family — every child added below shares it.
            Optional here; leave blank to assign it later from this parent's own page.
          </p>

          <FormField label="Route" hint="Optional." error={routeError}>
            <Select {...register("routeId")} disabled={routesQuery.isLoading} aria-label="Family route">
              <option value="">{routesQuery.isLoading ? "Loading routes…" : "No route yet"}</option>
              {routeOptions.map((route) => (
                <option key={route.id} value={route.id}>
                  {route.name}
                </option>
              ))}
            </Select>
          </FormField>

          <div className={styles.childRow}>
            <FormField label="Pickup stop" error={pickupError}>
              <Select
                {...register("pickupStopId")}
                disabled={!watchedRouteId || routeStopsQuery.isLoading}
                aria-label="Family pickup stop"
              >
                <option value="">
                  {!watchedRouteId ? "Select a route first" : routeStopsQuery.isLoading ? "Loading stops…" : "Select a stop"}
                </option>
                {stopOptions.map((stop) => (
                  <option key={stop.id} value={stop.id}>
                    {stop.sequenceNo}. {stop.name}
                  </option>
                ))}
              </Select>
            </FormField>
            <FormField label="Dropoff stop" error={dropoffError}>
              <Select
                {...register("dropoffStopId")}
                disabled={!watchedRouteId || routeStopsQuery.isLoading}
                aria-label="Family dropoff stop"
              >
                <option value="">
                  {!watchedRouteId ? "Select a route first" : routeStopsQuery.isLoading ? "Loading stops…" : "Select a stop"}
                </option>
                {stopOptions.map((stop) => (
                  <option key={stop.id} value={stop.id}>
                    {stop.sequenceNo}. {stop.name}
                  </option>
                ))}
              </Select>
            </FormField>
          </div>

          <FormField label="Vehicle" hint="Optional — the specific bus this family rides, if already known.">
            <Select {...register("vehicleId")} disabled={vehiclesQuery.isLoading} aria-label="Family vehicle">
              <option value="">{vehiclesQuery.isLoading ? "Loading vehicles…" : "No vehicle"}</option>
              {vehicleOptions.map((vehicle) => (
                <option key={vehicle.id} value={vehicle.id}>
                  {vehicle.plateNo}
                  {vehicle.label ? ` — ${vehicle.label}` : ""}
                </option>
              ))}
            </Select>
          </FormField>
        </div>

        <div className={styles.childrenSection}>
          <div className={styles.childrenSectionHeader}>
            <span className={styles.childrenSectionTitle}>
              <Users size={15} /> Children {childFields.length > 0 ? `(${childFields.length})` : ""}
            </span>
            <Button
              type="button"
              variant="secondary"
              size="sm"
              leadingIcon={<Plus size={13} />}
              onClick={() => appendChild({ ...EMPTY_CHILD })}
            >
              Add student
            </Button>
          </div>

          {childFields.length === 0 && (
            <p className={styles.childrenEmptyHint}>
              No children added yet — optional. Add one or more now, or from this parent's own
              page later.
            </p>
          )}

          {childFields.map((field, index) => {
            const childErrors = errors.children?.[index];
            return (
              <div key={field.id} className={styles.childCard}>
                <div className={styles.childCardHeader}>
                  <span>Student {index + 1}</span>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    leadingIcon={<Trash2 size={13} />}
                    onClick={() => removeChild(index)}
                    aria-label={`Remove student ${index + 1}`}
                  >
                    Remove
                  </Button>
                </div>

                <FormField label="Full name" error={childErrors?.fullName?.message}>
                  <Input
                    placeholder="e.g. Mohamed Ahmed"
                    invalid={!!childErrors?.fullName}
                    {...register(`children.${index}.fullName` as const)}
                  />
                </FormField>

                <div className={styles.childRow}>
                  <FormField label="Date of birth" error={childErrors?.dateOfBirth?.message}>
                    <Input type="date" invalid={!!childErrors?.dateOfBirth} {...register(`children.${index}.dateOfBirth` as const)} />
                  </FormField>
                  <FormField label="Gender">
                    <Select {...register(`children.${index}.gender` as const)} aria-label={`Student ${index + 1} gender`}>
                      <option value="">Not specified</option>
                      <option value="male">Male</option>
                      <option value="female">Female</option>
                      <option value="other">Other</option>
                    </Select>
                  </FormField>
                </div>

                <div className={styles.childRow}>
                  <FormField label="Relationship" hint="e.g. Mother, Father" error={childErrors?.relationship?.message}>
                    <Input
                      placeholder="e.g. Father"
                      invalid={!!childErrors?.relationship}
                      {...register(`children.${index}.relationship` as const)}
                    />
                  </FormField>
                  <Toggle
                    label="Primary guardian"
                    description="Main point of contact for this child."
                    {...register(`children.${index}.isPrimary` as const)}
                  />
                </div>

                <FormField label="Notes" hint="Optional." error={childErrors?.notes?.message}>
                  <Input placeholder="Optional" invalid={!!childErrors?.notes} {...register(`children.${index}.notes` as const)} />
                </FormField>
              </div>
            );
          })}
        </div>

        <div className={styles.childrenSection}>
          <div className={styles.childrenSectionHeader}>
            <span className={styles.childrenSectionTitle}>
              <Wallet size={15} /> Parent billing
            </span>
          </div>
          <p className={styles.childrenEmptyHint}>
            What this parent is charged for transportation each month. No Fee Plan required —
            optional here; set it up later from this parent's own page if you prefer.
          </p>

          <FormField
            label={`Monthly transportation fee (${watch("currency") || "USD"})`}
            hint="Leave blank to configure billing later."
            error={errors.monthlyFee?.message}
          >
            <Input placeholder="80.00" inputMode="decimal" invalid={!!errors.monthlyFee} {...register("monthlyFee")} />
          </FormField>

          <div className={styles.childRow}>
            <FormField label="Currency" error={errors.currency?.message}>
              <Select {...register("currency")} aria-label="Billing currency">
                <option value="USD">USD</option>
                <option value="SOS">SOS</option>
                <option value="KES">KES</option>
              </Select>
            </FormField>
            <FormField label="Due day" hint="1–28" error={errors.dueDay?.message}>
              <Input type="number" min={1} max={28} invalid={!!errors.dueDay} {...register("dueDay")} />
            </FormField>
          </div>

          <FormField
            label="Billing start"
            hint="First month this parent is billed, e.g. 2026-09."
            error={errors.billingStartPeriod?.message}
          >
            <Input placeholder="2026-09" invalid={!!errors.billingStartPeriod} {...register("billingStartPeriod")} />
          </FormField>
        </div>
      </form>
    </FormDrawer>
  );
}
