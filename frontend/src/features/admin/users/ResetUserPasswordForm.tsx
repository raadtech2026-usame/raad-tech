import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Check, Copy, KeyRound } from "lucide-react";
import { useState } from "react";
import { Button } from "../../../shared/components/Button/Button";
import { FormDrawer } from "../../../shared/components/Drawer/FormDrawer";
import { FormField } from "../../../shared/components/FormField/FormField";
import { Input } from "../../../shared/components/Input/Input";
import { useToast } from "../../../shared/components/Toast/toastStore";
import { ApiError } from "../../../shared/api/types";
import { resetUserPassword, type PasswordResetResult, type User } from "./api";
import styles from "./ResetUserPasswordForm.module.css";

export interface ResetUserPasswordFormProps {
  open: boolean;
  user: User | null;
  onClose: () => void;
}

/**
 * `POST /users/{id}/reset-password` (ADR-0017 Amendment) — the RAAD Super Admin's recovery
 * path when an Org Admin (or any other provisioned user) loses their temporary password before
 * ever logging in. No input fields: the new password is generated server-side, exactly once,
 * and revealed here — the same one-time-reveal pattern `CreateOrganizationForm.tsx` already
 * established for initial onboarding — never retrievable again afterward via any other route.
 */
export function ResetUserPasswordForm({ open, user, onClose }: ResetUserPasswordFormProps) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [result, setResult] = useState<PasswordResetResult | null>(null);
  const [copied, setCopied] = useState(false);

  const mutation = useMutation({
    mutationFn: () => {
      if (!user) {
        throw new Error("No user selected.");
      }
      return resetUserPassword(user.id);
    },
    onSuccess: (resetResult) => {
      queryClient.invalidateQueries({ queryKey: ["users", "list"] });
      toast.success(
        "Password reset",
        `${resetResult.user.fullName}'s password has been reset.`,
      );
      setResult(resetResult);
    },
    onError: (error) => {
      const message =
        error instanceof ApiError ? error.message : "Could not reset the password.";
      toast.error("Reset failed", message);
    },
  });

  function handleClose(): void {
    if (mutation.isPending) {
      return;
    }
    mutation.reset();
    setResult(null);
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

  if (!user) {
    return null;
  }

  if (result) {
    return (
      <FormDrawer
        open={open}
        onClose={handleClose}
        icon={<KeyRound size={22} />}
        iconTint="var(--color-brand-primary-tint)"
        iconColor="var(--color-brand-primary)"
        title="Password reset"
        subtitle="Hand this to the user — shown only once"
        footer={
          <div className={styles.footerActions}>
            <Button type="button" variant="primary" onClick={handleClose}>
              Done
            </Button>
          </div>
        }
      >
        <div className={styles.form}>
          <FormField label="User">
            <Input value={result.user.fullName} readOnly />
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
      icon={<KeyRound size={22} />}
      iconTint="var(--color-brand-primary-tint)"
      iconColor="var(--color-brand-primary)"
      title="Reset password"
      subtitle={`Generate a new temporary password for ${user.fullName}`}
      footer={
        <div className={styles.footerActions}>
          <Button
            type="button"
            variant="secondary"
            onClick={handleClose}
            disabled={mutation.isPending}
          >
            Cancel
          </Button>
          <Button
            type="button"
            variant="danger"
            loading={mutation.isPending}
            onClick={() => mutation.mutate()}
          >
            Reset password
          </Button>
        </div>
      }
    >
      <p className={styles.warning}>
        This immediately invalidates {user.fullName}&rsquo;s current password and signs them out
        of every active session. They&rsquo;ll need the new temporary password shown next to log
        back in, and will be forced to choose their own before doing anything else.
      </p>
    </FormDrawer>
  );
}
