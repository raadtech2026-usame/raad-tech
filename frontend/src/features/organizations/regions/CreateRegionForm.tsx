import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Globe } from "lucide-react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { Button } from "../../../shared/components/Button/Button";
import { FormDrawer } from "../../../shared/components/Drawer/FormDrawer";
import { FormField } from "../../../shared/components/FormField/FormField";
import { Input } from "../../../shared/components/Input/Input";
import { useToast } from "../../../shared/components/Toast/toastStore";
import { ApiError } from "../../../shared/api/types";
import { createRegion } from "./api";
import styles from "./CreateRegionForm.module.css";

// `entities.py`'s `Region` domain invariant: name must not be empty. Database Design §4.1:
// `name VARCHAR(120)`, `geographic_scope VARCHAR(255)`.
const REGION_NAME_MAX_LENGTH = 120;
const GEOGRAPHIC_SCOPE_MAX_LENGTH = 255;

const schema = z.object({
  name: z
    .string()
    .trim()
    .min(1, "Region name is required")
    .max(REGION_NAME_MAX_LENGTH, `Region name must be at most ${REGION_NAME_MAX_LENGTH} characters`),
  geographicScope: z
    .string()
    .trim()
    .max(GEOGRAPHIC_SCOPE_MAX_LENGTH, `Must be at most ${GEOGRAPHIC_SCOPE_MAX_LENGTH} characters`),
});

type FormValues = z.infer<typeof schema>;

const DEFAULT_VALUES: FormValues = { name: "", geographicScope: "" };

export interface CreateRegionFormProps {
  open: boolean;
  onClose: () => void;
}

/**
 * `POST /regions` (`CreateRegionRequest`, `organization.api.schemas`) exactly: `name`,
 * `geographic_scope`. Unlike every other create-form in this codebase, there is no
 * organization picker at all — `regions` is a platform-scoped table with no `organization_id`
 * column (Database Design §4.1), the same shape `RegionId`'s own domain docstring documents.
 * Only `founder` holds `organization.regions.create` in the seeded RBAC matrix — this form is
 * reachable exclusively from `RegionsPage.tsx`'s own `canManage` gate.
 */
export function CreateRegionForm({ open, onClose }: CreateRegionFormProps) {
  const toast = useToast();
  const queryClient = useQueryClient();

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
      createRegion({
        name: values.name,
        geographicScope: values.geographicScope || null,
      }),
    onSuccess: (region) => {
      queryClient.invalidateQueries({ queryKey: ["regions", "management-list"] });
      toast.success("Region created", `${region.name} has been added.`);
      reset(DEFAULT_VALUES);
      onClose();
    },
    onError: (error) => {
      const message = error instanceof ApiError ? error.message : "Could not create the region.";
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

  return (
    <FormDrawer
      open={open}
      onClose={handleClose}
      icon={<Globe size={22} />}
      iconTint="var(--color-brand-primary-tint)"
      iconColor="var(--color-brand-primary)"
      title="New region"
      subtitle="Add a region for tenant/staff scoping"
      footer={
        <div className={styles.footerActions}>
          <Button type="button" variant="secondary" onClick={handleClose} disabled={mutation.isPending}>
            Cancel
          </Button>
          <Button type="button" variant="primary" loading={isSubmitting || mutation.isPending} onClick={onValid}>
            Create region
          </Button>
        </div>
      }
    >
      <form className={styles.form} onSubmit={onValid} noValidate>
        <FormField label="Region name" error={errors.name?.message}>
          <Input placeholder="e.g. East Africa" invalid={!!errors.name} {...register("name")} />
        </FormField>

        <FormField
          label="Geographic scope"
          hint="Optional — a free-text description of what this region covers."
          error={errors.geographicScope?.message}
        >
          <Input
            placeholder="e.g. Kenya, Somalia, Ethiopia"
            invalid={!!errors.geographicScope}
            {...register("geographicScope")}
          />
        </FormField>
      </form>
    </FormDrawer>
  );
}
