import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarDays, ChevronLeft, ChevronRight, Plus } from "lucide-react";
import { usePageHeader } from "../../../app/layout/PageHeaderContext";
import { useAuthStore } from "../../../shared/stores/authStore";
import { useToast } from "../../../shared/components/Toast/toastStore";
import { ApiError } from "../../../shared/api/types";
import { Badge } from "../../../shared/components/Badge/Badge";
import { Button } from "../../../shared/components/Button/Button";
import { ConfirmDialog } from "../../../shared/components/ConfirmDialog/ConfirmDialog";
import { EmptyState } from "../../../shared/components/EmptyState/EmptyState";
import { FormField } from "../../../shared/components/FormField/FormField";
import { Input } from "../../../shared/components/Input/Input";
import { Skeleton } from "../../../shared/components/Skeleton/Skeleton";
import { Tabs } from "../../../shared/components/Tabs/Tabs";
import { CancelTripDialog } from "./CancelTripDialog";
import { CoverForm, TimetableForm, UnavailabilityForm } from "./OperationsForms";
import {
  generateTrips,
  getDailyBoard,
  getDaySafety,
  listClosures,
  listTimetable,
  listUnavailability,
  listVehicleOptions,
  recordClosure,
  withdrawClosure,
  withdrawCover,
  withdrawUnavailability,
  type BoardTrip,
  type GenerationResult,
  type TimetableEntry,
  type Unavailability,
} from "./api";
import {
  addDays,
  formatDay,
  formatPeriod,
  formatTime,
  isoDay,
  periodLabel,
  reasonLabel,
  uncoveredLabel,
  weekdaysLabel,
} from "./labels";
import styles from "./Operations.module.css";

function errorText(error: unknown): string {
  return error instanceof ApiError ? error.message : "Please try again.";
}

function useVehicleLabels() {
  const query = useQuery({ queryKey: ["operations", "vehicle-options"], queryFn: listVehicleOptions, staleTime: 60_000 });
  return useMemo(() => new Map((query.data ?? []).map((o) => [o.id, o.label])), [query.data]);
}

// ---- board ------------------------------------------------------------------------------------

function BoardPanel({ canManage }: { canManage: boolean }) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [day, setDay] = useState(isoDay(new Date()));
  const [cancelling, setCancelling] = useState<BoardTrip | null>(null);
  const [preview, setPreview] = useState<GenerationResult | null>(null);
  const vehicleLabel = useVehicleLabels();
  const board = useQuery({ queryKey: ["daily-operations", day], queryFn: () => getDailyBoard(day) });
  // A failure here leaves the board as it was: safety counts are a pointer to /safety, not the record.
  const safety = useQuery({ queryKey: ["daily-operations", day, "safety"], queryFn: () => getDaySafety(day) });
  const alertCount = (id: string) => safety.data?.alerts.get(id) ?? 0;
  const incidentCount = (id: string) => safety.data?.incidents.get(id) ?? 0;
  const dayAlerts = safety.data?.alertTotal ?? 0;
  const dayIncidents = safety.data?.incidentTotal ?? 0;

  const previewMutation = useMutation({
    mutationFn: () => generateTrips(7, true),
    onSuccess: setPreview,
    onError: (error) => toast.error("Could not preview", errorText(error)),
  });
  const generateMutation = useMutation({
    mutationFn: () => generateTrips(7, false),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ["daily-operations"] });
      queryClient.invalidateQueries({ queryKey: ["trips"] });
      setPreview(null);
      toast.success("Trips generated", `${result.created} trip(s) created for the next 7 days.`);
    },
    onError: (error) => toast.error("Could not generate", errorText(error)),
  });

  const data = board.data;
  return (
    <div className={styles.page}>
      <div className={styles.toolbar}>
        <div className={styles.dayBar}>
          <Button size="sm" variant="ghost" aria-label="Previous day" onClick={() => setDay(addDays(day, -1))}>
            <ChevronLeft size={16} />
          </Button>
          <Input type="date" aria-label="Date" value={day} onChange={(e) => e.target.value && setDay(e.target.value)} />
          <Button size="sm" variant="ghost" aria-label="Next day" onClick={() => setDay(addDays(day, 1))}>
            <ChevronRight size={16} />
          </Button>
          <Button size="sm" variant="secondary" onClick={() => setDay(isoDay(new Date()))}>
            Today
          </Button>
        </div>
        {canManage && (
          <Button leadingIcon={<CalendarDays size={15} />} loading={previewMutation.isPending} onClick={() => previewMutation.mutate()}>
            Generate the next 7 days
          </Button>
        )}
      </div>

      {board.isLoading ? (
        <Skeleton height={160} />
      ) : board.isError || !data ? (
        <EmptyState icon={<CalendarDays size={22} />} title="Could not load the day" description={errorText(board.error)} />
      ) : (
        <>
          <div className={styles.summary}>
            <strong>{formatDay(data.date)}</strong>
            {data.uncoveredTrips > 0 ? (
              <Badge variant="danger" dot>
                {data.uncoveredTrips} uncovered trip{data.uncoveredTrips === 1 ? "" : "s"}
              </Badge>
            ) : (
              <Badge variant="success" dot>
                Every trip covered
              </Badge>
            )}
            {dayAlerts > 0 && (
              <Badge variant="danger">
                {dayAlerts} safety alert{dayAlerts === 1 ? "" : "s"}
              </Badge>
            )}
            {dayIncidents > 0 && (
              <Badge variant="warning">
                {dayIncidents} incident{dayIncidents === 1 ? "" : "s"}
              </Badge>
            )}
            {data.closures.map((label) => (
              <Badge key={label} variant="warning">
                Closed: {label}
              </Badge>
            ))}
          </div>
          {data.vehicles.length === 0 ? (
            <EmptyState
              icon={<CalendarDays size={22} />}
              title="Nothing scheduled"
              description="No trips or crew for this day. Set up the timetable, then generate trips."
            />
          ) : (
            <div className={styles.boardGrid}>
              {data.vehicles.map((vehicle) => (
                <section key={vehicle.vehicleId} className={styles.section} aria-label={vehicleLabel.get(vehicle.vehicleId) ?? "Bus"}>
                  <div className={styles.sectionHeader}>
                    <span className={styles.itemTitle}>{vehicleLabel.get(vehicle.vehicleId) ?? vehicle.vehicleId}</span>
                    <span className={styles.itemActions}>
                      {alertCount(vehicle.vehicleId) > 0 && (
                        <Badge variant="danger">
                          {alertCount(vehicle.vehicleId)} alert{alertCount(vehicle.vehicleId) === 1 ? "" : "s"}
                        </Badge>
                      )}
                      {incidentCount(vehicle.vehicleId) > 0 && (
                        <Badge variant="warning">
                          {incidentCount(vehicle.vehicleId)} incident{incidentCount(vehicle.vehicleId) === 1 ? "" : "s"}
                        </Badge>
                      )}
                      {vehicle.crewGaps > 0 && <Badge variant="warning">{vehicle.crewGaps} crew gap{vehicle.crewGaps === 1 ? "" : "s"}</Badge>}
                    </span>
                  </div>
                  <span className={styles.sectionTitle}>Trips</span>
                  {vehicle.trips.length === 0 ? (
                    <p className={styles.empty}>No trips.</p>
                  ) : (
                    <ul className={styles.list}>
                      {vehicle.trips.map((trip) => (
                        <li key={trip.id} className={styles.item}>
                          <div className={styles.itemMain}>
                            <span className={styles.itemTitle}>
                              {periodLabel(trip.tripType)}
                              {trip.plannedDeparture ? ` · ${formatTime(trip.plannedDeparture)}` : ""}
                              {trip.routeName ? ` · ${trip.routeName}` : ""}
                            </span>
                            <span className={styles.itemMeta}>
                              Driver: {trip.driverName ?? "—"}
                              {trip.cancelledReason ? ` · Cancelled: ${trip.cancelledReason}` : ""}
                            </span>
                          </div>
                          <div className={styles.itemActions}>
                            {trip.status === "cancelled" ? (
                              <Badge variant="neutral">Cancelled</Badge>
                            ) : trip.uncoveredReason ? (
                              <Badge variant="danger" dot>
                                {uncoveredLabel(trip.uncoveredReason)}
                              </Badge>
                            ) : (
                              <Badge variant="success">Covered</Badge>
                            )}
                            {canManage && trip.status === "scheduled" && (
                              <Button size="sm" variant="ghost" onClick={() => setCancelling(trip)}>
                                Cancel
                              </Button>
                            )}
                          </div>
                        </li>
                      ))}
                    </ul>
                  )}
                  <span className={styles.sectionTitle}>Crew</span>
                  {vehicle.crew.length === 0 ? (
                    <p className={styles.empty}>No crew assigned.</p>
                  ) : (
                    <ul className={styles.list}>
                      {vehicle.crew.map((member) => (
                        <li key={member.staffId} className={styles.item}>
                          <div className={styles.itemMain}>
                            <span className={styles.itemTitle}>{member.staffName}</span>
                            <span className={styles.itemMeta}>{member.roleName ?? "No title"}</span>
                          </div>
                          <div className={styles.itemActions}>
                            {member.isSubstitute && <Badge variant="info">Substitute</Badge>}
                            {member.isUnavailable &&
                              (member.coveredBy ? (
                                <Badge variant="warning">Away · covered by {member.coveredBy}</Badge>
                              ) : (
                                <Badge variant="danger">Away · not covered</Badge>
                              ))}
                          </div>
                        </li>
                      ))}
                    </ul>
                  )}
                </section>
              ))}
            </div>
          )}
        </>
      )}

      <CancelTripDialog
        tripId={cancelling?.id ?? null}
        description={cancelling ? `${periodLabel(cancelling.tripType)} trip on ${formatDay(day)}` : ""}
        onClose={() => setCancelling(null)}
      />
      <ConfirmDialog
        open={preview !== null}
        title="Generate trips for the next 7 days?"
        description={
          preview
            ? `${preview.toCreate.length} trip(s) will be created` +
              (preview.closedDays.length ? `, ${preview.closedDays.length} closed day(s) skipped` : "") +
              (preview.skipped.length ? `, ${preview.skipped.length} timetable entr(ies) skipped (inactive route, driver or bus)` : "") +
              ". Existing trips are never duplicated."
            : undefined
        }
        confirmLabel="Generate"
        loading={generateMutation.isPending}
        confirmDisabled={preview?.toCreate.length === 0}
        onConfirm={() => generateMutation.mutate()}
        onCancel={() => setPreview(null)}
      />
    </div>
  );
}

// ---- absences -----------------------------------------------------------------------------------

export function UnavailabilityList({
  items,
  canManage,
  showStaff,
  onCover,
}: {
  items: Unavailability[];
  canManage: boolean;
  showStaff: boolean;
  onCover: (item: Unavailability) => void;
}) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [withdrawing, setWithdrawing] = useState<Unavailability | null>(null);
  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["operations", "unavailability"] });
    queryClient.invalidateQueries({ queryKey: ["daily-operations"] });
    queryClient.invalidateQueries({ queryKey: ["trips"] });
  };
  const withdraw = useMutation({
    mutationFn: (id: string) => withdrawUnavailability(id),
    onSuccess: () => {
      invalidate();
      setWithdrawing(null);
      toast.success("Withdrawn", "Its covers are withdrawn and drivers restored where available.");
    },
    onError: (error) => toast.error("Could not withdraw", errorText(error)),
  });
  const withdrawCoverMutation = useMutation({
    mutationFn: (id: string) => withdrawCover(id),
    onSuccess: () => {
      invalidate();
      toast.success("Cover withdrawn", "The original driver has their trips back where available.");
    },
    onError: (error) => toast.error("Could not withdraw the cover", errorText(error)),
  });

  if (items.length === 0) return <p className={styles.empty}>No unavailability recorded.</p>;
  return (
    <>
      <ul className={styles.list}>
        {items.map((item) => (
          <li key={item.id} className={styles.item}>
            <div className={styles.itemMain}>
              <span className={styles.itemTitle}>
                {showStaff ? `${item.staffName} · ` : ""}
                {formatPeriod(item.startsOn, item.endsOn)}
              </span>
              <span className={styles.itemMeta}>
                {reasonLabel(item.reason)}
                {item.privateFieldsVisible ? (item.note ? ` · ${item.note}` : "") : " · Note visible to Org Admins only"}
              </span>
              {item.covers
                .filter((c) => !c.withdrawnAt)
                .map((c) => (
                  <span key={c.id} className={styles.itemMeta}>
                    Covered by {c.substituteStaffName}, {formatPeriod(c.startsOn, c.endsOn)}
                    {canManage && !item.withdrawnAt && (
                      <>
                        {" "}
                        <Button size="sm" variant="ghost" onClick={() => withdrawCoverMutation.mutate(c.id)}>
                          Withdraw cover
                        </Button>
                      </>
                    )}
                  </span>
                ))}
            </div>
            <div className={styles.itemActions}>
              {item.withdrawnAt ? (
                <Badge variant="neutral">Withdrawn</Badge>
              ) : (
                canManage && (
                  <>
                    <Button size="sm" variant="secondary" onClick={() => onCover(item)}>
                      Cover
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => setWithdrawing(item)}>
                      Withdraw
                    </Button>
                  </>
                )
              )}
            </div>
          </li>
        ))}
      </ul>
      <ConfirmDialog
        open={withdrawing !== null}
        title="Withdraw this unavailability?"
        description="Its covers are withdrawn too, and the original driver gets their scheduled trips back where available."
        confirmLabel="Withdraw"
        tone="danger"
        loading={withdraw.isPending}
        onConfirm={() => withdrawing && withdraw.mutate(withdrawing.id)}
        onCancel={() => setWithdrawing(null)}
      />
    </>
  );
}

function AbsencesPanel({ canManage }: { canManage: boolean }) {
  const today = isoDay(new Date());
  const [recording, setRecording] = useState(false);
  const [covering, setCovering] = useState<Unavailability | null>(null);
  const query = useQuery({
    queryKey: ["operations", "unavailability", "upcoming"],
    queryFn: () => listUnavailability({ start: today, end: addDays(today, 60) }),
  });
  return (
    <section className={styles.section} aria-label="Unavailability">
      <div className={styles.sectionHeader}>
        <span className={styles.sectionTitle}>Unavailable in the next 60 days</span>
        {canManage && (
          <Button size="sm" leadingIcon={<Plus size={14} />} onClick={() => setRecording(true)}>
            Record unavailability
          </Button>
        )}
      </div>
      {query.isLoading ? <Skeleton height={60} /> : <UnavailabilityList items={query.data ?? []} canManage={canManage} showStaff onCover={setCovering} />}
      <UnavailabilityForm open={recording} onClose={() => setRecording(false)} />
      <CoverForm unavailability={covering} onClose={() => setCovering(null)} />
    </section>
  );
}

// ---- timetable ----------------------------------------------------------------------------------

function TimetablePanel({ canManage }: { canManage: boolean }) {
  const [editing, setEditing] = useState<TimetableEntry | null | "new">(null);
  const vehicleLabel = useVehicleLabels();
  const query = useQuery({ queryKey: ["operations", "timetable"], queryFn: listTimetable });
  const entries = query.data ?? [];
  return (
    <section className={styles.section} aria-label="Timetable">
      <div className={styles.sectionHeader}>
        <span className={styles.sectionTitle}>Weekly timetable</span>
        {canManage && (
          <Button size="sm" leadingIcon={<Plus size={14} />} onClick={() => setEditing("new")}>
            Add run
          </Button>
        )}
      </div>
      {query.isLoading ? (
        <Skeleton height={60} />
      ) : entries.length === 0 ? (
        <p className={styles.empty}>No regular runs yet. Each run generates one trip per matching day.</p>
      ) : (
        <ul className={styles.list}>
          {entries.map((e) => (
            <li key={e.id} className={styles.item}>
              <div className={styles.itemMain}>
                <span className={styles.itemTitle}>
                  {vehicleLabel.get(e.vehicleId) ?? e.vehicleId} · {periodLabel(e.tripType)}
                  {e.plannedDeparture ? ` · ${formatTime(e.plannedDeparture)}` : ""} · {e.routeName ?? e.routeId}
                </span>
                <span className={styles.itemMeta}>
                  {weekdaysLabel(e.weekdays)} · Driver: {e.defaultDriverName ?? "—"} · From {formatDay(e.validFrom)}
                  {e.validUntil ? ` until ${formatDay(e.validUntil)}` : ""}
                </span>
              </div>
              <div className={styles.itemActions}>
                {!e.isActive && <Badge variant="neutral">Inactive</Badge>}
                {canManage && (
                  <Button size="sm" variant="ghost" onClick={() => setEditing(e)}>
                    Edit
                  </Button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
      <TimetableForm open={editing !== null} entry={editing === "new" ? null : editing} onClose={() => setEditing(null)} />
    </section>
  );
}

// ---- closed days ------------------------------------------------------------------------------

function ClosuresPanel({ canManage }: { canManage: boolean }) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const today = isoDay(new Date());
  const [values, setValues] = useState({ startsOn: today, endsOn: today, label: "" });
  const query = useQuery({ queryKey: ["operations", "closures"], queryFn: () => listClosures(today, addDays(today, 365)) });
  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["operations", "closures"] });
    queryClient.invalidateQueries({ queryKey: ["daily-operations"] });
  };
  const record = useMutation({
    mutationFn: () => recordClosure({ ...values, label: values.label.trim() }),
    onSuccess: () => {
      invalidate();
      setValues({ startsOn: today, endsOn: today, label: "" });
      toast.success("Closed days recorded", "Trips already generated for them are not cancelled; cancel them on the board.");
    },
    onError: (error) => toast.error("Could not record", errorText(error)),
  });
  const withdraw = useMutation({
    mutationFn: (id: string) => withdrawClosure(id),
    onSuccess: invalidate,
    onError: (error) => toast.error("Could not withdraw", errorText(error)),
  });
  const invalid = !values.label.trim() || values.endsOn < values.startsOn;
  return (
    <section className={styles.section} aria-label="Closed days">
      <span className={styles.sectionTitle}>Closed days (next 12 months)</span>
      {query.isLoading ? (
        <Skeleton height={48} />
      ) : (query.data ?? []).length === 0 ? (
        <p className={styles.empty}>No closed days recorded.</p>
      ) : (
        <ul className={styles.list}>
          {(query.data ?? []).map((c) => (
            <li key={c.id} className={styles.item}>
              <div className={styles.itemMain}>
                <span className={styles.itemTitle}>{c.label}</span>
                <span className={styles.itemMeta}>{formatPeriod(c.startsOn, c.endsOn)}</span>
              </div>
              {canManage && (
                <Button size="sm" variant="ghost" onClick={() => withdraw.mutate(c.id)}>
                  Withdraw
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
      {canManage && (
        <form className={styles.inlineForm} onSubmit={(e) => { e.preventDefault(); if (!invalid) record.mutate(); }}>
          <FormField label="Label">
            <Input aria-label="Closure label" value={values.label} maxLength={120} placeholder="e.g. Eid holidays" onChange={(e) => setValues({ ...values, label: e.target.value })} />
          </FormField>
          <FormField label="From">
            <Input type="date" aria-label="Closed from" value={values.startsOn} onChange={(e) => setValues({ ...values, startsOn: e.target.value })} />
          </FormField>
          <FormField label="Until">
            <Input type="date" aria-label="Closed until" value={values.endsOn} onChange={(e) => setValues({ ...values, endsOn: e.target.value })} />
          </FormField>
          <Button type="submit" size="sm" loading={record.isPending} disabled={invalid}>
            Add
          </Button>
        </form>
      )}
    </section>
  );
}

/**
 * `/org/operations` and `/platform/operations` (ADR-0052, ADR-0053, ADR-0054): is every bus
 * covered today? The Org Admin manages; Founder, Regional Manager and Support Staff read.
 * `canManage` is presentation only (`.claude/rules/frontend.md` #2).
 */
export function DailyOperationsPage() {
  usePageHeader("Daily Operations", "Every bus's trips, crew and cover, day by day");
  const principal = useAuthStore((s) => s.principal);
  const canManage = principal?.role === "org_admin";
  const [tab, setTab] = useState("board");
  const tabs = [
    { id: "board", label: "Board" },
    { id: "absences", label: "Unavailability" },
    { id: "timetable", label: "Timetable" },
    { id: "closures", label: "Closed days" },
  ];
  return (
    <div className={styles.page}>
      <Tabs options={tabs} activeId={tab} onSelect={setTab} />
      {tab === "board" && <BoardPanel canManage={canManage} />}
      {tab === "absences" && <AbsencesPanel canManage={canManage} />}
      {tab === "timetable" && <TimetablePanel canManage={canManage} />}
      {tab === "closures" && <ClosuresPanel canManage={canManage} />}
    </div>
  );
}
