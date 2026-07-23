import { useEffect } from "react";
import { CheckCircle2, XCircle, Info, X } from "lucide-react";
import { useToastStore, type ToastItem, type ToastVariant } from "./toastStore";
import styles from "./Toast.module.css";

const ICONS: Record<ToastVariant, React.ReactNode> = {
  success: <CheckCircle2 size={16} />,
  error: <XCircle size={16} />,
  info: <Info size={16} />,
};

const AUTO_DISMISS_MS = 5000;

function Toast({ toast }: { toast: ToastItem }) {
  const dismiss = useToastStore((s) => s.dismiss);

  useEffect(() => {
    const timer = setTimeout(() => dismiss(toast.id), AUTO_DISMISS_MS);
    return () => clearTimeout(timer);
  }, [toast.id, dismiss]);

  return (
    <div className={`${styles.toast} ${styles[toast.variant]}`} role="status">
      <span className={styles.icon}>{ICONS[toast.variant]}</span>
      <div className={styles.body}>
        <div className={styles.title}>{toast.title}</div>
        {toast.description && <div className={styles.description}>{toast.description}</div>}
      </div>
      <button
        type="button"
        className={styles.dismiss}
        onClick={() => dismiss(toast.id)}
        aria-label="Dismiss notification"
      >
        <X size={14} />
      </button>
    </div>
  );
}

/** Mounted once near the app root (see `app/providers.tsx`). Renders whatever's currently in
 * `useToastStore` — call sites never render a `<Toast>` directly, they call `useToast()`. */
export function ToastViewport() {
  const toasts = useToastStore((s) => s.toasts);

  if (toasts.length === 0) {
    return null;
  }

  return (
    <div className={styles.viewport} aria-live="polite">
      {toasts.map((toast) => (
        <Toast key={toast.id} toast={toast} />
      ))}
    </div>
  );
}
