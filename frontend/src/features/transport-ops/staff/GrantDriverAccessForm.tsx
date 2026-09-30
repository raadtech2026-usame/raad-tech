import { zodResolver } from "@hookform/resolvers/zod";
import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Copy, KeyRound } from "lucide-react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { Button } from "../../../shared/components/Button/Button";
import { FormDrawer } from "../../../shared/components/Drawer/FormDrawer";
import { FormField } from "../../../shared/components/FormField/FormField";
import { Input } from "../../../shared/components/Input/Input";
import { useToast } from "../../../shared/components/Toast/toastStore";
import { ApiError } from "../../../shared/api/types";
import { grantDriverAccess, type GrantDriverAccessResult, type Staff } from "./api";
import styles from "./Staff.module.css";

const E164_PATTERN = /^\+[1-9]\d{1,14}$/;

const schema = z
  .object({
    licenseNo: z.string().trim().min(1, "License number is required").max(64, "At most 64 characters"),
    email: z.string().trim().refine((value) => value === "" || z.string().email().safeParse(value).success, {
      message: "Must be a valid email address",
    }),
    phone: z.string().trim().refine((value) => value === "" || E164_PATTERN.test(value), {
      message: "Phone must be E.164 format, e.g. +252612345678",
    }),
  })
  .refine((values) => values.email !== "" || values.phone !== "", {
    message: "The login needs an email or a phone number.",
    path: ["phone"],
  });

type FormValues = z.infer<typeof schema>;

export interface GrantDriverAccessFormProps {
  open: boolean;
  onClose: () => void;
  staff: Staff;
}

/**
 * "Give driver access" (ADR-0049 §3): creates a driver login and a driver profile for someone
 * already on the staff list, so the person is never recorded twice. The one-time password is
 * shown once, like "New driver".
 */
export function GrantDriverAccessForm({ open, onClose, staff }: GrantDriverAccessFormProps) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [result, setResult] = useState<GrantDriverAccessResult | null>(null);
  const [copied, setCopied] = useState(false);

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<FormValues>({ resolver: zodResolver(schema), defaultValues: { licenseNo: "", email: "", phone: "" } });

  useEffect(() => {
    if (open) {
      reset({ licenseNo: "", email: "", phone: staff.phone ?? "" });
      setResult(null);
      setCopied(false);
    }
  }, [open, staff.phone, reset]);

  const mutation = useMutation({
    mutationFn: (values: FormValues) =>
      grantDriverAccess(staff.id, {
        licenseNo: values.licenseNo.trim(),
        email: values.email.trim() || null,
        phone: values.phone.trim() || null,
      }),
    onSuccess: (granted) => {
      queryClient.invalidateQueries({ queryKey: ["transport-staff"] });
      queryClient.invalidateQueries({ queryKey: ["drivers", "list"] });
      setResult(granted);
    },
    onError: (error) => {
      toast.error("Could not give driver access", error instanceof ApiError ? error.message : "Please try again.");
    },
  });

  function handleClose(): void {
    if (mutation.isPending) return;
    mutation.reset();
    onClose();
  }

  async function copyPassword(): Promise<void> {
    if (!result) return;
    try {
      await navigator.clipboard.writeText(result.temporaryPassword);
      setCopied(true);
    } catch {
      toast.error("Could not copy", "Select and copy the password manually.");
    }
  }

  const onValid = handleSubmit((values) => mutation.mutate(values));

  if (result) {
    return (
      <FormDrawer
        open={open}
        onClose={handleClose}
        icon={<CheckCircle2 size={22} />}
        iconTint="var(--color-success-tint)"
        iconColor="var(--color-success)"
        title="Driver access given"
        subtitle={`${staff.fullName} can now sign in to the driver app`}
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
            Share this one-time password with <strong>{staff.fullName}</strong> — it will not be shown again.
          </p>
          <div className={styles.passwordRow}>
            <code className={styles.password}>{result.temporaryPassword}</code>
            <Button type="button" variant="secondary" size="sm" leadingIcon={<Copy size={13} />} onClick={() => void copyPassword()}>
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
      icon={<KeyRound size={22} />}
      iconTint="var(--color-brand-primary-tint)"
      iconColor="var(--color-brand-primary)"
      title="Give driver access"
      subtitle={staff.fullName}
      footer={
        <div className={styles.footerActions}>
          <Button type="button" variant="secondary" onClick={handleClose} disabled={mutation.isPending}>
            Cancel
          </Button>
          <Button type="button" variant="primary" loading={mutation.isPending} onClick={onValid}>
            Give access
          </Button>
        </div>
      }
    >
      <form className={styles.form} onSubmit={onValid} noValidate>
        <FormField label="Driving licence number" error={errors.licenseNo?.message}>
          <Input {...register("licenseNo")} aria-label="Driving licence number" autoComplete="off" />
        </FormField>
        <FormField label="Login email" error={errors.email?.message}>
          <Input type="email" {...register("email")} aria-label="Login email" />
        </FormField>
        <FormField label="Login phone" hint="Defaults to their staff phone" error={errors.phone?.message}>
          <Input {...register("phone")} aria-label="Login phone" placeholder="+252…" />
        </FormField>
      </form>
    </FormDrawer>
  );
}
