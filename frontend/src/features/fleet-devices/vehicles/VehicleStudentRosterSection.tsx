import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRightLeft, Phone, Search, UserMinus } from "lucide-react";
import { Button } from "../../../shared/components/Button/Button";
import { ConfirmDialog } from "../../../shared/components/ConfirmDialog/ConfirmDialog";
import { FormField } from "../../../shared/components/FormField/FormField";
import { Input } from "../../../shared/components/Input/Input";
import { Select } from "../../../shared/components/Select/Select";
import { Skeleton } from "../../../shared/components/Skeleton/Skeleton";
import { useToast } from "../../../shared/components/Toast/toastStore";
import { ApiError } from "../../../shared/api/types";
import {
  endStudentAssignment,
  getVehicleStudentRoster,
  listVehiclesForPicker,
  transferStudentToVehicle,
  type VehicleOption,
  type VehicleStudentRosterItem,
} from "../../transport-ops/student-assignments/api";
import { setFamilyTransportation } from "../../transport-ops/parents/api";
import styles from "./VehicleStudentRosterSection.module.css";

export interface VehicleStudentRosterSectionProps {
  vehicleId: string;
  organizationId: string;
  canManage: boolean;
}

export function VehicleStudentRosterSection({
  vehicleId,
  organizationId,
  canManage,
}: VehicleStudentRosterSectionProps) {
  const toast = useToast();
  const queryClient = useQueryClient();

  const [searchTerm, setSearchTerm] = useState("");
  const [transferItem, setTransferItem] = useState<VehicleStudentRosterItem | null>(null);
  const [targetVehicleId, setTargetVehicleId] = useState("");
  const [transferMode, setTransferMode] = useState<"family" | "single">("family");

  const [removeItem, setRemoveItem] = useState<VehicleStudentRosterItem | null>(null);
  const [removeMode, setRemoveMode] = useState<"family" | "single">("family");

  const rosterQuery = useQuery({
    queryKey: ["vehicle-student-roster", vehicleId],
    queryFn: () => getVehicleStudentRoster(vehicleId),
    enabled: !!vehicleId,
  });

  const vehiclesQuery = useQuery({
    queryKey: ["vehicles", "picker-for-transfer", organizationId],
    queryFn: () => listVehiclesForPicker(organizationId, ""),
    enabled: canManage && !!organizationId,
    staleTime: 60_000,
  });

  const otherVehicles: VehicleOption[] = useMemo(() => {
    return (vehiclesQuery.data ?? []).filter((v) => v.id !== vehicleId);
  }, [vehiclesQuery.data, vehicleId]);

  const roster = rosterQuery.data ?? [];

  const filteredRoster = useMemo(() => {
    if (!searchTerm.trim()) return roster;
    const term = searchTerm.toLowerCase().trim();
    return roster.filter(
      (item) =>
        item.studentName.toLowerCase().includes(term) ||
        (item.parentName && item.parentName.toLowerCase().includes(term)) ||
        (item.parentPhone && item.parentPhone.includes(term)) ||
        (item.studentGrade && item.studentGrade.toLowerCase().includes(term)),
    );
  }, [roster, searchTerm]);

  const transferMutation = useMutation({
    mutationFn: async () => {
      if (!transferItem || !targetVehicleId) {
        throw new Error("Target vehicle is required");
      }
      if (transferMode === "family" && transferItem.parentId) {
        await setFamilyTransportation(transferItem.parentId, {
          vehicleId: targetVehicleId,
          routeId: null,
          pickupStopId: null,
          dropoffStopId: null,
        });
      } else {
        await transferStudentToVehicle(
          organizationId,
          transferItem.assignmentId,
          transferItem.studentId,
          targetVehicleId,
        );
      }
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["vehicle-student-roster"] });
      queryClient.invalidateQueries({ queryKey: ["student-assignments"] });
      queryClient.invalidateQueries({ queryKey: ["vehicles"] });
      toast.success(
        "Student transferred",
        transferMode === "family"
          ? "The family has been transferred to the new bus."
          : `${transferItem?.studentName} has been transferred to the new bus.`,
      );
      setTransferItem(null);
      setTargetVehicleId("");
    },
    onError: (error) => {
      const message = error instanceof ApiError ? error.message : "Could not transfer student.";
      toast.error("Transfer failed", message);
    },
  });

  const removeMutation = useMutation({
    mutationFn: async () => {
      if (!removeItem) {
        throw new Error("No student selected");
      }
      if (removeMode === "family" && removeItem.parentId) {
        await setFamilyTransportation(removeItem.parentId, {
          vehicleId: null,
          routeId: null,
          pickupStopId: null,
          dropoffStopId: null,
        });
      } else {
        await endStudentAssignment(removeItem.assignmentId, "removed");
      }
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["vehicle-student-roster"] });
      queryClient.invalidateQueries({ queryKey: ["student-assignments"] });
      queryClient.invalidateQueries({ queryKey: ["vehicles"] });
      toast.success(
        "Removed from bus",
        removeMode === "family"
          ? "The family was safely removed from bus transportation."
          : `${removeItem?.studentName} was safely removed from this bus.`,
      );
      setRemoveItem(null);
    },
    onError: (error) => {
      const message = error instanceof ApiError ? error.message : "Could not remove student from bus.";
      toast.error("Removal failed", message);
    },
  });

  function openTransfer(item: VehicleStudentRosterItem) {
    setTransferItem(item);
    setTransferMode(item.parentId ? "family" : "single");
    setTargetVehicleId(otherVehicles[0]?.id ?? "");
  }

  function openRemove(item: VehicleStudentRosterItem) {
    setRemoveItem(item);
    setRemoveMode(item.parentId ? "family" : "single");
  }

  return (
    <section className={styles.section} aria-label="Assigned Students">
      <div className={styles.sectionHeader}>
        <span className={styles.sectionTitle}>
          Assigned Students ({roster.length})
        </span>
      </div>

      {roster.length > 5 && (
        <div className={styles.searchWrap}>
          <Input
            icon={<Search size={13} />}
            placeholder="Search students or parents…"
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            aria-label="Filter roster"
          />
        </div>
      )}

      {rosterQuery.isLoading ? (
        <Skeleton height={56} />
      ) : rosterQuery.isError ? (
        <p className={styles.empty}>Could not load student roster.</p>
      ) : roster.length === 0 ? (
        <p className={styles.empty}>No students assigned to this bus.</p>
      ) : filteredRoster.length === 0 ? (
        <p className={styles.empty}>No students match the search filter.</p>
      ) : (
        <ul className={styles.list}>
          {filteredRoster.map((item) => (
            <li key={item.assignmentId} className={styles.item}>
              <div className={styles.itemMain}>
                <span className={styles.itemTitle}>
                  {item.studentName}
                  {item.studentGrade ? ` · ${item.studentGrade}` : ""}
                </span>
                <span className={styles.itemMeta}>
                  <span>Parent: {item.parentName ?? "Unlinked"}</span>
                  {item.parentPhone && (
                    <a
                      href={`tel:${item.parentPhone}`}
                      className={styles.phoneLink}
                      title={`Call ${item.parentPhone}`}
                    >
                      <Phone size={11} style={{ display: "inline", marginRight: "3px" }} />
                      {item.parentPhone}
                    </a>
                  )}
                </span>
              </div>
              {canManage && (
                <div className={styles.itemActions}>
                  <Button
                    size="sm"
                    variant="secondary"
                    leadingIcon={<ArrowRightLeft size={13} />}
                    onClick={() => openTransfer(item)}
                    title="Transfer to another bus"
                  >
                    Transfer
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    leadingIcon={<UserMinus size={13} />}
                    onClick={() => openRemove(item)}
                    title="Remove from bus safely"
                  >
                    Remove
                  </Button>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}

      {/* Transfer Dialog */}
      <ConfirmDialog
        open={transferItem !== null}
        title={`Transfer ${transferItem?.studentName} to another bus`}
        description="Choose the destination bus and whether to transfer all siblings together."
        confirmLabel="Transfer Now"
        confirmDisabled={!targetVehicleId}
        loading={transferMutation.isPending}
        onConfirm={() => transferMutation.mutate()}
        onCancel={() => setTransferItem(null)}
      >
        <div className={styles.modalBody}>
          {transferItem?.parentId && (
            <div className={styles.radioGroup}>
              <label className={styles.radioOption}>
                <input
                  type="radio"
                  name="transferMode"
                  value="family"
                  checked={transferMode === "family"}
                  onChange={() => setTransferMode("family")}
                />
                <span>
                  <strong>Transfer entire family</strong> (All siblings of {transferItem.parentName ?? "this parent"})
                </span>
              </label>
              <label className={styles.radioOption}>
                <input
                  type="radio"
                  name="transferMode"
                  value="single"
                  checked={transferMode === "single"}
                  onChange={() => setTransferMode("single")}
                />
                <span>Transfer this student only</span>
              </label>
            </div>
          )}

          <FormField label="Target Bus" hint="Select the new bus to assign.">
            <Select
              value={targetVehicleId}
              onChange={(e) => setTargetVehicleId(e.target.value)}
              aria-label="Target bus"
            >
              <option value="">Select bus…</option>
              {otherVehicles.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.plateNo} {v.label ? `— ${v.label}` : ""}
                </option>
              ))}
            </Select>
          </FormField>
        </div>
      </ConfirmDialog>

      {/* Remove Confirmation Dialog */}
      <ConfirmDialog
        open={removeItem !== null}
        title={`Remove ${removeItem?.studentName} from this bus?`}
        description="This safely unassigns the student from bus transportation. Student profile, billing history, and ledger records are fully preserved."
        confirmLabel="Remove from Bus"
        tone="danger"
        loading={removeMutation.isPending}
        onConfirm={() => removeMutation.mutate()}
        onCancel={() => setRemoveItem(null)}
      >
        {removeItem?.parentId && (
          <div className={styles.modalBody}>
            <div className={styles.radioGroup}>
              <label className={styles.radioOption}>
                <input
                  type="radio"
                  name="removeMode"
                  value="family"
                  checked={removeMode === "family"}
                  onChange={() => setRemoveMode("family")}
                />
                <span>
                  <strong>Remove entire family</strong> (All siblings of {removeItem.parentName ?? "this parent"})
                </span>
              </label>
              <label className={styles.radioOption}>
                <input
                  type="radio"
                  name="removeMode"
                  value="single"
                  checked={removeMode === "single"}
                  onChange={() => setRemoveMode("single")}
                />
                <span>Remove this student only</span>
              </label>
            </div>
          </div>
        )}
      </ConfirmDialog>
    </section>
  );
}
