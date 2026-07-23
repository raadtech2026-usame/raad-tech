import { create } from "zustand";

export type ToastVariant = "success" | "error" | "info";

export interface ToastItem {
  id: string;
  variant: ToastVariant;
  title: string;
  description?: string;
}

interface ToastState {
  toasts: ToastItem[];
  push: (toast: Omit<ToastItem, "id">) => string;
  dismiss: (id: string) => void;
}

/** Global mutation feedback (success/error banners) — deliberately separate from the persisted
 * `Notification` domain object (C7): this is ephemeral UI feedback for the action the current
 * user just took, not the cross-device notification feed. Conflating the two would mean a toast
 * a user dismisses somehow needing to round-trip to `POST /notifications/{id}/read`, which makes
 * no sense for "your save succeeded." */
export const useToastStore = create<ToastState>((set) => ({
  toasts: [],
  push: (toast) => {
    const id = crypto.randomUUID();
    set((state) => ({ toasts: [...state.toasts, { ...toast, id }] }));
    return id;
  },
  dismiss: (id) => set((state) => ({ toasts: state.toasts.filter((t) => t.id !== id) })),
}));

export function useToast() {
  const push = useToastStore((s) => s.push);
  return {
    success: (title: string, description?: string) => push({ variant: "success", title, description }),
    error: (title: string, description?: string) => push({ variant: "error", title, description }),
    info: (title: string, description?: string) => push({ variant: "info", title, description }),
  };
}
