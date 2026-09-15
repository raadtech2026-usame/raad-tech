import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Building2, Check, Copy } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { Button } from "../../shared/components/Button/Button";
import { FormDrawer } from "../../shared/components/Drawer/FormDrawer";
import { FormField } from "../../shared/components/FormField/FormField";
import { Input } from "../../shared/components/Input/Input";
import { Select } from "../../shared/components/Select/Select";
import { useToast } from "../../shared/components/Toast/toastStore";
import { ApiError } from "../../shared/api/types";
// A cross-folder API import, unlike this codebase's usual per-feature discipline — deliberate
// and narrow: the plan catalogue is `billing`'s own resource, and duplicating a second
// `GET /billing/plans` client here would be the actual duplication the rule guards against.
import { listActivePlansForPicker } from "../billing/api";
import { createOrganization, listRegions, type OnboardedOrganization } from "./api";
import styles from "./CreateOrganizationForm.module.css";

// Matches `organization.domain.value_objects`'s own `_ULID_PATTERN` (Crockford Base32, 26 chars)
// — client-side format validation of the same real domain invariant, not a new business rule.
const ULID_PATTERN = /^[0-9A-HJKMNP-TV-Z]{26}$/;

/** Preset trial durations (Part 1's own requested set); "Custom" reveals a plain day-count
 * input rather than adding a second pricing/duration engine — the backend accepts any integer
 * in `organization.domain.entities`' documented 1-365 day bound regardless of which UI path
 * produced it. */
const TRIAL_DURATION_PRESETS = [3, 7, 14, 30] as const;
const CUSTOM_TRIAL_DURATION = "custom";

const schema = z
  .object({
    name: z.string().trim().min(1, "Organization name is required"),
    regionId: z.string().min(1, "Region is required"),
    parentOrgId: z
      .string()
      .trim()
      .refine((value) => value === "" || ULID_PATTERN.test(value), {
        message: "Must be a valid organization ID (26-character ULID)",
      }),
    // Onboarding path: "trial" (defers plan selection) or "plan"/none (ADR-0040 §5's existing
    // optional plan_id) — never both, the backend rejects a request setting both.
    onboardingPath: z.enum(["none", "plan", "trial"]),
    // Optional (ADR-0040 §5): an organization can be onboarded before its commercial tier is
    // agreed, then have a subscription opened later. Supplying it here is the path that opens
    // the subscription and issues the first invoice in the same request.
    planId: z.string(),
    trialDurationPreset: z.string(),
    trialDurationCustomDays: z.string(),
    adminFullName: z.string().trim().min(1, "Org Admin name is required"),
    adminEmail: z.string().trim().email("Must be a valid email").or(z.literal("")),
    adminPhone: z.string().trim(),
  })
  // ADR-0017: the provisioned `iam.User` needs at least one of email/phone, mirroring
  // `iam.User`'s own domain invariant — enforced here too so the error surfaces before submit,
  // not as a backend round-trip.
  .refine((values) => values.adminEmail !== "" || values.adminPhone !== "", {
    message: "Provide an Org Admin email or phone number",
    path: ["adminEmail"],
  })
  .refine(
    (values) =>
      values.onboardingPath !== "trial" ||
      values.trialDurationPreset !== CUSTOM_TRIAL_DURATION ||
      (Number(values.trialDurationCustomDays) >= 1 &&
        Number(values.trialDurationCustomDays) <= 365),
    {
      message: "Enter a custom duration between 1 and 365 days",
      path: ["trialDurationCustomDays"],
    },
  );

type FormValues = z.infer<typeof schema>;

const DEFAULT_VALUES: FormValues = {
  name: "",
  regionId: "",
  parentOrgId: "",
  onboardingPath: "none",
  planId: "",
  trialDurationPreset: String(TRIAL_DURATION_PRESETS[0]),
  trialDurationCustomDays: "",
  adminFullName: "",
  adminEmail: "",
  adminPhone: "",
};

function resolveTrialDurationDays(values: FormValues): number | null {
  if (values.onboardingPath !== "trial") return null;
  if (values.trialDurationPreset === CUSTOM_TRIAL_DURATION) {
    const parsed = Number(values.trialDurationCustomDays);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return Number(values.trialDurationPreset);
}

export interface CreateOrganizationFormProps {
  open: boolean;
  onClose: () => void;
}

/**
 * `POST /organizations` (ADR-0017, `RegisterOrganizationRequest`): `name`, `org_type` (fixed to
 * `"school"` — Database Design §4.2's **D3**, the only currently-active `org_type` value, so
 * this form offers one fixed choice rather than a dropdown implying others exist), `region_id`
 * (a required picker over `GET /regions` — this module has no standalone Regions feature this
 * phase; fetching the region list here is the minimal read this required field makes
 * unavoidable), an optional `parent_org_id`, and — since Organization Onboarding is now one
 * guided workflow, not two disconnected steps — the Org Admin's own identity fields
 * (`admin_full_name`/`admin_email`/`admin_phone`). `org_type` is deliberately not a form field
 * at all: it is always sent as `"school"`. **No `billing_model` field** — ADR-0016 (RAAD
 * business model realignment) removed it from `Organization` entirely; RAAD bills Organizations
 * only now.
 *
 * **Plan selection is deliberately not part of this form yet** — see
 * `organization.application.commands.OnboardOrganizationCommand`'s own docstring: a real,
 * flagged follow-up now that ADR-0016 has landed, not attempted this phase.
 *
 * On success, the response carries a one-time Org Admin temporary password — surfaced in this
 * drawer exactly once (a `result` view replaces the form) before closing, since it is never
 * retrievable again afterward via any other endpoint. That reveal also shows the new
 * Organization's own id, its login URL (this app's own `/login` route — there is no separate
 * "Organization Portal" domain), and the Org Admin's email/phone (captured from what was just
 * submitted; the backend response itself only carries the opaque `adminUserId`) — everything a
 * Founder needs to hand off to the Org Admin in one place.
 */
export function CreateOrganizationForm({ open, onClose }: CreateOrganizationFormProps) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [result, setResult] = useState<OnboardedOrganization | null>(null);
  const [adminContact, setAdminContact] = useState<{ email: string; phone: string } | null>(
    null,
  );
  const [copied, setCopied] = useState(false);

  // This app has no separate "Organization Portal" domain — one SPA, one `/login` route for
  // every role (`app/router.tsx`), redirecting to `/org` post-auth for an Org Admin. Read from
  // the real, currently-running origin rather than a hardcoded/fabricated subdomain.
  const organizationPortalUrl = `${window.location.origin}/login`;

  // ADR-0040 §5. Onboarding can open the organization's subscription in the same request, which
  // is what stops a brand-new tenant hitting ADR-0039's subscription-inactive gate on its first
  // login. Only active organization plans are offered — a disabled tier is not sellable.
  const plansQuery = useQuery({
    queryKey: ["billing", "plans", "picker"],
    queryFn: listActivePlansForPicker,
    enabled: open,
    staleTime: 60_000,
  });

  const regionsQuery = useQuery({
    queryKey: ["regions", "picker"],
    queryFn: () =>
      listRegions({
        page: 1,
        pageSize: 100,
        sort: { field: "name", direction: "asc" },
        filters: { status: "active" },
        search: "",
      }),
    enabled: open,
    staleTime: 60_000,
  });

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

  const onboardingPath = watch("onboardingPath");
  const trialDurationPreset = watch("trialDurationPreset");

  const mutation = useMutation({
    mutationFn: (values: FormValues) =>
      createOrganization({
        name: values.name,
        orgType: "school",
        regionId: values.regionId,
        parentOrgId: values.parentOrgId || null,
        planId: values.onboardingPath === "plan" ? values.planId || null : null,
        trialEnabled: values.onboardingPath === "trial",
        trialDurationDays: resolveTrialDurationDays(values),
        adminFullName: values.adminFullName,
        adminEmail: values.adminEmail || null,
        adminPhone: values.adminPhone || null,
      }),
    onSuccess: (onboarded, values) => {
      // Matches every other feature's mutation convention (roadmap §3.2): invalidate the exact
      // query key affected, not a blanket `invalidateQueries()`.
      queryClient.invalidateQueries({ queryKey: ["organizations", "list"] });
      toast.success("Organization created", `${onboarded.organization.name} has been added.`);
      // The response itself carries no email/phone (only the opaque adminUserId) — captured
      // here from what was just submitted so the reveal panel can show the actual login
      // identifier, not just a reference id.
      setAdminContact({ email: values.adminEmail, phone: values.adminPhone });
      reset(DEFAULT_VALUES);
      // Don't close yet — the temporary password is shown exactly once, below.
      setResult(onboarded);
    },
    onError: (error) => {
      const message =
        error instanceof ApiError ? error.message : "Could not create the organization.";
      toast.error("Create failed", message);
    },
  });

  function handleClose(): void {
    if (mutation.isPending) {
      return;
    }
    reset(DEFAULT_VALUES);
    mutation.reset();
    setResult(null);
    setAdminContact(null);
    setCopied(false);
    onClose();
  }

  async function handleCopyPassword(): Promise<void> {
    if (!result) return;
    try {
      await navigator.clipboard.writeText(result.temporaryPassword);
      setCopied(true);
    } catch {
      // Clipboard access can be denied/unavailable — the password is still visible and
      // selectable in the field below, so this is a convenience, not the only way to copy it.
    }
  }

  const onValid = handleSubmit((values) => mutation.mutate(values));
  const regionOptions = regionsQuery.data?.data ?? [];
  const regionError = errors.regionId?.message ?? (regionsQuery.isError ? "Could not load regions." : undefined);

  if (result) {
    return (
      <FormDrawer
        open={open}
        onClose={handleClose}
        icon={<Building2 size={22} />}
        iconTint="var(--color-brand-primary-tint)"
        iconColor="var(--color-brand-primary)"
        title="Organization created"
        subtitle="Hand these credentials to the Org Admin — shown only once"
        footer={
          <div className={styles.footerActions}>
            <Button type="button" variant="primary" onClick={handleClose}>
              Done
            </Button>
          </div>
        }
      >
        <div className={styles.form}>
          <FormField label="Organization">
            <Input value={result.organization.name} readOnly />
          </FormField>
          <FormField label="Organization ID">
            <Input value={result.organization.id} readOnly />
          </FormField>
          <FormField
            label="Organization Portal URL"
            hint="This app's own login page — the same one every role signs in through; it redirects to the Organization Dashboard after a successful Org Admin login."
          >
            <Input value={organizationPortalUrl} readOnly />
          </FormField>
          <FormField
            label="Org Admin login"
            hint="Email or phone — whichever was provided is the actual sign-in identifier."
          >
            <Input value={adminContact?.email || adminContact?.phone || "—"} readOnly />
          </FormField>
          <FormField label="Org Admin user ID" hint="Reference id for this account — email or phone above is the actual login.">
            <Input value={result.adminUserId} readOnly />
          </FormField>
          <FormField
            label="Temporary password"
            hint="Not retrievable again after you close this panel — copy it now."
          >
            <div className={styles.footerActions}>
              <Input value={result.temporaryPassword} readOnly />
              <Button type="button" variant="secondary" onClick={handleCopyPassword}>
                {copied ? <Check size={16} /> : <Copy size={16} />}
                {copied ? "Copied" : "Copy"}
              </Button>
            </div>
          </FormField>
        </div>
      </FormDrawer>
    );
  }

  return (
    <FormDrawer
      open={open}
      onClose={handleClose}
      icon={<Building2 size={22} />}
      iconTint="var(--color-brand-primary-tint)"
      iconColor="var(--color-brand-primary)"
      title="New Organization"
      subtitle="Register a new tenant and its first Org Admin"
      footer={
        <div className={styles.footerActions}>
          <Button type="button" variant="secondary" onClick={handleClose} disabled={mutation.isPending}>
            Cancel
          </Button>
          <Button
            type="button"
            variant="primary"
            loading={isSubmitting || mutation.isPending}
            onClick={onValid}
          >
            Create organization
          </Button>
        </div>
      }
    >
      <form className={styles.form} onSubmit={onValid} noValidate>
        <FormField label="Organization name" error={errors.name?.message}>
          <Input
            placeholder="e.g. Green Valley School"
            invalid={!!errors.name}
            {...register("name")}
          />
        </FormField>

        <FormField label="Organization type" hint="Only school organizations are supported today.">
          <Select defaultValue="school" disabled aria-label="Organization type">
            <option value="school">School</option>
          </Select>
        </FormField>

        <FormField label="Region" error={regionError}>
          <Select
            {...register("regionId")}
            disabled={regionsQuery.isLoading || regionsQuery.isError}
            aria-label="Region"
          >
            <option value="">{regionsQuery.isLoading ? "Loading regions…" : "Select a region"}</option>
            {regionOptions.map((region) => (
              <option key={region.id} value={region.id}>
                {region.name}
              </option>
            ))}
          </Select>
        </FormField>

        <FormField
          label="Onboarding"
          hint="Choose exactly one: defer billing with a trial, assign a plan now, or leave the organization unsubscribed until later."
        >
          <Select {...register("onboardingPath")} aria-label="Onboarding path">
            <option value="none">No trial / no subscription yet</option>
            <option value="plan">Choose a subscription plan now</option>
            <option value="trial">Start with a trial</option>
          </Select>
        </FormField>

        {onboardingPath === "plan" && (
          <FormField
            label="Subscription plan"
            hint={
              plansQuery.isError
                ? "Could not load plans — the organization can still be created and subscribed later."
                : "Opens the subscription and issues the first invoice now."
            }
            error={errors.planId?.message}
          >
            <Select {...register("planId")} disabled={plansQuery.isLoading}>
              <option value="">Select a plan</option>
              {(plansQuery.data ?? []).map((plan) => (
                <option key={plan.id} value={plan.id}>
                  {plan.name} — {plan.amount} {plan.currency} / {plan.billingCycle}
                </option>
              ))}
            </Select>
          </FormField>
        )}

        {onboardingPath === "trial" && (
          <FormField
            label="Trial duration"
            hint="No subscription/plan is created now — the organization gets full access until the trial ends, then Founder assigns a plan from its Subscription tab."
            error={errors.trialDurationCustomDays?.message}
          >
            <div className={styles.footerActions}>
              <Select {...register("trialDurationPreset")} aria-label="Trial duration">
                {TRIAL_DURATION_PRESETS.map((days) => (
                  <option key={days} value={days}>
                    {days} days
                  </option>
                ))}
                <option value={CUSTOM_TRIAL_DURATION}>Custom…</option>
              </Select>
              {trialDurationPreset === CUSTOM_TRIAL_DURATION && (
                <Input
                  type="number"
                  min={1}
                  max={365}
                  placeholder="Days"
                  invalid={!!errors.trialDurationCustomDays}
                  {...register("trialDurationCustomDays")}
                />
              )}
            </div>
          </FormField>
        )}

        <FormField
          label="Parent organization ID"
          hint="Optional — leave blank unless this is a sub-organization/campus."
          error={errors.parentOrgId?.message}
        >
          <Input
            placeholder="26-character ULID"
            invalid={!!errors.parentOrgId}
            {...register("parentOrgId")}
          />
        </FormField>

        <FormField label="Org Admin full name" error={errors.adminFullName?.message}>
          <Input
            placeholder="e.g. Amina Warsame"
            invalid={!!errors.adminFullName}
            {...register("adminFullName")}
          />
        </FormField>

        <FormField
          label="Org Admin email"
          hint="At least one of email or phone is required."
          error={errors.adminEmail?.message}
        >
          <Input
            type="email"
            placeholder="admin@school.example.com"
            invalid={!!errors.adminEmail}
            {...register("adminEmail")}
          />
        </FormField>

        <FormField label="Org Admin phone" hint="Optional if email is provided.">
          <Input placeholder="+2526xxxxxxxx" {...register("adminPhone")} />
        </FormField>
      </form>
    </FormDrawer>
  );
}
