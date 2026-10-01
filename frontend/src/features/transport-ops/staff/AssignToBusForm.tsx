import { zodResolver } from "@hookform/resolvers/zod";
import { useEffect } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bus } from "lucide-react";
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
  assignToBus,
  listRoutesForPicker,
  listStaff,
  listStaffRoles,
  listVehiclesForPicker,
} from "./api";
import styles from "./Staff.module.css";

const schema = z
  .object({
    staffId: z.string().min(1, "Choose a staff member"),
    vehicleId: z.string().min(1, "Choose a bus"),
    kind: z.enum(["permanent", "temporary"]),
    startsOn: z.string(),
    endsOn: z.string(),
    roleId: z.string(),
    routeId: z.string(),
    reason: z.string().trim().max(255, "At most 255 characters"),
  })
  .refine((values) => values.kind === "permanent" || values.endsOn !== "", {
    message: "A temporary assignment needs an end date",
    path: ["endsOn"],
  })
  .refine((values) => !values.startsOn || !values.endsOn || values.endsOn >= values.startsOn, {
    message: "The end date is before the start date",
    path: ["endsOn"],
  });

type FormValues = z.infer<typeof schema>;

export interface AssignToBusFormProps {
  open: boolean;
  onClose: () => void;
  /** Fixed when opened from a staff profile. */
  staffId?: string;
  staffName?: string;
  /** Fixed when opened from a bus. */
  vehicleId?: string;
  vehicleLabel?: string;
  organizationId: string | null;
}

/**
 * Puts one staff member on one bus (ADR-0050). Opened from a staff profile (the bus is picked
 * here) or from a bus's Crew section (the person is picked here). The job title held now is
 * recorded on the assignment, so a later title change never rewrites this history. A person
 * already on the bus for any of the chosen days is refused by the server (409), shown as-is.
 */
export function AssignToBusForm({
  open,
  onClose,
  staffId,
  staffName,
  vehicleId,
  vehicleLabel,
  organizationId,
}: AssignToBusFormProps) {
  const toast = useToast();
  const queryClient = useQueryClient();

  const vehiclesQuery = useQuery({
    queryKey: ["transport-staff", "vehicle-picker", organizationId],
    queryFn: () => listVehiclesForPicker(organizationId),
    enabled: open && !vehicleId,
    staleTime: 60_000,
  });
  const staffQuery = useQuery({
    queryKey: ["transport-staff", "staff-picker"],
    queryFn: () =>
      listStaff({ page: 1, pageSize: 100, sort: { field: "full_name", direction: "asc" }, filters: { status: "active" }, search: "" }),
    enabled: open && !staffId,
    staleTime: 30_000,
  });
  const rolesQuery = useQuery({
    queryKey: ["transport-staff", "roles"],
    queryFn: () => listStaffRoles(),
    enabled: open,
    staleTime: 60_000,
  });
  const routesQuery = useQuery({
    queryKey: ["transport-staff", "route-picker"],
    queryFn: () => listRoutesForPicker(),
    enabled: open,
    staleTime: 60_000,
  });

  const {
    register,
    handleSubmit,
    reset,
    watch,
    formState: { errors },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { staffId: "", vehicleId: "", kind: "permanent", startsOn: "", endsOn: "", roleId: "", routeId: "", reason: "" },
  });

  useEffect(() => {
    if (open) {
      reset({
        staffId: staffId ?? "",
        vehicleId: vehicleId ?? "",
        kind: "permanent",
        startsOn: "",
        endsOn: "",
        roleId: "",
        routeId: "",
        reason: "",
      });
    }
  }, [open, staffId, vehicleId, reset]);

  const kind = watch("kind");

  const mutation = useMutation({
    mutationFn: (values: FormValues) =>
      assignToBus({
        staffId: values.staffId,
        vehicleId: values.vehicleId,
        kind: values.kind,
        startsOn: values.startsOn || null,
        endsOn: values.endsOn || null,
        roleId: values.roleId || null,
        routeId: values.routeId || null,
        reason: values.reason.trim() || null,
      }),
    onSuccess: (assignment) => {
      queryClient.invalidateQueries({ queryKey: ["transport-staff", "crew"] });
      toast.success("Assigned to bus", assignment.staffName);
      for (const warning of assignment.warnings) toast.info("Documents", warning);
      onClose();
    },
    onError: (error) => {
      toast.error("Could not assign", error instanceof ApiError ? error.message : "Please try again.");
    },
  });

  const onValid = handleSubmit((values) => mutation.mutate(values));
  const roles = (rolesQuery.data ?? []).filter((role) => !role.isArchived);

  return (
    <FormDrawer
      open={open}
      onClose={() => !mutation.isPending && onClose()}
      icon={<Bus size={22} />}
      iconTint="var(--color-brand-primary-tint)"
      iconColor="var(--color-brand-primary)"
      title="Assign to bus"
      subtitle={staffName ?? vehicleLabel ?? "Bus crew"}
      footer={
        <div className={styles.footerActions}>
          <Button type="button" variant="secondary" onClick={onClose} disabled={mutation.isPending}>
            Cancel
          </Button>
          <Button type="button" variant="primary" loading={mutation.isPending} onClick={onValid}>
            Assign
          </Button>
        </div>
      }
    >
      <form className={styles.form} onSubmit={onValid} noValidate>
        {!staffId && (
          <FormField label="Staff member" error={errors.staffId?.message}>
            <Select {...register("staffId")} aria-label="Staff member" disabled={staffQuery.isLoading}>
              <option value="">Choose…</option>
              {(staffQuery.data?.data ?? []).map((person) => (
                <option key={person.id} value={person.id}>
                  {person.fullName}
                  {person.roleName ? ` — ${person.roleName}` : ""}
                </option>
              ))}
            </Select>
          </FormField>
        )}
        {!vehicleId && (
          <FormField label="Bus" error={errors.vehicleId?.message}>
            <Select {...register("vehicleId")} aria-label="Bus" disabled={vehiclesQuery.isLoading}>
              <option value="">Choose…</option>
              {(vehiclesQuery.data ?? []).map((vehicle) => (
                <option key={vehicle.id} value={vehicle.id}>
                  {vehicle.plateNo}
                  {vehicle.label ? ` — ${vehicle.label}` : ""}
                </option>
              ))}
            </Select>
          </FormField>
        )}
        <FormField label="Kind">
          <Select {...register("kind")} aria-label="Kind">
            <option value="permanent">Permanent</option>
            <option value="temporary">Temporary (needs an end date)</option>
          </Select>
        </FormField>
        <div className={styles.formRow}>
          <FormField label="Starts" hint="Leave empty for today">
            <Input type="date" {...register("startsOn")} aria-label="Starts" />
          </FormField>
          <FormField label="Ends" hint={kind === "temporary" ? "Required" : "Optional"} error={errors.endsOn?.message}>
            <Input type="date" {...register("endsOn")} aria-label="Ends" />
          </FormField>
        </div>
        <div className={styles.formRow}>
          <FormField label="Job title on this bus" hint="Leave empty to use their current title">
            <Select {...register("roleId")} aria-label="Job title on this bus">
              <option value="">Their current title</option>
              {roles.map((role) => (
                <option key={role.id} value={role.id}>
                  {role.name}
                </option>
              ))}
            </Select>
          </FormField>
          <FormField label="Route" hint="Optional">
            <Select {...register("routeId")} aria-label="Route">
              <option value="">No specific route</option>
              {(routesQuery.data ?? []).map((route) => (
                <option key={route.id} value={route.id}>
                  {route.name}
                </option>
              ))}
            </Select>
          </FormField>
        </div>
        <FormField label="Reason" hint="Optional, e.g. covering for a colleague" error={errors.reason?.message}>
          <Input {...register("reason")} aria-label="Reason" />
        </FormField>
      </form>
    </FormDrawer>
  );
}
