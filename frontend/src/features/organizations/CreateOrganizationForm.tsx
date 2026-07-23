import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Building2 } from "lucide-react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { Button } from "../../shared/components/Button/Button";
import { FormDrawer } from "../../shared/components/Drawer/FormDrawer";
import { FormField } from "../../shared/components/FormField/FormField";
import { Input } from "../../shared/components/Input/Input";
import { Select } from "../../shared/components/Select/Select";
import { useToast } from "../../shared/components/Toast/toastStore";
import { ApiError } from "../../shared/api/types";
import { createOrganization, listRegions, type BillingModel } from "./api";
import styles from "./CreateOrganizationForm.module.css";

// Matches `organization.domain.value_objects`'s own `_ULID_PATTERN` (Crockford Base32, 26 chars)
// — client-side format validation of the same real domain invariant, not a new business rule.
const ULID_PATTERN = /^[0-9A-HJKMNP-TV-Z]{26}$/;
const BILLING_MODELS = ["organization_pays", "parent_pays"] as const;

const schema = z.object({
  name: z.string().trim().min(1, "Organization name is required"),
  regionId: z.string().min(1, "Region is required"),
  billingModel: z
    .string()
    .min(1, "Billing model is required")
    .refine((value) => (BILLING_MODELS as readonly string[]).includes(value), {
      message: "Select a valid billing model",
    }),
  parentOrgId: z
    .string()
    .trim()
    .refine((value) => value === "" || ULID_PATTERN.test(value), {
      message: "Must be a valid organization ID (26-character ULID)",
    }),
});

type FormValues = z.infer<typeof schema>;

const DEFAULT_VALUES: FormValues = { name: "", regionId: "", billingModel: "", parentOrgId: "" };

export interface CreateOrganizationFormProps {
  open: boolean;
  onClose: () => void;
}

/**
 * `POST /organizations` (`RegisterOrganizationRequest`) exactly: `name`, `org_type` (fixed to
 * `"school"` — Database Design §4.2's **D3**, the only currently-active `org_type` value, so
 * this form offers one fixed choice rather than a dropdown implying others exist), `region_id`
 * (a required picker over `GET /regions` — this module has no standalone Regions feature this
 * phase; fetching the region list here is the minimal read this required field makes
 * unavoidable), `billing_model`, and an optional `parent_org_id`. `org_type` is deliberately not
 * a form field at all: it is always sent as `"school"`.
 */
export function CreateOrganizationForm({ open, onClose }: CreateOrganizationFormProps) {
  const toast = useToast();
  const queryClient = useQueryClient();

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
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: DEFAULT_VALUES,
  });

  const mutation = useMutation({
    mutationFn: (values: FormValues) =>
      createOrganization({
        name: values.name,
        orgType: "school",
        regionId: values.regionId,
        // Safe cast: the zod `.refine` above already guarantees one of `BILLING_MODELS`.
        billingModel: values.billingModel as BillingModel,
        parentOrgId: values.parentOrgId || null,
      }),
    onSuccess: (organization) => {
      // Matches every other feature's mutation convention (roadmap §3.2): invalidate the exact
      // query key affected, not a blanket `invalidateQueries()`.
      queryClient.invalidateQueries({ queryKey: ["organizations", "list"] });
      toast.success("Organization created", `${organization.name} has been added.`);
      reset(DEFAULT_VALUES);
      onClose();
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
    onClose();
  }

  const onValid = handleSubmit((values) => mutation.mutate(values));
  const regionOptions = regionsQuery.data?.data ?? [];
  const regionError = errors.regionId?.message ?? (regionsQuery.isError ? "Could not load regions." : undefined);

  return (
    <FormDrawer
      open={open}
      onClose={handleClose}
      icon={<Building2 size={22} />}
      iconTint="var(--color-brand-primary-tint)"
      iconColor="var(--color-brand-primary)"
      title="New Organization"
      subtitle="Register a new tenant on the platform"
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

        <FormField label="Billing model" error={errors.billingModel?.message}>
          <Select {...register("billingModel")} aria-label="Billing model">
            <option value="">Select a billing model</option>
            <option value="organization_pays">Organization pays</option>
            <option value="parent_pays">Parent pays</option>
          </Select>
        </FormField>

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
      </form>
    </FormDrawer>
  );
}
