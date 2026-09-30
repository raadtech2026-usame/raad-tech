import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ConfirmDialog } from "../../../shared/components/ConfirmDialog/ConfirmDialog";
import { FormField } from "../../../shared/components/FormField/FormField";
import { Input } from "../../../shared/components/Input/Input";
import { useToast } from "../../../shared/components/Toast/toastStore";
import { ApiError } from "../../../shared/api/types";
import { cancelTrip } from "./api";

export interface CancelTripDialogProps {
  tripId: string | null;
  /** e.g. "Morning trip, Wed 1 Oct" */
  description: string;
  onClose: () => void;
  onCancelled?: () => void;
}

/**
 * ADR-0054: cancels a scheduled trip. Final: a cancelled trip is never restored. The reason is
 * sent to the parents of the children on that route and bus, so the dialog says so.
 * Used by the Trips page and the Daily Operations board.
 */
export function CancelTripDialog({ tripId, description, onClose, onCancelled }: CancelTripDialogProps) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [reason, setReason] = useState("");

  useEffect(() => {
    if (tripId) setReason("");
  }, [tripId]);

  const mutation = useMutation({
    mutationFn: () => cancelTrip(tripId!, reason.trim()),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["trips"] });
      queryClient.invalidateQueries({ queryKey: ["daily-operations"] });
      toast.success("Trip cancelled", "Parents of the children on this trip are being told.");
      onCancelled?.();
      onClose();
    },
    onError: (error) => toast.error("Could not cancel", error instanceof ApiError ? error.message : "Please try again."),
  });

  return (
    <ConfirmDialog
      open={tripId !== null}
      title="Cancel this trip?"
      description={`${description}. This cannot be undone; a replacement trip can be created afterwards.`}
      confirmLabel="Cancel trip"
      cancelLabel="Keep trip"
      tone="danger"
      loading={mutation.isPending}
      confirmDisabled={reason.trim().length === 0}
      onConfirm={() => mutation.mutate()}
      onCancel={onClose}
    >
      <FormField label="Reason" hint="Parents will read this exactly as written.">
        <Input
          aria-label="Cancellation reason"
          value={reason}
          maxLength={255}
          onChange={(event) => setReason(event.target.value)}
          placeholder="e.g. The bus has broken down"
        />
      </FormField>
    </ConfirmDialog>
  );
}
