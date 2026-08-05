import { Truck } from "lucide-react";
import { Card, CardHeader } from "../../shared/components/Card/Card";
import { EmptyState } from "../../shared/components/EmptyState/EmptyState";
import { Skeleton } from "../../shared/components/Skeleton/Skeleton";
import { statusLabel, statusTone } from "../../features/fleet-devices/vehicles/labels";
import type { VehicleStatus } from "../../features/fleet-devices/vehicles/api";
import { useVehicleStatusCounts } from "./hooks";
import { StatBar, type StatBarItem } from "./StatBar";
import sectionStyles from "./dashboard.module.css";

const STATUSES: VehicleStatus[] = ["active", "maintenance", "inactive"];

/** Vehicle status breakdown (`GET /vehicles`, count-only per status — see `hooks.ts`'s
 * `useVehicleStatusCounts`) — `PlatformStats` (ADR-0020) only carries a flat vehicle total, no
 * breakdown, so this is the only source for "how healthy is the fleet, not just how big is it."
 * Reuses `fleet-devices/vehicles/labels.ts`'s own `statusLabel`/`statusTone` rather than a second,
 * possibly-drifting copy. */
export function FleetHealthSection() {
  const counts = useVehicleStatusCounts();

  const items: StatBarItem[] = STATUSES.map((status) => ({
    key: status,
    label: statusLabel(status),
    value: counts[status],
    tone: statusTone(status),
  }));

  return (
    <Card>
      <CardHeader title="Fleet Health" />
      <div className={sectionStyles.panelBody}>
        {counts.isError ? (
          <EmptyState icon={<Truck size={20} />} title="Could not load fleet health" />
        ) : counts.isLoading ? (
          <Skeleton height={10} />
        ) : (
          <StatBar items={items} emptyLabel="No vehicles registered yet." />
        )}
      </div>
    </Card>
  );
}
