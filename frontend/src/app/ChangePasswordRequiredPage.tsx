import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation } from "@tanstack/react-query";
import { KeyRound } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { changePassword } from "../shared/api/authApi";
import { ApiError } from "../shared/api/types";
import { getDashboardHomePath } from "../shared/auth/dashboard";
import { Button } from "../shared/components/Button/Button";
import { FormField } from "../shared/components/FormField/FormField";
import { Input } from "../shared/components/Input/Input";
import { useToast } from "../shared/components/Toast/toastStore";
import { useAuthStore } from "../shared/stores/authStore";
import styles from "./ChangePasswordRequiredPage.module.css";

const schema = z
  .object({
    newPassword: z.string().min(10, "Must be at least 10 characters"),
    confirmPassword: z.string(),
  })
  .refine((values) => values.newPassword === values.confirmPassword, {
    message: "Passwords do not match",
    path: ["confirmPassword"],
  });

type FormValues = z.infer<typeof schema>;

/**
 * ADR-0017 / ADR-0017 Amendment: `RouteGuard` (`enforcePasswordChange`) redirects here — before
 * any other `/platform`/`/org` route — whenever the signed-in principal still holds a one-time
 * hand-off temporary password (`Principal.isPasswordChangeRequired`, sourced from the backend's
 * own login/refresh response, not a client-only flag per `.claude/rules/frontend.md` #2). No
 * "current password" field: `POST /auth/change-password` is identified by the bearer token
 * alone and doesn't ask for one (`ChangePasswordRequest`, backend `iam/api/schemas.py`).
 */
export function ChangePasswordRequiredPage() {
  const toast = useToast();
  const navigate = useNavigate();
  const principal = useAuthStore((s) => s.principal);
  const clearPasswordChangeRequired = useAuthStore((s) => s.clearPasswordChangeRequired);

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { newPassword: "", confirmPassword: "" },
  });

  const mutation = useMutation({
    mutationFn: (values: FormValues) => changePassword(values.newPassword),
    onSuccess: () => {
      clearPasswordChangeRequired();
      toast.success("Password changed", "You're all set.");
      navigate(principal ? getDashboardHomePath(principal.role) : "/", { replace: true });
    },
    onError: (error) => {
      const message =
        error instanceof ApiError ? error.message : "Could not change the password.";
      toast.error("Change failed", message);
    },
  });

  const onValid = handleSubmit((values) => mutation.mutate(values));

  return (
    <main className={styles.page}>
      <div className={styles.card}>
        <div className={styles.brand}>
          <span className={styles.icon}>
            <KeyRound size={22} />
          </span>
          <div className={styles.heading}>Set a new password</div>
          <p className={styles.tagline}>
            Your account was created with a temporary password. Choose a new one before
            continuing.
          </p>
        </div>

        <form className={styles.form} onSubmit={onValid} noValidate>
          <FormField label="New password" error={errors.newPassword?.message}>
            <Input
              type="password"
              autoComplete="new-password"
              autoFocus
              invalid={!!errors.newPassword}
              {...register("newPassword")}
            />
          </FormField>
          <FormField label="Confirm password" error={errors.confirmPassword?.message}>
            <Input
              type="password"
              autoComplete="new-password"
              invalid={!!errors.confirmPassword}
              {...register("confirmPassword")}
            />
          </FormField>

          <Button
            type="submit"
            fullWidth
            loading={isSubmitting || mutation.isPending}
          >
            Change password
          </Button>
        </form>
      </div>
    </main>
  );
}
