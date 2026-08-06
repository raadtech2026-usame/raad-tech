import { useEffect, useRef, type ReactNode } from "react";
import { Button, type ButtonVariant } from "../Button/Button";
import styles from "./ConfirmDialog.module.css";

export interface ConfirmDialogProps {
  open: boolean;
  title: ReactNode;
  description?: ReactNode;
  /** Rendered below `description`, inside the dialog body — e.g. a card-entry form for a
   * payment confirmation. Optional; most callers (suspend/unassign/etc.) need only `description`. */
  children?: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  /** `"danger"` for a destructive/consequential action (matches `Button`'s own `dangerSolid`
   * variant); `"primary"` for a neutral confirm (e.g. "Pay now"). */
  tone?: "primary" | "danger";
  loading?: boolean;
  /** Disables the confirm button without a loading spinner — e.g. while a required child form
   * (a Stripe `CardElement`) hasn't been completed yet. */
  confirmDisabled?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

const TONE_TO_VARIANT: Record<NonNullable<ConfirmDialogProps["tone"]>, ButtonVariant> = {
  primary: "primary",
  danger: "dangerSolid",
};

/** A real, justified gap this frontend didn't have: every existing "are you sure" action
 * (suspend/unassign/etc.) went straight to a loading button + toast, since those are all cheaply
 * reversible admin actions. Charging a real card is not — this is the first genuinely
 * consequential action in this frontend, so it gets a real confirm step. Mirrors `DetailDrawer`'s
 * own dialog semantics (scrim, `role="dialog"`, Escape-to-close, focus management) rather than
 * inventing a second pattern for the same a11y requirements. */
export function ConfirmDialog({
  open,
  title,
  description,
  children,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  tone = "primary",
  loading = false,
  confirmDisabled = false,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const confirmButtonRef = useRef<HTMLButtonElement>(null);
  const previouslyFocused = useRef<HTMLElement | null>(null);
  const onCancelRef = useRef(onCancel);
  onCancelRef.current = onCancel;

  useEffect(() => {
    if (!open) {
      return;
    }
    previouslyFocused.current = document.activeElement as HTMLElement | null;
    confirmButtonRef.current?.focus();

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        onCancelRef.current();
      }
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      previouslyFocused.current?.focus();
    };
  }, [open]);

  if (!open) {
    return null;
  }

  return (
    <>
      <div className={styles.scrim} onClick={loading ? undefined : onCancel} />
      <div
        className={styles.dialog}
        role="dialog"
        aria-modal="true"
        aria-labelledby="confirm-dialog-title"
      >
        <div id="confirm-dialog-title" className={styles.title}>
          {title}
        </div>
        {description && <div className={styles.description}>{description}</div>}
        {children && <div className={styles.body}>{children}</div>}
        <div className={styles.actions}>
          <Button type="button" variant="secondary" onClick={onCancel} disabled={loading}>
            {cancelLabel}
          </Button>
          <Button
            ref={confirmButtonRef}
            type="button"
            variant={TONE_TO_VARIANT[tone]}
            onClick={onConfirm}
            loading={loading}
            disabled={confirmDisabled}
          >
            {confirmLabel}
          </Button>
        </div>
      </div>
    </>
  );
}
